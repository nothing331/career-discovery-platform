from dataclasses import replace
from decimal import Decimal
import json
import httpx
import pytest
from kb_pipeline.openrouter import OpenRouter
from kb_pipeline.logging import RunLog
from kb_pipeline.db import runs
from kb_pipeline.contracts import PipelineError

BLOCKS = [
    {
        "id": "b0000",
        "text": "Computer Science",
        "heading": "Computer Science",
        "location": {"tag": "h1"},
    }
]


def response():
    return {
        "id": "synthetic-request",
        "model": "synthetic-model",
        "provider": "test",
        "usage": {"cost": 0.00001, "prompt_tokens": 100, "completion_tokens": 100},
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
                                    "method": "openrouter",
                                }
                            ]
                        }
                    )
                },
            }
        ],
    }


def client(engine, settings, handler):
    rid = engine.enqueue(llm=True)
    log = RunLog(engine.store, rid, ["synthetic-secret"])
    model = OpenRouter(
        replace(settings, api_key="synthetic-secret"),
        engine.store,
        rid,
        log,
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    return rid, model, log


def test_typed_call_caps_and_offline_cache(engine, settings, target):
    calls = []

    def handle(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body["provider"]["require_parameters"] is True
        assert body["provider"]["max_price"]["prompt"] == 0.2
        assert body["response_format"]["json_schema"]["strict"] is True
        return httpx.Response(200, json=response())

    rid, model, log = client(engine, settings, handle)
    first = model.call(BLOCKS, target, settings.model)
    second = model.call(BLOCKS, target, settings.model, offline=True)
    assert first == second and len(calls) == 1
    assert Decimal(engine.store.one(runs, id=rid)["reserved"]) == 0
    log.close()


def test_schema_failure_records_actual_cost(engine, settings, target):
    def handle(request):
        r = response()
        r["choices"][0]["message"]["content"] = "not JSON"
        return httpx.Response(200, json=r)

    rid, model, log = client(engine, settings, handle)
    with pytest.raises(PipelineError, match="Invalid typed"):
        model.call(BLOCKS, target, settings.model)
    assert Decimal(engine.store.one(runs, id=rid)["spent"]) == Decimal(".00001")
    assert not (settings.data_dir / "model_cache").exists()
    log.close()


def test_transport_retains_reservation(engine, settings, target):
    def handle(request):
        raise httpx.ReadTimeout("synthetic timeout")

    rid, model, log = client(engine, settings, handle)
    with pytest.raises(PipelineError, match="reservation retained"):
        model.call(BLOCKS, target, settings.model)
    assert Decimal(engine.store.one(runs, id=rid)["reserved"]) > 0
    log.close()


def test_offline_missing_cache_never_calls_provider(engine, settings, target):
    def deny(request):
        raise AssertionError("No network in offline replay")

    rid, model, log = client(engine, settings, deny)
    with pytest.raises(PipelineError, match="network is disabled"):
        model.call(BLOCKS, target, settings.model, offline=True)
    assert Decimal(engine.store.one(runs, id=rid)["reserved"]) == 0
    log.close()


def test_missing_billing_stops_and_retains_reservation(engine, settings, target):
    def handle(request):
        r = response()
        r["usage"] = {}
        return httpx.Response(200, json=r)

    rid, model, log = client(engine, settings, handle)
    with pytest.raises(PipelineError, match="usable cost"):
        model.call(BLOCKS, target, settings.model)
    assert Decimal(engine.store.one(runs, id=rid)["reserved"]) > 0
    log.close()


def test_changed_model_does_not_reuse_old_cache(engine, settings, target):
    rid, model, log = client(
        engine, settings, lambda request: httpx.Response(200, json=response())
    )
    model.call(BLOCKS, target, settings.model)
    with pytest.raises(PipelineError, match="network is disabled"):
        model.call(BLOCKS, target, "different/model", offline=True)
    log.close()
