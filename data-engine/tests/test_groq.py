from dataclasses import replace
from decimal import Decimal
import json
import httpx
import pytest
from kb_pipeline.config import Settings
from kb_pipeline.contracts import PipelineError
from kb_pipeline.db import runs, jobs, claims, releases
from kb_pipeline.engine import Engine
from kb_pipeline.groq import Groq
from kb_pipeline.logging import RunLog
from kb_pipeline.openrouter import OpenRouter

MODEL = "openai/gpt-oss-20b"
BLOCKS = [
    {
        "id": "b0000",
        "text": "Computer Science",
        "heading": "Computer Science",
        "location": {"tag": "h1"},
    }
]


def groq_settings(settings):
    return replace(
        settings,
        provider="groq",
        api_key="synthetic-groq-secret",
        model=MODEL,
        fallback_model="",
        input_rate=Decimal(".075"),
        output_rate=Decimal(".30"),
        output_tokens=4096,
    )


def response():
    return {
        "id": "synthetic-groq-request",
        "model": MODEL,
        "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300},
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps(
                        {
                            "claims": [
                                {
                                    "field": "programme_title",
                                    "value": "Computer Science",
                                    "quote": "Computer Science",
                                    "location_id": "b0000",
                                    "applicant_group": "not established",
                                    "intake": None,
                                    "conditions": None,
                                    "method": "llm",
                                }
                            ]
                        }
                    )
                },
            }
        ],
    }


def client(engine, settings, handler):
    selected = groq_settings(settings)
    rid = engine.enqueue(llm=True)
    log = RunLog(engine.store, rid, [selected.api_key])
    model = Groq(
        selected,
        engine.store,
        rid,
        log,
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    return rid, model, log


def test_groq_wire_contract_token_estimate_and_offline_cache(engine, settings, target):
    calls = []

    def handle(request):
        calls.append(request)
        assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer synthetic-groq-secret"
        body = json.loads(request.content)
        assert "provider" not in body and "max_tokens" not in body
        assert body["max_completion_tokens"] == 4096
        assert body["reasoning_effort"] == "low" and body["include_reasoning"] is False
        schema = body["response_format"]["json_schema"]
        assert schema["strict"] is True
        assert set(schema["schema"]["$defs"]["Claim"]["required"]) == set(
            schema["schema"]["$defs"]["Claim"]["properties"]
        )
        return httpx.Response(200, json=response())

    rid, model, log = client(engine, settings, handle)
    first = model.call(BLOCKS, target, MODEL)
    assert first[0].method == "groq:" + MODEL
    assert model.call(BLOCKS, target, MODEL, offline=True) == first
    assert len(calls) == 1
    row = engine.store.one(runs, id=rid)
    assert Decimal(row["spent"]) == Decimal(".0000675")
    assert Decimal(row["reserved"]) == 0
    log.close()
    events = (settings.data_dir / "logs" / rid / "events.jsonl").read_text()
    assert '"cost_basis": "token_rate_estimate"' in events
    for path in (settings.data_dir / "model_inputs").glob("*.json"):
        assert "synthetic-groq-secret" not in path.read_text()


def test_provider_cache_cannot_be_reused_as_other_provider(engine, settings, target):
    rid, model, log = client(
        engine, settings, lambda _: httpx.Response(200, json=response())
    )
    model.call(BLOCKS, target, MODEL)
    router = OpenRouter(
        replace(model.settings, provider="openrouter"),
        engine.store,
        rid,
        log,
        httpx.Client(
            transport=httpx.MockTransport(
                lambda _: pytest.fail("Offline provider call")
            )
        ),
    )
    with pytest.raises(PipelineError, match="network is disabled"):
        router.call(BLOCKS, target, MODEL, offline=True)
    changed = Groq(
        replace(model.settings, input_rate=Decimal(".1")), engine.store, rid, log
    )
    with pytest.raises(PipelineError, match="network is disabled"):
        changed.call(BLOCKS, target, MODEL, offline=True)
    changed.close()
    log.close()


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {},
        [],
        {"prompt_tokens": True, "completion_tokens": 2},
        {"prompt_tokens": 1, "completion_tokens": -1},
        {"prompt_tokens": "100", "completion_tokens": 2},
    ],
)
def test_unusable_groq_usage_retains_reservation(engine, settings, target, usage):
    def handle(_):
        data = response()
        data["usage"] = usage
        return httpx.Response(200, json=data)

    rid, model, log = client(engine, settings, handle)
    with pytest.raises(PipelineError) as exc:
        model.call(BLOCKS, target, MODEL)
    assert exc.value.code == "MODEL_BILLING_UNCERTAIN"
    row = engine.store.one(runs, id=rid)
    assert Decimal(row["reserved"]) > 0 and Decimal(row["spent"]) == 0
    log.close()


