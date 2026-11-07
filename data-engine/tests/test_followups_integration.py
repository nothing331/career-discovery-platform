"""Depth-1 follow-up crawl, claim dedupe, supersession, structured facts and migration 002."""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import json
import sqlite3

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from kb_pipeline.api import create_app
from kb_pipeline.contracts import PipelineError, Target
from kb_pipeline.db import (
    claims,
    errors,
    jobs,
    kb_structured,
    pages,
    runs,
    structured,
)
from kb_pipeline.engine import Engine
from kb_pipeline.knowledge import catalogue, publish, review

HOST = "university.example"
ADMISSIONS = (
    "<h1>Admission to the University</h1><p>Applicants must provide an English "
    "language certificate: IELTS 6.5 or TOEFL iBT 90 at the time of application.</p>"
)
FEES = (
    "<h1>Fees and contributions</h1><table><tr><td>Tuition fees</td>"
    "<td>190 EUR per semester</td></tr></table><p>Fees are charged every semester.</p>"
)


def page(title, body, links=()):
    anchors = "".join(f'<p><a href="{u}">{t}</a></p>' for u, t in links)
    return (
        f"<html><main><h1>{title}</h1><p>A local synthetic programme page for "
        f"integration tests only.</p><table><tr><td>Duration and credits</td>"
        f"<td>6 semesters; 180 ECTS credits</td></tr></table>{body}{anchors}</main></html>"
    ).encode()


LINKS = (
    ("/admissions", "Admission requirements"),
    ("/fees", "Tuition fees and semester contribution"),
    ("https://other.example/admission", "Admission elsewhere"),
    ("/missing-apply", "How to apply"),
)


def site(extra=None, calls=None):
    """Fake university: path -> html bytes, or an int HTTP status."""
    calls = calls if calls is not None else []
    content = {
        "/cs": page("Computer Science (B.Sc.)", "", LINKS),
        "/ms": page("Computer Science (M.Sc.)", "", LINKS),
        "/admissions": ADMISSIONS.encode(),
        "/fees": FEES.encode(),
        "/missing-apply": 404,
        **(extra or {}),
    }

    def handle(request):
        calls.append((request.url.host, request.url.path))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        item = content.get(request.url.path)
        if isinstance(item, int):
            return httpx.Response(item)
        if item is None:
            return httpx.Response(404)
        return httpx.Response(200, content=item, headers={"content-type": "text/html"})

    return httpx.Client(transport=httpx.MockTransport(handle)), calls


def make(settings, extra=None, **overrides):
    client, calls = site(extra)
    return (
        Engine(
            replace(settings, **overrides), fetch_client=client, sleep=lambda _: None
        ),
        calls,
    )


def target(tid="test-bsc", path="cs", level="bachelor"):
    return Target(
        id=tid,
        institution="Synthetic University",
        programme="Computer Science " + level,
        level=level,
        url=f"https://{HOST}/{path}",
        allowed_hosts=[HOST],
    )


def deny_client():
    return httpx.Client(
        transport=httpx.MockTransport(
            lambda r: pytest.fail("network used: " + str(r.url))
        )
    )


def page_rows(e, rid):
    return {
        urlpath(p["url"]): p
        for j in e.store.rows(jobs, run_id=rid)
        for p in e.store.rows(pages, job_id=j["id"])
    }


def urlpath(url):
    return "/" + url.split("/", 3)[3]


def test_followups_fetched_and_claims_use_their_own_snapshot(settings):
    e, calls = make(settings)
    rid = e.enqueue(targets=[target()])
    report = e.work(rid)
    assert report["documents"] == {"done": 1}
    rows = page_rows(e, rid)
    assert {k: v["status"] for k, v in rows.items()} == {
        "/admissions": "done",
        "/fees": "done",
        "/missing-apply": "failed",
    }
    assert rows["/missing-apply"]["error_code"] == "HTTP_404"
    assert json.loads(rows["/fees"]["roles"]) == ["fees"]
    assert report["followup_pages"] == {"done": 2, "failed": 1}
    # cross-host links are never selected or requested
    assert all(host == HOST for host, _ in calls)
    primary = e.store.rows(jobs, run_id=rid)[0]["snapshot_id"]
    by_snapshot = {}
    for r in e.store.rows(claims, run_id=rid):
        by_snapshot.setdefault(r["snapshot_id"], []).append(json.loads(r["body"]))
    fees_snapshot = rows["/fees"]["snapshot_id"]
    adm_snapshot = rows["/admissions"]["snapshot_id"]
    assert {primary, fees_snapshot, adm_snapshot} <= set(by_snapshot)
    assert any(b["field"] == "tuition" for b in by_snapshot[fees_snapshot])
    assert any(b["field"] == "requirement" for b in by_snapshot[adm_snapshot])
    # location ids are validated against the claim's own page, so all rule claims are sound
    assert not any(
        r["validation"] == "EVIDENCE_NOT_FOUND"
        for r in e.store.rows(claims, run_id=rid)
    )
    # the failing page is auditable but did not fail the job
    assert any(
        er["stage"] == "followup" and er["code"] == "HTTP_404"
        for er in e.store.rows(errors, run_id=rid)
    )


