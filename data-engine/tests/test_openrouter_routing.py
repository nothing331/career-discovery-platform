"""OpenRouter request routing: capped reasoning and a pinned upstream provider."""

from dataclasses import replace

import httpx
import pytest

from kb_pipeline.config import Settings
from kb_pipeline.groq import Groq
from kb_pipeline.logging import RunLog
from kb_pipeline.openrouter import OpenRouter
from test_groq import groq_settings

MODEL = "openai/gpt-oss-20b"


def build(engine, settings, cls=OpenRouter, **changes):
    selected = replace(settings, api_key="synthetic-secret", **changes)
    rid = engine.enqueue(llm=True)
    log = RunLog(engine.store, rid, [selected.api_key])
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    return cls(selected, engine.store, rid, log, client), log


def test_reasoning_is_capped_and_excluded_by_default(engine, settings, target):
    model, log = build(engine, settings)
    body = model.request([], target, MODEL)
    assert body["reasoning"] == {"effort": "low", "exclude": True}
    log.close()


def test_reasoning_can_be_disabled(engine, settings, target):
    model, log = build(engine, settings, reasoning_effort="none")
    assert model.request([], target, MODEL)["reasoning"] == {"enabled": False}
    log.close()


def test_provider_order_replaces_price_sort(engine, settings, target):
    model, log = build(engine, settings, provider_order=("Groq",))
    routing = model.request([], target, MODEL)["provider"]
    assert routing["order"] == ["Groq"]
    assert "sort" not in routing
    # The price caps and strict-parameter requirement still apply.
    assert routing["require_parameters"] is True
    assert routing["max_price"]["completion"] == float(settings.output_rate)
    log.close()


def test_no_provider_order_keeps_cheapest_routing(engine, settings, target):
    model, log = build(engine, settings)
    routing = model.request([], target, MODEL)["provider"]
    assert routing["sort"] == "price" and "order" not in routing
    log.close()


def test_groq_request_uses_its_own_reasoning_field(engine, settings, target):
    model, log = build(
        engine, groq_settings(settings), cls=Groq, reasoning_effort="medium"
    )
    body = model.request([], target, MODEL)
    assert "reasoning" not in body and "provider" not in body
    assert body["reasoning_effort"] == "medium"
    log.close()


def test_settings_load_reasoning_and_provider_order(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_PROVIDER_ORDER", " Groq , Cerebras ,")
    monkeypatch.setenv("OPENROUTER_REASONING_EFFORT", "Medium")
    s = Settings.load()
    assert s.provider_order == ("Groq", "Cerebras")
    assert s.reasoning_effort == "medium"
    # Both change model output, so they are frozen into the run config.
    assert s.model_config()["provider_order"] == ["Groq", "Cerebras"]
    assert s.model_config()["reasoning_effort"] == "medium"


def test_settings_reject_unknown_reasoning_effort(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_REASONING_EFFORT", "extreme")
    with pytest.raises(ValueError):
        Settings.load()
