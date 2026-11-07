"""Regression tests for verified code-review findings (negation, scope, intake, ...)."""

import pytest

from kb_pipeline.contracts import Claim, GENERAL_SCOPE
from kb_pipeline.normalize import normalize_claim

GEN = GENERAL_SCOPE


def _claim(field, quote, group=GEN):
    return Claim(
        field=field,
        value=quote,
        quote=quote,
        location_id="b0",
        applicant_group=group,
        intake=None,
        conditions=None,
    )


def kinds(quote, field="requirement"):
    return [
        (f.kind, f.data.model_dump(exclude_none=True))
        for f in normalize_claim("c", _claim(field, quote))
    ]


# ---- finding 1: negated APS


@pytest.mark.parametrize(
    "quote",
    [
        "An APS certificate is not required for applicants from the EU.",
        "APS is not necessary for this programme.",
        "Ein APS-Zertifikat ist nicht erforderlich.",
        "Es ist kein APS-Zertifikat erforderlich.",
        "The APS certificate is no longer needed.",
        "Applicants are exempt from the APS certificate.",
        "Bewerber sind vom APS-Zertifikat befreit.",
    ],
)
def test_negated_aps_not_emitted(quote):
    assert not [k for k in kinds(quote) if k[0] == "aps_required"]


def test_positive_aps_still_emitted():
    out = kinds(
        "APS certificate required for applicants who studied in China or India."
    )
    assert out[0][0] == "aps_required"


# ---- finding 2: language tests / levels / restriction


def test_negated_language_test_not_accepted():
    assert not [
        k for k in kinds("IELTS Online is not accepted.") if k[0] == "language_test"
    ]


def test_negated_clause_drops_only_that_test():
    out = kinds(
        "IELTS (minimum 6.5) and TOEFL iBT (minimum 90) are accepted, but PTE Academic is not accepted."
    )
    tests = {k[1]["test"] for k in out if k[0] == "language_test"}
    assert tests == {"IELTS", "TOEFL_IBT"}


def test_negated_language_level_not_emitted():
    q = "German language skills at level B2 CEFR are not required."
    assert not [k for k in kinds(q) if k[0] == "language_level"]
    q = "Nachweis über Deutschkenntnisse Niveau B2 ist nicht erforderlich."
    assert not [k for k in kinds(q) if k[0] == "language_level"]


@pytest.mark.parametrize(
    "quote",
    [
        "The programme is not admission-restricted.",
        "The programme is not restricted.",
        "Der Studiengang ist nicht zulassungsbeschränkt.",
        "The programme has no admission restriction in place.",
    ],
)
def test_negated_restriction_never_true(quote):
    for kind, data in kinds(quote):
        if kind == "restricted_admission":
            assert data["restricted"] is False


def test_mixed_admission_free_fixture_emits_nothing_restricted():
    q = "Admissions: First semester: without special admission requirements (admission-free) Higher semesters: with special admission requirements according to the admission regulations"
    assert not [k for k in kinds(q) if k[0] == "restricted_admission"]


# ---- finding 3: applicant-group detection

from kb_pipeline.contracts import Target  # noqa: E402
from kb_pipeline.extract import (  # noqa: E402
    detect_applicant_scope,
    detect_recurring_intake,
    rule_claims,
    validate,
)


def _target():
    return Target(
        id="t",
        institution="Uni",
        programme="MSc X",
        level="master",
        url="https://example.edu/x",
        allowed_hosts=["example.edu"],
    )


def _blk(text, heading="", tag="p", id="b0", **loc):
    return {"id": id, "text": text, "heading": heading, "location": {"tag": tag, **loc}}


