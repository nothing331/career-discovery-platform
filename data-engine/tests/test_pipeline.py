from dataclasses import replace
from decimal import Decimal
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from kb_pipeline.engine import Engine
from kb_pipeline.db import jobs, claims, errors, runs, releases
from kb_pipeline.contracts import PipelineError
from kb_pipeline.knowledge import review, publish, catalogue
from kb_pipeline.api import create_app
from kb_pipeline.logging import RunLog, Redactor
from conftest import HTML


def test_collection_evidence_holds_and_review_gate(engine, settings):
    rid = engine.enqueue()
    report = engine.work(rid)
    assert report["documents"] == {"done": 1}
    rows = engine.store.rows(claims, run_id=rid)
    assert any(json.loads(r["body"])["field"] == "ects" for r in rows)
    assert any(r["validation"] == "MISSING_INTAKE_SCOPE" for r in rows)
    assert report["known_cost_usd"] == "0"
    assert catalogue(engine.store) == []
    with pytest.raises(PipelineError, match="Every candidate"):
        publish(engine.store, rid)
    for row in rows:
        if row["validation"] == "valid":
            review(
                engine.store,
                row["id"],
                "test reviewer",
                "approved",
                "Synthetic fixture verified",
            )
        else:
            with pytest.raises(PipelineError, match="Resolve evidence"):
                review(engine.store, row["id"], "test reviewer", "approved")
            review(
                engine.store,
                row["id"],
                "test reviewer",
                "rejected",
                "Scope missing in synthetic fixture",
            )
    release = publish(engine.store, rid)
    assert catalogue(engine.store)[0]["release_id"] == release
    client = TestClient(create_app(settings))
    assert len(client.get("/v1/programmes").json()["programmes"]) == 1
    assert client.get("/v1/programmes/test-bsc/evidence").status_code == 200
    assert client.get("/v1/programmes/missing").status_code == 404
    with pytest.raises(PipelineError):
        review(engine.store, rows[0]["id"], "other", "rejected", "History edit")


def test_bounded_retries_and_visible_failures(settings):
    calls = []

    def handle(request):
        calls.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(503, headers={"Retry-After": "1"})

    e = Engine(
        settings,
        fetch_client=httpx.Client(transport=httpx.MockTransport(handle)),
        sleep=lambda _: None,
    )
    rid = e.enqueue()
    report = e.work(rid)
    assert calls.count("/cs") == 3
    assert report["documents"] == {"failed": 1}
    assert len(e.store.rows(errors, run_id=rid)) >= 3
    assert not e.store.rows(claims, run_id=rid)
    assert (settings.data_dir / "logs" / rid / "run_summary.json").exists()


def test_robots_disallowed_is_not_bypassed(settings):
    calls = []

    def handle(request):
        calls.append(request.url.path)
        return httpx.Response(200, text="User-agent: *\nDisallow: /")

    e = Engine(
        settings, fetch_client=httpx.Client(transport=httpx.MockTransport(handle))
    )
    rid = e.enqueue()
    e.work(rid)
    assert calls == ["/robots.txt"]
    assert any(
        r["code"] == "ROBOTS_DISALLOWED" for r in e.store.rows(errors, run_id=rid)
    )


def test_replay_uses_snapshot_and_retains_original(engine, settings):
    rid = engine.enqueue()
    engine.work(rid)
    err = engine.store.rows(errors, run_id=rid)[0]

    def deny(request):
        raise AssertionError("Replay must not access the network")

    e = Engine(
        settings,
        store=engine.store,
        fetch_client=httpx.Client(transport=httpx.MockTransport(deny)),
    )
    replay = e.replay(err["id"])
    report = e.work(replay)
    assert report["parent_error_id"] == err["id"] and report["documents"] == {"done": 1}
    assert e.store.one(errors, id=err["id"])["status"] == "open"
    assert e.store.one(runs, id=rid)["status"] == "awaiting_review"


def test_restart_recovers_saved_stage_without_refetch(engine, settings, monkeypatch):
    rid = engine.enqueue()
    import kb_pipeline.engine as module

    original = module.parse
    monkeypatch.setattr(
        module, "parse", lambda *args: (_ for _ in ()).throw(KeyboardInterrupt())
    )
    with pytest.raises(KeyboardInterrupt):
        engine.work(rid)
    assert engine.store.one(runs, id=rid)["status"] == "interrupted"
    monkeypatch.setattr(module, "parse", original)

    def deny(request):
        raise AssertionError("Checkpointed snapshot must be reused")

    resumed = Engine(
        settings,
        store=engine.store,
        fetch_client=httpx.Client(transport=httpx.MockTransport(deny)),
    )
    assert resumed.work(rid)["documents"] == {"done": 1}


def test_logging_failure_stops_publication(engine, monkeypatch):
    def fail(*args, **kwargs):
        raise PipelineError("LOG_WRITE_FAILED", "Synthetic write failure")

    monkeypatch.setattr(RunLog, "emit", fail)
    rid = engine.enqueue()
    with pytest.raises(PipelineError):
        engine.work(rid)
    assert engine.store.one(runs, id=rid)["status"] == "failed"
    assert engine.store.rows(releases) == []