def test_programme_title_only_from_primary_page(settings):
    e, _ = make(settings)
    rid = e.enqueue(targets=[target()])
    e.work(rid)
    primary = e.store.rows(jobs, run_id=rid)[0]["snapshot_id"]
    titles = [
        r
        for r in e.store.rows(claims, run_id=rid)
        if json.loads(r["body"])["field"] == "programme_title"
    ]
    assert len(titles) == 1 and titles[0]["snapshot_id"] == primary


def test_shared_followup_page_fetched_once_per_run(settings):
    e, calls = make(settings)
    rid = e.enqueue(targets=[target(), target("test-msc", "ms", "master")])
    report = e.work(rid)
    assert report["documents"] == {"done": 2}
    assert calls.count((HOST, "/admissions")) == 1
    assert calls.count((HOST, "/fees")) == 1
    assert calls.count((HOST, "/missing-apply")) == 1  # failures are shared too
    snaps = set()
    for j in e.store.rows(jobs, run_id=rid):
        row = [
            p for p in e.store.rows(pages, job_id=j["id"]) if p["url"].endswith("/fees")
        ][0]
        snaps.add(row["snapshot_id"])
    assert len(snaps) == 1
    assert {
        r["entity_id"]
        for r in e.store.rows(claims, run_id=rid)
        if r["snapshot_id"] in snaps
    } == {
        "test-bsc",
        "test-msc",
    }


def test_followup_limit_zero_and_target_opt_out(settings):
    e, calls = make(settings, followup_limit=0)
    rid = e.enqueue(targets=[target()])
    e.work(rid)
    assert [p for _, p in calls] == ["/robots.txt", "/cs"]
    assert not e.store.rows(pages)
    e2, calls2 = make(settings)
    opted_out = target().model_copy(update={"follow_links": False})
    e2.work(e2.enqueue(targets=[opted_out]))
    assert (HOST, "/admissions") not in calls2


def test_offline_reuses_saved_followups_or_skips_without_network(settings):
    e, _ = make(settings)
    first = e.enqueue(targets=[target()])
    e.work(first)
    snapshot_id = e.store.rows(jobs, run_id=first)[0]["snapshot_id"]
    offline = Engine(settings, store=e.store, fetch_client=deny_client())
    rid = offline.enqueue(targets=[target()], snapshot_id=snapshot_id, offline=True)
    report = offline.work(rid)
    rows = page_rows(offline, rid)
    assert rows["/fees"]["status"] == "done"
    assert rows["/fees"]["snapshot_id"] == page_rows(e, first)["/fees"]["snapshot_id"]
    assert rows["/missing-apply"]["status"] == "skipped"
    assert report["documents"] == {"done": 1}
    # a store holding only the primary snapshot: every follow-up is skipped
    e0, _ = make(
        replace(settings, data_dir=settings.data_dir.parent / "d0"), followup_limit=0
    )
    r0 = e0.enqueue(targets=[target()])
    e0.work(r0)
    sid = e0.store.rows(jobs, run_id=r0)[0]["snapshot_id"]
    o2 = Engine(
        replace(e0.settings, followup_limit=6),
        store=e0.store,
        fetch_client=deny_client(),
    )
    r2 = o2.enqueue(targets=[target()], snapshot_id=sid, offline=True)
    assert o2.work(r2)["followup_pages"] == {"skipped": 3}
    # a snapshot-pinned (replay/pilot-style) run is also offline for follow-ups
    r3 = o2.enqueue(targets=[target()], snapshot_id=sid)
    assert o2.work(r3)["followup_pages"] == {"skipped": 3}


def test_stop_codes_in_followups_still_stop_the_run(settings, monkeypatch):
    e, _ = make(settings)
    import kb_pipeline.engine as module

    real = module.Engine._candidates

    def boom(self, job, tgt, document, config, model, log, *, primary=True):
        if not primary:
            raise PipelineError("BUDGET_EXHAUSTED", "synthetic")
        return real(self, job, tgt, document, config, model, log, primary=primary)

    monkeypatch.setattr(module.Engine, "_candidates", boom)
    rid = e.enqueue(targets=[target()])
    assert e.work(rid)["status"] == "paused"
    assert e.store.rows(jobs, run_id=rid)[0]["status"] == "failed"