@pytest.mark.parametrize(
    "text",
    [
        "Students from India must submit an additional document.",
        "Applicants who studied in China need extra proof of their degree.",
        "Vietnam based applicants must verify their transcripts.",
        "Chinese applicants must provide a certificate of study.",
        "Vietnamese degrees are verified separately by the university.",
        "Non-German applicants must submit certified copies.",
        "Third-country nationals need a visa for entry to study.",
        "Third country applicants must register earlier.",
        "Drittstaatsangehörige müssen ein Visum beantragen.",
        "Overseas applicants must apply earlier than others.",
        "Citizens of some countries must apply through a portal.",
        "Je nach Staatsangehörigkeit gelten andere Fristen für die Bewerbung.",
        "The APS certificate must be submitted with the application documents.",
        "Applicants from Ghana must send originals by post to the office.",
        "Pakistan degrees need an extra review step before admission.",
    ],
)
def test_group_words_make_scope_unestablished(text):
    assert detect_applicant_scope(text) == "not established"


@pytest.mark.parametrize(
    "text",
    [
        "Applications from March onwards are processed quickly in our office.",
        "Students from Germany and abroad may apply for this course.",
    ],
)
def test_from_pattern_not_overeager(text):
    assert detect_applicant_scope(text) == GENERAL_SCOPE


LIST_TEXT = "Applicants must submit a notarised copy of their degree certificate."


def _list_doc(
    label_heading="Admission",
    li_heading="Admission",
    label_text="For applicants from India:",
):
    return {
        "blocks": [
            _blk(label_text, label_heading, id="b1"),
            _blk(LIST_TEXT, li_heading, tag="li", id="b0"),
        ]
    }


def test_list_item_inherits_group_from_preceding_label_paragraph():
    d = _list_doc()
    c = _claim("requirement", LIST_TEXT)
    assert validate(c, d) == "APPLICANT_SCOPE_CONFLICT"
    rc = [x for x in rule_claims(d, _target()) if x.field == "requirement"]
    assert rc and all(x.applicant_group == "not established" for x in rc)


def test_label_in_other_section_or_not_a_label_is_ignored():
    c = _claim("requirement", LIST_TEXT)
    assert validate(c, _list_doc(label_heading="Other")) == "valid"
    assert (
        validate(
            c,
            _list_doc(label_text="For applicants from India and more words " * 6 + ":"),
        )
        == "valid"
    )
    assert validate(c, _list_doc(label_text="For applicants from India")) == "valid"
    # a plain paragraph in between is the nearest preceding p
    d = _list_doc()
    d["blocks"].insert(
        1, _blk("Everybody else follows these rules.", "Admission", id="b2")
    )
    assert validate(c, d) == "valid"


def test_table_row_inherits_label():
    d = {
        "blocks": [
            _blk("Non-EU applicants:", "Fees", id="b1"),
            _blk("Tuition fees: 1500 EUR", "Fees", tag="tr", id="b0"),
        ]
    }
    c = _claim("tuition", "Tuition fees: 1500 EUR")
    assert validate(c, d) == "APPLICANT_SCOPE_CONFLICT"


def test_pdf_blocks_need_group_free_block_itself():
    group_text = "International applicants must provide a language certificate."
    d = {
        "blocks": [
            {"id": "b0", "text": group_text, "heading": "", "location": {"page": 2}}
        ]
    }
    assert validate(_claim("requirement", group_text), d) == "APPLICANT_SCOPE_CONFLICT"
    plain = "Applicants must provide a certified copy of the degree."
    d = {
        "blocks": [
            {
                "id": "b1",
                "text": "For applicants from India:",
                "heading": "",
                "location": {"page": 2},
            },
            {"id": "b0", "text": plain, "heading": "", "location": {"page": 2}},
        ]
    }
    assert validate(_claim("requirement", plain), d) == "valid"


# ---- finding 4: year-specific / decimal intake


@pytest.mark.parametrize(
    "heading", ["Winter semester 2026", "Winter semester 2025/26", "Winter term 25/26"]
)
def test_recurring_intake_rejected_for_year_specific_block(heading):
    b = _blk("Application deadline: 15 July", heading, tag="tr")
    assert detect_recurring_intake(b) is None
    c = _claim("deadline", b["text"])
    c = c.model_copy(update={"intake": "winter semester (recurring)"})
    assert validate(c, {"blocks": [b]}) == "INTAKE_NOT_GROUNDED"
    assert rule_claims({"blocks": [b]}, _target())[0].intake is None


