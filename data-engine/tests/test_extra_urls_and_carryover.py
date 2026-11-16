"""Curated registry extra_urls and review carry-over between runs."""

import json

import pytest
from pydantic import ValidationError

from kb_pipeline.contracts import Target
from kb_pipeline.db import claims
from kb_pipeline.knowledge import review

from kb_pipeline.engine import Engine
from test_followups_integration import HOST, make, page_rows, site, target


def make_on(store, settings, extra=None):
    client, calls = site(extra)
    return Engine(settings, store=store, fetch_client=client, sleep=lambda _: None), calls

INTL = "intl.university.example"
DEADLINES = (
    "<h1>Deadlines for international applicants</h1><p>Applicants must submit the "
    "application for the winter semester by 15 July via the portal.</p>"
)


def curated(*urls, **update):
    hosts = sorted({HOST, *(u.split("/")[2] for u in urls)})
    return target().model_copy(
        update={"extra_urls": list(urls), "allowed_hosts": hosts, **update}
    )


def test_extra_url_host_must_be_allowed():
    with pytest.raises(ValidationError):
        Target(
            id="x-bsc",
            institution="X",
            programme="CS",
            level="bachelor",
            url=f"https://{HOST}/cs",
            allowed_hosts=[HOST],
            extra_urls=[f"https://{INTL}/deadlines"],
        )


def test_extra_urls_fetched_on_other_allowed_host(settings):
    e, calls = make(settings, extra={"/deadlines": DEADLINES.encode()})
    t = Target.model_validate(
        curated(f"https://{INTL}/deadlines").model_dump(mode="json")
    )
    rid = e.enqueue(targets=[t])
    e.work(rid)
    rows = page_rows(e, rid)
    assert rows["/deadlines"]["status"] == "done"
    assert json.loads(rows["/deadlines"]["roles"]) == ["curated"]
    assert (INTL, "/deadlines") in calls
    snap = rows["/deadlines"]["snapshot_id"]
    assert any(r["snapshot_id"] == snap for r in e.store.rows(claims, run_id=rid))


def test_extra_urls_run_even_when_crawl_disabled(settings):
    e, calls = make(
        settings, extra={"/deadlines": DEADLINES.encode()}, followup_limit=0
    )
    t = Target.model_validate(
        curated(f"https://{INTL}/deadlines", follow_links=False).model_dump(
            mode="json"
        )
    )
    e.work(e.enqueue(targets=[t]))
    assert (INTL, "/deadlines") in calls
    assert (HOST, "/admissions") not in calls


def test_curated_url_also_linked_is_fetched_once(settings):
    e, calls = make(settings)
    t = Target.model_validate(curated(f"https://{HOST}/fees").model_dump(mode="json"))
    rid = e.enqueue(targets=[t])
    e.work(rid)
    assert calls.count((HOST, "/fees")) == 1
    roles = json.loads(page_rows(e, rid)["/fees"]["roles"])
    assert roles == ["curated", "fees"]


def _decide_all(e, rid):
    for r in e.store.rows(claims, run_id=rid):
        if r["validation"] == "valid":
            review(e.store, r["id"], "founder", "approved")
        else:
            review(e.store, r["id"], "founder", "rejected", "held")


def test_review_carries_over_identical_claims(settings):
    e, _ = make(settings)
    first = e.enqueue(targets=[target()])
    e.work(first)
    _decide_all(e, first)
    before = {r["claim_key"]: r["review"] for r in e.store.rows(claims, run_id=first)}

    e2, _ = make_on(e.store, settings)
    second = e2.enqueue(targets=[target()])
    e2.work(second)
    rows = e2.store.rows(claims, run_id=second)
    assert rows and all(r["review"] == before[r["claim_key"]] for r in rows)
    assert all(r["reviewer"] == "carried-over" for r in rows)
    assert all(first in (r["review_note"] or "") for r in rows)


def test_changed_page_needs_fresh_review(settings):
    e, _ = make(settings)
    first = e.enqueue(targets=[target()])
    e.work(first)
    _decide_all(e, first)
    changed = (
        "<h1>Admission to the University</h1><p>Applicants must provide an English "
        "language certificate: IELTS 7.0 or TOEFL iBT 95 at the time of application.</p>"
    )
    e2, _ = make_on(e.store, settings, extra={"/admissions": changed.encode()})
    second = e2.enqueue(targets=[target()])
    e2.work(second)
    rows = page_rows(e2, second)
    adm = rows["/admissions"]["snapshot_id"]
    adm_claims = [
        r for r in e2.store.rows(claims, run_id=second) if r["snapshot_id"] == adm
    ]
    assert adm_claims and all(r["review"] == "pending" for r in adm_claims)
    # unchanged pages still carry over
    others = [
        r for r in e2.store.rows(claims, run_id=second) if r["snapshot_id"] != adm
    ]
    assert others and all(r["review"] != "pending" for r in others)


