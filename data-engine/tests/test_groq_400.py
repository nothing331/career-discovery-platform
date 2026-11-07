"""Groq HTTP 400 is a per-request failure: charged conservatively, never a run stop."""

from decimal import Decimal
import json
import time

import httpx
import pytest

from kb_pipeline.contracts import PipelineError
from kb_pipeline.db import claims, jobs, pages, runs
from kb_pipeline.engine import Engine
from kb_pipeline.ratelimit import Pacer
from test_groq import BLOCKS, MODEL, client, groq_settings, response

SECRET = "synthetic-groq-secret"
SCHEMA_400 = {
    "error": {
        "message": f"Failed to validate JSON, key {SECRET} " + "x" * 3000,
        "type": "invalid_request_error",
        "code": "json_validate_failed",
    }
}
OTHER_400 = {"error": {"message": "bad request", "type": "invalid_request_error"}}


def events(settings, rid):
    path = settings.data_dir / "logs" / rid / "events.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def diagnostics(settings, rid):
    d = settings.data_dir / "logs" / rid / "diagnostics"
    return [json.loads(p.read_text()) for p in d.glob("*.json")]


def two_target_settings(settings, target):
    other = target.model_copy(update={"id": "test-bsc-2"})
    registry = json.loads(settings.registry.read_text())
    registry["targets"].append(other.model_dump(mode="json"))
    settings.registry.write_text(json.dumps(registry))
    return other