def test_followup_parse_error_is_recorded_not_fatal(settings):
    e, _ = make(settings, extra={"/fees": b"<html><main>x</main></html>"})
    rid = e.enqueue(targets=[target()])
    report = e.work(rid)
    assert report["documents"] == {"done": 1}
    row = page_rows(e, rid)["/fees"]
    assert row["status"] == "failed" and row["error_code"] == "EMPTY_PARSED_TEXT"
    assert not [
        r
        for r in e.store.rows(claims, run_id=rid)
        if r["snapshot_id"] == row["snapshot_id"]
    ]


def test_config_records_versions_and_limit_change_is_detected(settings):
    e, _ = make(settings)
    rid = e.enqueue(targets=[target()])
    config = json.loads(e.store.one(runs, id=rid)["config"])
    assert config["link_selector"] == "roles-v2" and config["normalizer"] == "regex-v3"
    assert config["followup_limit"] == 6
    other, _ = make(settings, followup_limit=2)
    other.store = e.store
    with pytest.raises(PipelineError) as exc:
        other.work(rid)
    assert exc.value.code == "RUN_CONFIG_CHANGED"


def test_no_candidates_judged_across_all_pages(settings):
    bare = (
        "<html><main><h2>Welcome</h2><p>"
        + "Some general information about the department and the city. " * 3
        + '</p><p><a href="/admissions">Admission requirements</a></p></main></html>'
    ).encode()
    # the primary page alone yields nothing, the follow-up page rescues the job
    e, _ = make(settings, extra={"/cs": bare})
    rid = e.enqueue(targets=[target()])
    assert e.work(rid)["documents"] == {"done": 1}
    assert {
        json.loads(r["body"])["field"] for r in e.store.rows(claims, run_id=rid)
    } == {"requirement"}
    # nothing anywhere: NO_CANDIDATES, and a follow-up h1 never counts as a title
    empty = (
        b"<html><main><h1>Hello</h1><p>"
        + b"Welcome to our department and city. " * 4
        + b"</p></main></html>"
    )
    e2, _ = make(
        replace(settings, data_dir=settings.data_dir.parent / "d2"),
        extra={"/cs": bare, "/admissions": empty},
    )
    rid2 = e2.enqueue(targets=[target()])
    assert e2.work(rid2)["documents"] == {"failed": 1}
    assert any(
        er["code"] == "NO_CANDIDATES" for er in e2.store.rows(errors, run_id=rid2)
    )


def test_dedupe_merges_methods_instead_of_second_row(settings):
    selected = replace(
        settings,
        followup_limit=0,
        provider="groq",
        model="openai/gpt-oss-20b",
        fallback_model="",
        api_key="synthetic-key",
        input_rate=Decimal(".075"),
        output_rate=Decimal(".30"),
    )
    claim = {
        "field": "programme_title",
        "value": "Computer Science (B.Sc.)",
        "quote": "Computer Science (B.Sc.)",
        "location_id": "b0000",
        "applicant_group": "general (no specific applicant group stated)",
        "intake": None,
        "conditions": None,
        "method": "llm",
    }

    def model(request):
        return httpx.Response(
            200,
            json={
                "id": "synthetic",
                "model": "openai/gpt-oss-20b",
                "usage": {"prompt_tokens": 10, "completion_tokens": 10},
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps({"claims": [claim]})},
                    }
                ],
            },
        )

    client, _ = site()
    e = Engine(
        selected,
        fetch_client=client,
        model_client=httpx.Client(transport=httpx.MockTransport(model)),
        sleep=lambda _: None,
    )
    rid = e.enqueue(targets=[target()], llm=True)
    e.work(rid)
    titles = [
        r
        for r in e.store.rows(claims, run_id=rid)
        if json.loads(r["body"])["field"] == "programme_title"
    ]
    assert len(titles) == 1
    methods = json.loads(titles[0]["agreeing_methods"])
    assert methods[0] == "rules-v6" and methods[1].startswith("groq:")
    assert titles[0]["claim_key"]


def test_latest_run_only_is_reviewable(engine):
    old = engine.enqueue()
    engine.work(old)
    new = engine.enqueue()
    engine.work(new)
    assert engine.report(old)["superseded"] and not engine.report(new)["superseded"]
    old_valid = next(
        r for r in engine.store.rows(claims, run_id=old) if r["validation"] == "valid"
    )
    with pytest.raises(PipelineError) as exc:
        review(engine.store, old_valid["id"], "tester", "approved")
    assert exc.value.code == "RUN_SUPERSEDED"
    # rejections are still recorded
    review(
        engine.store, old_valid["id"], "tester", "rejected", "Superseded by newer run"
    )
    with pytest.raises(PipelineError) as exc:
        publish(engine.store, old)
    assert exc.value.code == "RUN_SUPERSEDED"
    new_valid = next(
        r for r in engine.store.rows(claims, run_id=new) if r["validation"] == "valid"
    )
    review(engine.store, new_valid["id"], "tester", "approved")