@pytest.mark.parametrize(
    "failure,expected",
    [
        ("timeout", "MODEL_TRANSPORT"),
        ("429", "MODEL_RATE_LIMIT"),
        ("400", "MODEL_BILLING_UNCERTAIN"),
        ("usage", "MODEL_BILLING_UNCERTAIN"),
    ],
)
def test_groq_engine_pauses_without_other_provider_fallback(
    settings, fetch_client, failure, expected
):
    calls = []

    def handle(request):
        calls.append(str(request.url))
        if failure == "timeout":
            raise httpx.ReadTimeout("Synthetic timeout")
        if failure == "429":
            return httpx.Response(429, headers={"retry-after": "60"})
        if failure == "400":
            return httpx.Response(400, json={"error": {"code": "json_validate_failed"}})
        return httpx.Response(200, json={"usage": {}})

    e = Engine(
        groq_settings(settings),
        fetch_client=fetch_client,
        model_client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    rid = e.enqueue(llm=True)
    report = e.work(rid)
    assert report["status"] == "paused" and len(calls) == 1
    assert e.store.rows(jobs, run_id=rid)[0]["error_id"]
    assert report["known_cost_usd"] is None
    assert Decimal(report["reserved_or_uncertain_usd"]) > 0
    assert not e.store.rows(releases)
    from kb_pipeline.db import errors

    assert any(r["code"] == expected for r in e.store.rows(errors, run_id=rid))


def test_invalid_groq_json_is_costed_but_not_cached(engine, settings, target):
    def handle(_):
        data = response()
        data["choices"][0]["message"]["content"] = "broken JSON"
        return httpx.Response(200, json=data)

    rid, model, log = client(engine, settings, handle)
    with pytest.raises(PipelineError) as exc:
        model.call(BLOCKS, target, MODEL)
    assert exc.value.code == "MODEL_SCHEMA_INVALID"
    assert Decimal(engine.store.one(runs, id=rid)["spent"]) > 0
    assert not list((settings.data_dir / "model_cache").glob("*.json"))
    log.close()


def test_groq_call_cannot_exceed_available_budget(engine, settings, target):
    rid, model, log = client(
        engine, settings, lambda _: pytest.fail("Budget must be checked before sending")
    )
    engine.store.update(runs, rid, budget="0.00000001")
    with pytest.raises(PipelineError) as exc:
        model.call(BLOCKS, target, MODEL)
    assert exc.value.code == "BUDGET_EXHAUSTED"
    assert Decimal(engine.store.one(runs, id=rid)["spent"]) == 0
    log.close()


def test_groq_full_pipeline_and_frozen_provider_config(settings, fetch_client):
    e = Engine(
        groq_settings(settings),
        fetch_client=fetch_client,
        model_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json=response())
            )
        ),
    )
    rid = e.enqueue(llm=True)
    report = e.work(rid)
    assert report["status"] == "awaiting_review"
    assert (
        report["cost_basis"] == "token_rate_estimate"
        and report["known_cost_usd"] is None
    )
    assert Decimal(report["estimated_cost_usd"]) == Decimal(".0000675")
    rows = e.store.rows(claims, run_id=rid)
    assert any(json.loads(r["body"])["method"] == "groq:" + MODEL for r in rows)
    assert all(r["review"] == "pending" for r in rows) and not e.store.rows(releases)
    queued = e.enqueue(llm=True)
    e.settings = replace(e.settings, provider="openrouter")
    with pytest.raises(PipelineError) as exc:
        e.work(queued)
    assert exc.value.code == "RUN_CONFIG_CHANGED"


def test_settings_select_only_requested_provider_key(tmp_path, monkeypatch):
    import kb_pipeline.config as config

    monkeypatch.setattr(config, "PROJECT", tmp_path)
    (tmp_path / ".env").write_text(
        "LLM_PROVIDER=groq\nGROQ_API_KEY=synthetic-groq-only\nOPENROUTER_API_KEY=synthetic-router-only\n"
    )
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    for key in ("GROQ_API_KEY", "OPENROUTER_API_KEY", "GROQ_MODEL"):
        monkeypatch.delenv(key, raising=False)
    selected = Settings.load()
    assert (
        selected.provider == "groq"
        and selected.model == MODEL
        and selected.fallback_model == ""
    )
    assert selected.api_key == "synthetic-groq-only"
    assert "synthetic-groq-only" not in repr(selected) + json.dumps(
        selected.model_config()
    )
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    assert Settings.load().api_key == "synthetic-router-only"
    monkeypatch.setenv("LLM_PROVIDER", "invalid-provider")
    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        Settings.load()