def test_recurring_intake_year_in_text():
    b = _blk("Deadline for the winter semester 2026: 15 July", tag="tr")
    assert detect_recurring_intake(b) is None


def test_decimal_not_a_date():
    b = _blk("Winter semester modules, see regulation 2.1; details follow", tag="tr")
    assert detect_recurring_intake(b) is None
    assert (
        detect_recurring_intake(_blk("Winter semester: Bewerbung bis 15.07."))
        is not None
    )


# ---- finding 5: model limit codes keep rule candidates

import json  # noqa: E402
from dataclasses import replace  # noqa: E402
from decimal import Decimal  # noqa: E402

import httpx  # noqa: E402

import kb_pipeline.engine as engine_module  # noqa: E402
from kb_pipeline.contracts import PipelineError  # noqa: E402
from kb_pipeline.db import claims, errors, jobs, pages  # noqa: E402
from kb_pipeline.engine import Engine  # noqa: E402

HOST = "university.example"


class _Raises:
    def __init__(self, code):
        self.code, self.job_id = code, None

    def close(self):
        pass

    def extract(self, blocks, target, *, offline=False):
        raise PipelineError(self.code, "synthetic model failure")


def _site(pages_by_path):
    def handle(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        body = pages_by_path.get(request.url.path)
        if body is None:
            return httpx.Response(404)
        return httpx.Response(
            200, content=body.encode(), headers={"content-type": "text/html"}
        )

    return httpx.Client(transport=httpx.MockTransport(handle))


def _llm_engine(settings, pages_by_path, monkeypatch, code):
    cfg = replace(
        settings,
        provider="groq",
        model="openai/gpt-oss-20b",
        fallback_model="",
        api_key="synthetic-key",
        input_rate=Decimal(".075"),
        output_rate=Decimal(".30"),
    )
    monkeypatch.setattr(engine_module, "extractor", lambda *a, **k: _Raises(code))
    return Engine(cfg, fetch_client=_site(pages_by_path), sleep=lambda _: None)


def _tgt():
    return Target(
        id="t-bsc",
        institution="Uni",
        programme="Computer Science",
        level="bachelor",
        url=f"https://{HOST}/cs",
        allowed_hosts=[HOST],
    )


def _events(e, rid):
    path = e.settings.data_dir / "logs" / rid / "events.jsonl"
    return [json.loads(x) for x in path.read_text().splitlines()]


PAGE = (
    "<html><main><h1>Computer Science (B.Sc.)</h1>"
    "<table><tr><td>Duration and credits</td><td>6 semesters; 180 ECTS credits</td></tr></table>"
    "<p>Admission requirements: {big}</p>{links}</main></html>"
)
BIG = "x" * 13000


@pytest.mark.parametrize("code", ["SECTION_TOO_LARGE", "MODEL_DOCUMENT_LIMIT"])
def test_model_limit_keeps_rule_candidates_primary(settings, monkeypatch, code):
    e = _llm_engine(
        settings, {"/cs": PAGE.format(big=BIG, links="")}, monkeypatch, code
    )
    rid = e.enqueue(targets=[_tgt()], llm=True)
    report = e.work(rid)
    assert report["documents"] == {"done": 1}
    assert any(
        json.loads(r["body"])["field"] == "ects"
        for r in e.store.rows(claims, run_id=rid)
    )
    ev = [x for x in _events(e, rid) if x["event"] == "extract.model_skipped"]
    assert ev and ev[0]["level"] == "WARNING" and ev[0]["code"] == code
    assert any(
        r["code"] == code and r["stage"] == "extract"
        for r in e.store.rows(errors, run_id=rid)
    )


def test_model_limit_keeps_rule_candidates_followup(settings, monkeypatch):
    links = '<p><a href="/admissions">Admission requirements</a></p>'
    adm = (
        "<html><main><h1>Admission</h1><p>Applicants must provide an English language "
        "certificate: IELTS 6.5 at the time of application.</p></main></html>"
    )
    e = _llm_engine(
        settings,
        {"/cs": PAGE.format(big="short", links=links), "/admissions": adm},
        monkeypatch,
        "MODEL_DOCUMENT_LIMIT",
    )
    rid = e.enqueue(targets=[_tgt()], llm=True)
    report = e.work(rid)
    assert report["documents"] == {"done": 1}
    page_status = [
        p["status"]
        for j in e.store.rows(jobs, run_id=rid)
        for p in e.store.rows(pages, job_id=j["id"])
    ]
    assert page_status == ["done"]
    assert any(
        "IELTS" in json.loads(r["body"])["quote"]
        for r in e.store.rows(claims, run_id=rid)
    )
    skipped = [x for x in _events(e, rid) if x["event"] == "extract.model_skipped"]
    assert len(skipped) == 2 and any("page_url" in x for x in skipped)


def test_other_model_errors_still_propagate(settings, monkeypatch):
    e = _llm_engine(
        settings,
        {"/cs": PAGE.format(big="short", links="")},
        monkeypatch,
        "MODEL_BROKEN",
    )
    rid = e.enqueue(targets=[_tgt()], llm=True)
    assert e.work(rid)["documents"] == {"failed": 1}


# ---- finding 6: degree-level link filter + unverified regulations pages

from kb_pipeline.links import select_followups  # noqa: E402

H = "https://www.uni-x.de"


def _t(level):
    return Target(
        id="x",
        institution="X",
        programme="Informatik",
        level=level,
        url=f"{H}/en/study/cs",
        allowed_hosts=["www.uni-x.de"],
    )


def _pick(level, *pairs):
    d = {"blocks": [], "links": [{"url": u, "text": t} for u, t in pairs]}
    return [r["url"] for r in select_followups(d, _t(level))]


def test_links_for_other_degree_level_skipped():
    bach = (f"{H}/files/AStuPO_Bachelor_FIM.pdf", "Studienordnung")
    mast = (f"{H}/files/Master_Informatik.pdf", "Prüfungsordnung")
    assert _pick("master", bach, mast) == [mast[0]]
    assert _pick("bachelor", bach, mast) == [bach[0]]
    assert _pick("master", (f"{H}/a", "Examination regulations B.Sc.")) == []
    assert _pick("bachelor", (f"{H}/a", "Examination regulations M.Sc.")) == []
    assert _pick("master", (f"{H}/files/po-bsc.pdf", "Prüfungsordnung")) == []
    # both or neither level named: kept
    both = (f"{H}/a", "Examination regulations for Bachelor and Master")
    assert _pick("master", both) == [both[0]] and _pick("bachelor", both) == [both[0]]
    assert _pick("master", (f"{H}/a", "Examination regulations")) == [f"{H}/a"]
    # words merely containing the letters are not degree names
    assert _pick("master", (f"{H}/basics/apply", "Apply")) == [f"{H}/basics/apply"]
    assert _pick("bachelor", (f"{H}/admission-mathematics", "Admission")) == [
        f"{H}/admission-mathematics"
    ]


REGS_LINKS = (
    '<p><a href="/regs-physics">Examination regulations (physics)</a></p>'
    '<p><a href="/regs-cs">Examination regulations (computer)</a></p>'
)
REGS_OTHER = (
    "<html><main><h1>Examination regulations Physics</h1><p>Applicants must provide proof of "
    "English language skills at level B2 before enrolment.</p></main></html>"
)
REGS_OWN = (
    "<html><main><h1>Examination regulations Computer Science</h1><p>Applicants must provide proof "
    "of English language skills at level C1 before enrolment.</p></main></html>"
)


def test_regulation_pages_of_other_programmes_are_held(settings):
    e = Engine(
        settings,
        fetch_client=_site(
            {
                "/cs": PAGE.format(big="short", links=REGS_LINKS),
                "/regs-physics": REGS_OTHER,
                "/regs-cs": REGS_OWN,
            }
        ),
        sleep=lambda _: None,
    )
    rid = e.enqueue(targets=[_tgt()])
    e.work(rid)
    status = {
        ("B2" if "B2" in json.loads(r["body"])["quote"] else "C1"): r["validation"]
        for r in e.store.rows(claims, run_id=rid)
        if json.loads(r["body"])["field"] == "requirement"
        and "English language skills" in json.loads(r["body"])["quote"]
    }
    assert status == {"B2": "FOLLOWUP_PROGRAMME_UNVERIFIED", "C1": "valid"}


# ---- finding 7: supersession only for published entities; fixed-width timestamps

from kb_pipeline import db as db_module  # noqa: E402
from kb_pipeline.knowledge import publish, review  # noqa: E402


def test_now_is_fixed_width_even_with_zero_microseconds(monkeypatch):
    from datetime import datetime, timezone

    class Fake(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 1, 1, 0, 0, 0, 0, tzinfo=tz or timezone.utc)

    monkeypatch.setattr(db_module, "datetime", Fake)
    stamp = db_module.now()
    assert len(stamp) == len("2026-01-01T00:00:00.000000+00:00")


def test_publish_ignores_newer_run_for_entities_without_approved_claims(settings):
    def tgt(i):
        return Target(
            id=f"t-{i}",
            institution="Uni",
            programme="Computer Science",
            level="bachelor",
            url=f"https://{HOST}/{i}",
            allowed_hosts=[HOST],
        )

    body = PAGE.format(big="short", links="")
    e = Engine(
        replace(settings, followup_limit=0),
        fetch_client=_site({"/a": body, "/b": body}),
        sleep=lambda _: None,
    )
    r1 = e.enqueue(targets=[tgt("a"), tgt("b")])
    e.work(r1)
    for row in e.store.rows(claims, run_id=r1):
        if row["entity_id"] == "t-a" and row["validation"] == "valid":
            review(e.store, row["id"], "tester", "approved")
        else:
            review(e.store, row["id"], "tester", "rejected", "not accepted")
    r2 = e.enqueue(targets=[tgt("b")])
    e.work(r2)
    assert publish(e.store, r1)


# ---- finding 8: replay pins the parent job's follow-up snapshots


def test_replay_uses_parent_jobs_followup_snapshot_not_newest(settings):
    links = '<p><a href="/admissions">Admission requirements</a></p><p><a href="/gone-apply">How to apply</a></p>'
    pages_by_path = {
        "/cs": PAGE.format(big="short", links=links),
        "/admissions": "<html><main><h1>Admission</h1><p>Applicants must provide an English language certificate: IELTS 6.5 at the time of application.</p></main></html>",
    }
    e = Engine(settings, fetch_client=_site(pages_by_path), sleep=lambda _: None)
    r1 = e.enqueue(targets=[_tgt()])
    e.work(r1)
    job1 = e.store.rows(jobs, run_id=r1)[0]
    old = next(
        p
        for p in e.store.rows(pages, job_id=job1["id"])
        if p["url"].endswith("/admissions")
    )
    err = next(x for x in e.store.rows(errors, run_id=r1) if x["job_id"] == job1["id"])
    # the page changes and a later normal run observes a newer snapshot
    pages_by_path["/admissions"] = pages_by_path["/admissions"].replace("6.5", "7.5")
    r2 = e.enqueue(targets=[_tgt()])
    e.work(r2)
    job2 = e.store.rows(jobs, run_id=r2)[0]
    new = next(
        p
        for p in e.store.rows(pages, job_id=job2["id"])
        if p["url"].endswith("/admissions")
    )
    assert new["snapshot_id"] != old["snapshot_id"]
    replay = e.replay(err["id"])
    e.work(replay)
    job3 = e.store.rows(jobs, run_id=replay)[0]
    got = next(
        p
        for p in e.store.rows(pages, job_id=job3["id"])
        if p["url"].endswith("/admissions")
    )
    assert got["snapshot_id"] == old["snapshot_id"]