def finish(e, rid, reject=lambda row, body: False):
    """Approve every valid claim except those rejected by the callback; reject the rest."""
    for row in e.store.rows(claims, run_id=rid):
        body = json.loads(row["body"])
        if row["validation"] == "valid" and not reject(row, body):
            review(e.store, row["id"], "tester", "approved")
        else:
            review(e.store, row["id"], "tester", "rejected", "Held or not accepted")


def test_structured_facts_created_and_published_only_with_approved_evidence(settings):
    e, _ = make(settings)
    rid = e.enqueue(targets=[target()])
    report = e.work(rid)
    staged = e.store.rows(structured, run_id=rid)
    assert (
        staged
        and report["structured"]
        and sum(report["structured"].values()) == len(staged)
    )
    valid_ids = {
        r["id"] for r in e.store.rows(claims, run_id=rid) if r["validation"] == "valid"
    }
    for s in staged:
        assert s["review"] == "pending" and s["fact_key"]
        assert set(json.loads(s["evidence_claim_ids"])) <= valid_ids
    tests = [s for s in staged if s["kind"] == "language_test"]
    assert tests and any("IELTS" in s["evidence_text"] for s in tests)
    # reject the admissions requirement: the facts resting on it must not publish
    adm = page_rows(e, rid)["/admissions"]["snapshot_id"]
    finish(e, rid, reject=lambda row, body: row["snapshot_id"] == adm)
    assert e.store.rows(structured, run_id=rid) == staged
    publish(e.store, rid)
    published = e.store.rows(kb_structured)
    assert not [p for p in published if p["kind"] == "language_test"]
    assert len(catalogue(e.store)[0]["structured"]) == len(published)


def test_structured_published_with_followup_evidence_in_catalogue(settings):
    e, _ = make(settings)
    rid = e.enqueue(targets=[target()])
    e.work(rid)
    finish(e, rid)
    publish(e.store, rid)
    entry = catalogue(e.store)[0]
    lang = [s for s in entry["structured"] if s["kind"] == "language_test"]
    assert lang
    evidence = lang[0]["evidence"]
    adm = page_rows(e, rid)["/admissions"]["snapshot_id"]
    assert evidence["claims"][0]["snapshot_id"] == adm
    assert evidence["claims"][0]["source_url"].endswith("/admissions")
    assert evidence["evidence_text"] in evidence["claims"][0]["quote"]
    # facts evidence also comes from the claim's own page, not the job's
    assert any(
        f["evidence"]["source_url"].endswith("/admissions") for f in entry["facts"]
    )
    client = TestClient(create_app(settings))
    body = client.get("/v1/programmes/test-bsc/structured").json()
    assert (
        body["structured"]
        and client.get("/v1/programmes/test-bsc").json()["structured"]
    )


def test_structured_cli(settings, monkeypatch):
    from typer.testing import CliRunner

    import kb_pipeline.cli as cli

    e, _ = make(settings)
    rid = e.enqueue(targets=[target()])
    e.work(rid)
    monkeypatch.setattr(cli, "engine", lambda: e)
    result = CliRunner().invoke(cli.app, ["structured", rid, "--kind", "language_test"])
    out = json.loads(result.stdout)
    assert out and all(r["kind"] == "language_test" for r in out)
    assert out[0]["all_evidence_approved"] is False


def test_migration_002_upgrades_existing_001_database(tmp_path):
    db = tmp_path / "legacy.db"
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    eng = create_engine("sqlite:///" + str(db))
    with eng.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "001")
    raw = sqlite3.connect(db)
    raw.execute("INSERT INTO ops_runs (id, status) VALUES ('r', 'awaiting_review')")
    for cid in ("c1", "c2"):
        raw.execute(
            "INSERT INTO staging_claims (id, run_id, entity_id, validation, review) VALUES (?, 'r', 'e', 'valid', 'pending')",
            (cid,),
        )
    raw.commit()
    raw.close()
    with eng.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    raw = sqlite3.connect(db)
    tables = {
        r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"ops_pages", "structured_facts", "kb_structured_facts"} <= tables
    cols = {r[1] for r in raw.execute("PRAGMA table_info(staging_claims)")}
    assert {"claim_key", "agreeing_methods"} <= cols
    # legacy rows survive with NULL keys (distinct under the unique index)
    assert raw.execute(
        "SELECT count(*), count(claim_key) FROM staging_claims"
    ).fetchone() == (2, 0)
    raw.execute(
        "INSERT INTO staging_claims (id, run_id, claim_key) VALUES ('n1', 'r', 'k')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        raw.execute(
            "INSERT INTO staging_claims (id, run_id, claim_key) VALUES ('n2', 'r', 'k')"
        )
    raw.close()
