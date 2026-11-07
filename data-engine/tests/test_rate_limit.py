from dataclasses import replace
from decimal import Decimal
import json
import httpx
import pytest
from kb_pipeline.config import Settings
from kb_pipeline.contracts import PipelineError
from kb_pipeline.db import errors, runs
from kb_pipeline.engine import Engine
from kb_pipeline.groq import Groq
from kb_pipeline.logging import RunLog
from kb_pipeline.openrouter import OpenRouter
from kb_pipeline.ratelimit import Pacer, parse_duration
from test_groq import BLOCKS, MODEL, groq_settings, response


class Clock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s

    def monotonic(self):
        return self.now


def make(engine, settings, handler, clock, **overrides):
    selected = replace(groq_settings(settings), **overrides)
    rid = engine.enqueue(llm=True)
    log = RunLog(engine.store, rid, [selected.api_key])
    model = Groq(
        selected,
        engine.store,
        rid,
        log,
        httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    return rid, model, log


def events(settings, rid, log, name):
    log.close()
    lines = (settings.data_dir / "logs" / rid / "events.jsonl").read_text().splitlines()
    return [e for e in map(json.loads, lines) if e["event"] == name]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("7.66s", 7.66),
        ("1m2.5s", 62.5),
        ("450ms", 0.45),
        ("3", 3.0),
        ("1.5", 1.5),
        ("junk", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_duration(text, expected):
    got = parse_duration(text)
    assert got == pytest.approx(expected) if expected is not None else got is None


def test_429_then_200_retries_and_settles_only_success(engine, settings, target):
    clock = Clock()
    seen = []

    def handle(request):
        seen.append(Decimal(engine.store.one(runs, id=rid)["reserved"]))
        if len(seen) == 1:
            return httpx.Response(429, headers={"retry-after": "2.5"})
        return httpx.Response(200, json=response())

    rid, model, log = make(engine, settings, handle, clock)
    claims = model.call(BLOCKS, target, MODEL)
    assert claims and len(seen) == 2
    assert clock.sleeps == [2.5]
    # Each attempt holds a fresh reservation of equal size (released in between).
    assert seen[0] == seen[1] > 0
    row = engine.store.one(runs, id=rid)
    assert Decimal(row["reserved"]) == 0
    assert Decimal(row["spent"]) == Decimal(".0000675")
    ev = events(settings, rid, log, "model.rate_limited")
    assert len(ev) == 1 and ev[0]["level"] == "WARNING"
    assert ev[0]["attempt"] == 1 and ev[0]["wait_seconds"] == 2.5
    assert ev[0]["provider"] == "groq" and ev[0]["model"] == MODEL
    assert "synthetic-groq-secret" not in json.dumps(ev)


def test_groq_reset_header_and_backoff_and_cap(engine, settings, target):
    clock = Clock()
    answers = iter(
        [
            {"x-ratelimit-reset-tokens": "1m2.5s"},
            {"x-ratelimit-reset-requests": "450ms"},
            {},
            {"retry-after": "500"},
        ]
    )

    def handle(request):
        try:
            return httpx.Response(429, headers=next(answers))
        except StopIteration:
            return httpx.Response(200, json=response())

    rid, model, log = make(engine, settings, handle, clock)
    model.call(BLOCKS, target, MODEL)
    # 62.5 capped to 60; 0.45; default 5*2**2; retry-after capped to 60.
    assert clock.sleeps == [60, 0.45, 20, 60]


def test_retries_exhausted_raises_rate_limit_and_pauses(settings, fetch_client):
    calls = []

    def handle(request):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "1"})

    sleeps = []
    e = Engine(
        replace(groq_settings(settings), rate_limit_retries=2),
        fetch_client=fetch_client,
        model_client=httpx.Client(transport=httpx.MockTransport(handle)),
        sleep=sleeps.append,
    )
    rid = e.enqueue(llm=True)
    report = e.work(rid)
    assert report["status"] == "paused" and len(calls) == 3
    assert sleeps.count(1.0) == 2
    assert any(
        r["code"] == "MODEL_RATE_LIMIT" for r in e.store.rows(errors, run_id=rid)
    )