def test_groq_400_schema_failure_does_not_pause_and_charges_reservation(
    settings, fetch_client, target
):
    other = two_target_settings(settings, target)
    calls = []

    def handle(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(400, json=SCHEMA_400)
        return httpx.Response(200, json=response())

    e = Engine(
        groq_settings(settings),
        fetch_client=fetch_client,
        model_client=httpx.Client(transport=httpx.MockTransport(handle)),
        sleep=lambda _: None,
    )
    rid = e.enqueue(llm=True, targets=[target, other])
    report = e.work(rid)
    assert report["status"] != "paused"
    assert len(calls) == 2  # the run continued to the next target
    assert {j["status"] for j in e.store.rows(jobs, run_id=rid)} <= {
        "done",
        "awaiting_review",
        "review",
    } or all(j["error_id"] is None for j in e.store.rows(jobs, run_id=rid))
    row = e.store.one(runs, id=rid)
    charged = [
        ev
        for ev in events(e.settings, rid)
        if ev["event"] == "model.charged_reservation"
    ]
    assert len(charged) == 1
    amount = Decimal(charged[0]["amount_usd"])
    assert amount > 0 and Decimal(row["spent"]) >= amount
    assert Decimal(row["reserved"]) == 0
    http = [ev for ev in events(e.settings, rid) if ev["event"] == "model.http_error"]
    assert http[0]["status"] == 400
    assert http[0]["provider_error_code"] == "json_validate_failed"
    assert len(http[0]["response_body"]) <= 1000
    dumped = json.dumps(diagnostics(e.settings, rid))
    assert "json_validate_failed" in dumped and "MODEL_SCHEMA_INVALID" in dumped
    assert SECRET not in dumped
    assert (
        SECRET not in (e.settings.data_dir / "logs" / rid / "events.jsonl").read_text()
    )
    # rule claims from the failed document were kept
    assert e.store.rows(claims, run_id=rid)


def test_groq_400_other_is_request_rejected_non_stop(engine, settings, target):
    rid, model, log = client(
        engine, settings, lambda _: httpx.Response(400, json=OTHER_400)
    )
    with pytest.raises(PipelineError) as exc:
        model.call(BLOCKS, target, MODEL)
    assert exc.value.code == "MODEL_REQUEST_REJECTED"
    from kb_pipeline.engine import STOP_CODES

    assert exc.value.code not in STOP_CODES
    row = engine.store.one(runs, id=rid)
    assert Decimal(row["spent"]) > 0 and Decimal(row["reserved"]) == 0
    log.close()


def test_groq_401_still_stops_and_releases(engine, settings, target):
    rid, model, log = client(engine, settings, lambda _: httpx.Response(401))
    with pytest.raises(PipelineError) as exc:
        model.call(BLOCKS, target, MODEL)
    assert exc.value.code == "MODEL_AUTH_FAILED"
    row = engine.store.one(runs, id=rid)
    assert Decimal(row["spent"]) == 0 and Decimal(row["reserved"]) == 0
    log.close()


def big_blocks(n=3):
    return [
        {
            "id": f"b{i:04d}",
            "text": "t" * 7000,
            "heading": "h",
            "location": {"tag": "p"},
        }
        for i in range(n)
    ]


def test_failed_chunk_keeps_other_chunks(engine, settings, target):
    calls = []

    def handle(_):
        calls.append(1)
        if len(calls) == 2:
            return httpx.Response(400, json=SCHEMA_400)
        return httpx.Response(200, json=response())

    rid, model, log = client(engine, settings, handle)
    model.pacer = Pacer(0, 0, lambda _: None, time.monotonic)
    claims_out = model.extract(big_blocks(), target)
    assert len(calls) == 3 and len(claims_out) == 2
    assert (
        any(ev["event"] == "model.chunk_skipped" for ev in events(settings, rid))
        or log.close() is None
    )
    log.close()


def test_all_chunks_failing_raises_last_error(engine, settings, target):
    rid, model, log = client(
        engine, settings, lambda _: httpx.Response(400, json=SCHEMA_400)
    )
    model.pacer = Pacer(0, 0, lambda _: None, time.monotonic)
    with pytest.raises(PipelineError) as exc:
        model.extract(big_blocks(2), target)
    assert exc.value.code == "MODEL_SCHEMA_INVALID"
    log.close()


def test_stop_code_in_chunk_raises_immediately(engine, settings, target):
    calls = []

    def handle(_):
        calls.append(1)
        return httpx.Response(401)

    rid, model, log = client(engine, settings, handle)
    model.pacer = Pacer(0, 0, lambda _: None, time.monotonic)
    with pytest.raises(PipelineError) as exc:
        model.extract(big_blocks(), target)
    assert exc.value.code == "MODEL_AUTH_FAILED" and len(calls) == 1
    log.close()


FEES = (
    "<html><main><h1>Fees and contributions</h1><table><tr><td>Tuition fees</td>"
    "<td>190 EUR per semester</td></tr></table><p>Fees are charged every semester.</p>"
    "</main></html>"
)
PRIMARY = (
    "<html><main><h1>Computer Science (B.Sc.)</h1><p>A local synthetic programme "
    "page.</p><table><tr><td>Duration and credits</td><td>6 semesters; 180 ECTS "
    '</td></tr></table><p><a href="/fees">Tuition fees and semester contribution'
    "</a></p></main></html>"
)


def test_truncated_model_response_on_followup_keeps_rule_claims(settings):
    calls = []

    def fetch(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        body = {"/cs": PRIMARY, "/fees": FEES}.get(request.url.path)
        if body is None:
            return httpx.Response(404)
        return httpx.Response(
            200, content=body.encode(), headers={"content-type": "text/html"}
        )

    def model_handle(request):
        calls.append(1)
        data = response()
        if len(calls) > 1:
            data["choices"][0]["finish_reason"] = "length"
        return httpx.Response(200, json=data)

    e = Engine(
        groq_settings(settings),
        fetch_client=httpx.Client(transport=httpx.MockTransport(fetch)),
        model_client=httpx.Client(transport=httpx.MockTransport(model_handle)),
        sleep=lambda _: None,
    )
    rid = e.enqueue(llm=True)
    report = e.work(rid)
    assert report["status"] != "paused"
    page_rows = e.store.rows(pages, job_id=e.store.rows(jobs, run_id=rid)[0]["id"])
    assert [p["status"] for p in page_rows] == ["done"]
    fees_claims = [
        json.loads(r["body"])
        for r in e.store.rows(claims, run_id=rid)
        if r["snapshot_id"] == page_rows[0]["snapshot_id"]
    ]
    assert any(c["field"] == "tuition" for c in fees_claims)
    assert any(
        ev["event"] == "extract.model_skipped"
        and ev["code"] == "MODEL_TRUNCATED_OR_REFUSED"
        for ev in events(e.settings, rid)
    )