def test_markup_only_change_still_carries(settings):
    from test_followups_integration import ADMISSIONS

    e, _ = make(settings)
    first = e.enqueue(targets=[target()])
    e.work(first)
    _decide_all(e, first)
    noisy = ADMISSIONS + "<!-- csrf token 8f2a -->"
    e2, _ = make_on(e.store, settings, extra={"/admissions": noisy.encode()})
    second = e2.enqueue(targets=[target()])
    e2.work(second)
    rows = e2.store.rows(claims, run_id=second)
    assert rows and all(r["review"] != "pending" for r in rows)


def test_carry_is_idempotent_and_skips_human_decisions(settings):
    from kb_pipeline.knowledge import carry_reviews

    e, _ = make(settings)
    first = e.enqueue(targets=[target()])
    e.work(first)
    _decide_all(e, first)
    e2, _ = make_on(e.store, settings)
    second = e2.enqueue(targets=[target()])
    e2.work(second)
    assert carry_reviews(e2.store, second)["carried"] == 0
    row = next(
        r for r in e2.store.rows(claims, run_id=second) if r["validation"] == "valid"
    )
    review(e2.store, row["id"], "founder", "rejected", "changed my mind")
    carry_reviews(e2.store, second)
    assert e2.store.one(claims, id=row["id"])["reviewer"] == "founder"


def test_pending_claims_do_not_carry(settings):
    e, _ = make(settings)
    e.work(e.enqueue(targets=[target()]))
    e2, _ = make_on(e.store, settings)
    second = e2.enqueue(targets=[target()])
    e2.work(second)
    assert all(r["review"] == "pending" for r in e2.store.rows(claims, run_id=second))


class _TitleOnEveryPage:
    """Model stub that, like gpt-oss on curated fee/deadline pages, reports each
    page's own heading as the programme title."""

    job_id = None

    def close(self):
        pass

    def extract(self, blocks, target, *, offline=False):
        from kb_pipeline.contracts import Claim

        block = next(b for b in blocks if b["text"].strip())
        return [
            Claim(
                field="programme_title",
                value=block["text"][:80],
                quote=block["text"],
                location_id=block["id"],
                applicant_group="general (no specific applicant group stated)",
                intake=None,
                conditions=None,
                method="stub",
            )
        ]


def test_followup_pages_never_contribute_a_title(settings, monkeypatch):
    from dataclasses import replace
    from decimal import Decimal

    import kb_pipeline.engine as engine_module
    from kb_pipeline.db import jobs, pages

    monkeypatch.setattr(engine_module, "extractor", lambda *a, **k: _TitleOnEveryPage())
    cfg = replace(
        settings,
        provider="groq",
        model="openai/gpt-oss-20b",
        fallback_model="",
        api_key="synthetic-key",
        input_rate=Decimal(".075"),
        output_rate=Decimal(".30"),
    )
    client, _ = site()
    e = Engine(cfg, fetch_client=client, sleep=lambda _: None)
    rid = e.enqueue(targets=[target()], llm=True)
    e.work(rid)
    (job,) = e.store.rows(jobs, run_id=rid)
    followups = {p["snapshot_id"] for p in e.store.rows(pages, job_id=job["id"])}
    titles = [
        r for r in e.store.rows(claims, run_id=rid)
        if json.loads(r["body"])["field"] == "programme_title"
    ]
    assert titles
    assert all(r["snapshot_id"] not in followups for r in titles)
    assert all(r["validation"] != "CONFLICTING_VALUES" for r in titles)


@pytest.mark.parametrize(
    "a, b, disagree",
    [
        # Heidelberg's h1 carries the faculty as an eyebrow line.
        (
            "Faculty of Mathematics and Computer Science Data and Computer Science",
            "Data and Computer Science – Master",
            False,
        ),
        ("Fakultät für Informatik Informatik B.Sc.", "Informatik", False),
        # A prefix that is not an organisational unit is a different programme.
        ("Applied Data and Computer Science", "Data and Computer Science", True),
        ("Faculty of Physics Physics", "Computer Science", True),
    ],
)
def test_faculty_prefix_in_title_does_not_conflict(a, b, disagree):
    members = [({}, {"field": "programme_title", "value": v}) for v in (a, b)]
    assert Engine._values_disagree(members) is disagree