def test_retries_disabled_fails_immediately(engine, settings, target):
    clock = Clock()
    rid, model, log = make(
        engine,
        settings,
        lambda _: httpx.Response(429),
        clock,
        rate_limit_retries=0,
    )
    with pytest.raises(PipelineError) as e:
        model.call(BLOCKS, target, MODEL)
    assert e.value.code == "MODEL_RATE_LIMIT" and clock.sleeps == []


def ok(_):
    return httpx.Response(200, json=response())  # 300 tokens per call


def test_pacing_sleeps_when_request_window_full(engine, settings, target):
    clock = Clock()
    rid, model, log = make(engine, settings, ok, clock, rpm_limit=2, tpm_limit=0)
    # Distinct fingerprints avoid the cache: vary the model request via blocks.
    for n in range(3):
        blocks = [{**BLOCKS[0], "text": f"Computer Science {n}"}]
        model.call(blocks, target, MODEL)
    assert len(clock.sleeps) == 1 and clock.sleeps[0] == pytest.approx(60, abs=0.1)
    assert events(settings, rid, log, "model.paced")


def test_pacing_uses_actual_token_usage(engine, settings, target):
    clock = Clock()
    rid, model, log = make(engine, settings, ok, clock, tpm_limit=3200, rpm_limit=0)
    for n in range(2):
        model.call([{**BLOCKS[0], "text": f"Alpha {n}"}], target, MODEL)
    # Estimate is ~1.5K+; the 300 actual tokens from call 1 push call 2 over the limit.
    assert len(clock.sleeps) == 1


def test_no_pacing_under_limit_or_when_disabled(engine, settings, target):
    for limits in (
        {"tpm_limit": 10**6, "rpm_limit": 100},
        {"tpm_limit": 0, "rpm_limit": 0},
    ):
        clock = Clock()
        rid, model, log = make(engine, settings, ok, clock, **limits)
        for n in range(4):
            model.call([{**BLOCKS[0], "text": f"{limits} {n}"}], target, MODEL)
        assert clock.sleeps == []
        log.close()


def test_oversized_estimate_proceeds_with_warning(engine, settings, target):
    clock = Clock()
    rid, model, log = make(engine, settings, ok, clock, tpm_limit=100, rpm_limit=0)
    assert model.call(BLOCKS, target, MODEL)
    assert clock.sleeps == []
    assert events(settings, rid, log, "model.pacing_oversized")


def test_window_expires(engine, settings, target):
    clock = Clock()
    pacer = Pacer(0, 1, clock.sleep, clock.monotonic)
    pacer.started()
    clock.now += 61
    assert pacer.acquire(10) == 0 and clock.sleeps == []


def test_openrouter_defaults_do_not_pace(engine, settings, target):
    clock = Clock()
    model = OpenRouter(
        replace(settings, api_key="k"),
        engine.store,
        engine.enqueue(llm=True),
        None,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert not model.pacer.enabled


def test_settings_defaults_and_validation(monkeypatch, tmp_path):
    for k in (
        "LLM_PROVIDER",
        "GROQ_TPM_LIMIT",
        "GROQ_RPM_LIMIT",
        "OPENROUTER_TPM_LIMIT",
        "LLM_RATE_LIMIT_RETRIES",
        "LLM_RATE_LIMIT_MAX_WAIT",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("kb_pipeline.config.dotenv_values", lambda *_: {})
    s = Settings.load()
    assert (s.tpm_limit, s.rpm_limit, s.rate_limit_retries) == (0, 0, 4)
    assert s.rate_limit_max_wait == 60
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    s = Settings.load()
    assert (s.tpm_limit, s.rpm_limit) == (8000, 30)
    monkeypatch.setenv("GROQ_TPM_LIMIT", "0")
    assert Settings.load().tpm_limit == 0
    monkeypatch.setenv("LLM_RATE_LIMIT_RETRIES", "99")
    with pytest.raises(ValueError, match="rate-limit"):
        Settings.load()
    assert "tpm_limit" not in s.model_config()