def test_redaction_in_tracebacks_and_jsonl(engine, settings):
    secret = "synthetic-provider-key-123456"
    rid = engine.enqueue()
    job = engine.store.rows(jobs, run_id=rid)[0]
    log = RunLog(engine.store, rid, [secret])
    try:
        raise ValueError(
            f"Authorization: Bearer {secret} https://user:password@example.com/path?token=private-token"
        )
    except ValueError as exc:
        log.failure(job["id"], "extract", exc, api_key=secret)
    log.close()
    for path in (settings.data_dir / "logs" / rid).rglob("*"):
        if path.is_file():
            text = path.read_text()
            assert (
                secret not in text
                and "private-token" not in text
                and "user:password" not in text
            )
            for line in text.splitlines() if path.suffix == ".jsonl" else [text]:
                json.loads(line)


def test_budget_reservations_are_bounded(engine):
    rid = engine.enqueue(budget=Decimal(".01"))
    engine.store.reserve(rid, Decimal(".006"))
    with pytest.raises(PipelineError):
        engine.store.reserve(rid, Decimal(".006"))
    engine.store.settle(rid, Decimal(".006"), Decimal(".002"))
    row = engine.store.one(runs, id=rid)
    assert Decimal(row["spent"]) == Decimal(".002") and Decimal(row["reserved"]) == 0


def test_cross_host_redirect_requires_review(settings):
    def handle(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(302, headers={"location": "https://127.0.0.1/private"})

    e = Engine(
        settings, fetch_client=httpx.Client(transport=httpx.MockTransport(handle))
    )
    rid = e.enqueue()
    e.work(rid)
    assert any(
        r["code"] == "REDIRECT_SOURCE_REVIEW" for r in e.store.rows(errors, run_id=rid)
    )


def test_layout_table_is_not_a_giant_deadline_claim(target):
    from kb_pipeline.acquire import parse
    from kb_pipeline.extract import rule_claims

    html = (
        "<main><table><tr><td><h1>Computer Science M.Sc.</h1><p>"
        + ("Example admissions background. " * 180)
        + "</p><table><tr><td>Duration</td><td>4 semesters</td></tr><tr><td>Application deadline</td><td>15 July</td></tr></table></td></tr></table></main>"
    ).encode()
    document = parse(html, "text/html", str(target.url))
    rows = rule_claims(document, target)
    assert any(c.field == "duration_semesters" and c.value == "4" for c in rows)
    assert any(c.field == "programme_title" for c in rows)
    assert all(len(c.value) <= 3000 for c in rows)


def test_error_resolution_requires_successful_linked_replay(engine, monkeypatch):
    import kb_pipeline.engine as module
    from kb_pipeline.knowledge import resolve_error

    original = module.parse

    def fail(*args):
        raise PipelineError("SYNTHETIC_PARSE_BUG", "Synthetic regression case")

    monkeypatch.setattr(module, "parse", fail)
    rid = engine.enqueue()
    engine.work(rid)
    err = engine.store.rows(errors, run_id=rid)[0]
    monkeypatch.setattr(module, "parse", original)
    replay = engine.replay(err["id"])
    with pytest.raises(PipelineError):
        resolve_error(engine.store, err["id"], replay, "developer", "Not run yet")
    engine.work(replay)
    resolve_error(
        engine.store, err["id"], replay, "developer", "Replay and regression verified"
    )
    assert engine.store.one(errors, id=err["id"])["status"] == "resolved"
    assert catalogue(engine.store) == []


def test_cli_redacts_secret_even_if_settings_are_invalid(tmp_path):
    import os
    import subprocess
    import sys

    secret = "synthetic-secret-invalid-setting"
    env = {**os.environ, "OPENROUTER_API_KEY": secret, "ENGINE_DELAY_SECONDS": secret}
    result = subprocess.run(
        [sys.executable, "-m", "kb_pipeline", "init"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert secret not in result.stdout + result.stderr
    assert "[REDACTED]" in result.stderr


def test_same_host_redirect_checks_robots_before_request(settings):
    calls = []

    def handle(request):
        calls.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private")
        return httpx.Response(302, headers={"location": "/private"})

    e = Engine(
        settings, fetch_client=httpx.Client(transport=httpx.MockTransport(handle))
    )
    rid = e.enqueue()
    e.work(rid)
    assert "/private" not in calls
    assert any(
        r["code"] == "ROBOTS_DISALLOWED" for r in e.store.rows(errors, run_id=rid)
    )


def test_long_retry_after_holds_instead_of_retrying_too_soon(settings):
    calls = []

    def handle(request):
        calls.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(429, headers={"retry-after": "3600"})

    e = Engine(
        settings,
        fetch_client=httpx.Client(transport=httpx.MockTransport(handle)),
        sleep=lambda _: None,
    )
    rid = e.enqueue()
    e.work(rid)
    assert calls.count("/cs") == 1
    assert any(
        r["code"] == "RETRY_AFTER_REVIEW" for r in e.store.rows(errors, run_id=rid)
    )
