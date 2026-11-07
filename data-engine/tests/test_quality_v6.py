"""Quality fixes after the run-4 analysis (rules-v6 / regex-v3).

Fixtures are real texts from data/backups/run4.claims.json and the cached freiburg-msc,
saarland-bsc and passau pages.
"""

import json
from dataclasses import replace
from decimal import Decimal

import httpx
import pytest

import kb_pipeline.engine as engine_module
from kb_pipeline.contracts import Claim, PipelineError, GENERAL_SCOPE
from kb_pipeline.db import claims, jobs, pages, structured
from kb_pipeline.engine import Engine
from kb_pipeline.extract import (
    canonical_title,
    is_placeholder,
    rule_claims,
    validate,
    value_in_quote,
)
from kb_pipeline.grounding import ground
from kb_pipeline.knowledge import list_structured
from kb_pipeline.normalize import (
    merge_facts,
    normalize_claim,
    normalize_claims,
    superseded_windows,
)
from test_followups_integration import (
    FEES,
    HOST,
    LINKS,
    make,
    page,
    target,
)

GEN = GENERAL_SCOPE


def blk(id, text, heading="Study", tag="p"):
    return {"id": id, "text": text, "heading": heading, "location": {"tag": tag}}


def claim(field, text, value=None, id="b0", group=GEN, intake=None, quote=None):
    return Claim(
        field=field,
        value=value or text,
        quote=quote or text,
        location_id=id,
        applicant_group=group,
        intake=intake,
        conditions=None,
    )


def check(field, text, **kw):
    doc = {"blocks": [blk("b0", text)]}
    return validate(claim(field, text, **kw), doc)


# ---- 1. regulation clauses are not admission requirements ------------------------

REGULATION = [
    "(3) As a rule, students who work as course tutors shall be awarded 4 credits (cf. the programme-specific study regulations).",
    "9. At least 6 ungraded credits from the mandatory elective category ‘German or English Language Courses’ at Saarland University (note: the language chosen shall not be the student’s native language); the Examination Board may, on request, permit courses in other languages.",
    "Students shall accumulate a total of 42 CP in the compulsory part of the curriculum (of which 30 CP are from the ‘Master’s thesis’ module and 12 CP are from the ‘Master’s seminar’) and at least 78 CP from the mandatory electives.",
    "(1) Students may register for the final assessment phase in which they complete their Bachelor’s or Master’s thesis provided that they have properly completed all of the stipulated programme requirements.",
    "Before enrolling or re-registering, all students must currently pay a semester fee of €412,30, which includes the student-services payment and the administrative charge.",
    "(4) Students who have acquired core skills through other work or activities at Saarland University may apply to have this work recognized. Section 19(4) shall apply accordingly.",
]


@pytest.mark.parametrize("text", REGULATION)
def test_regulation_clauses_are_held_not_a_fact(text):
    assert check("requirement", text) == "NOT_A_FACT"


ADMISSION = [
    "Applicants must provide an English language certificate: IELTS 6.5 or TOEFL iBT 90 at the time of application.",
    "To apply, you need to have an undergraduate university degree in computer science or a related discipline with a computer science component of at least 110 ECTS credits.",
    "Your degree must have been earned over a course of study of a standard length of three years or more. If you completed a four-year non-ECTS degree, the 110 ECTS credit requirement is deemed to be met.",
    "As part of the application you must submit an English or German-language abstract of your undergraduate dissertation/bachelor's thesis/final year project.",
    "Even if you plan to choose only modules taught in English, you also need German language skills at level A1 CEFR (beginner's level) or higher.",
]


@pytest.mark.parametrize("text", ADMISSION)
def test_genuine_admission_requirements_stay_valid(text):
    assert check("requirement", text) == "valid"


def test_numbered_subsection_fragments():
    admission = "(5) If the requirements of Subsection 4 are not met, the student may be provisionally admitted to the relevant Master’s degree programme on condition that he or she acquires the missing curricular content."
    # admission-related -> incomplete without Subsection 4; anything else -> noise
    assert check("requirement", admission) == "INCOMPLETE_REQUIREMENT"
    other = "(2) The date shall be documented as set out in paragraph 3 and sent to the office."
    assert check("requirement", other) == "NOT_A_FACT"
    # a numbered admission clause with no cross reference is not rejected on that basis
    plain = "(2) Applicants must hold a Bachelor’s degree in computer science or an equivalent qualification."
    assert check("requirement", plain) == "valid"


# ---- 2. programme title variants -------------------------------------------------


@pytest.mark.parametrize(
    "a,b",
    [
        ("Computer Science (M.Sc.)", "M.Sc. Computer Science"),
        ("Computer Science B.Sc.", "B.Sc. Computer Science"),
        ("computer science, MSc", "Master of Science Computer Science"),
        ("Computer Science (B.Sc.)", "Computer Science"),
    ],
)
def test_title_variants_agree(a, b):
    members = [(None, {"field": "programme_title", "value": v}) for v in (a, b)]
    assert not Engine._values_disagree(members)


@pytest.mark.parametrize(
    "a,b",
    [
        ("Computer Science (M.Sc.)", "Data Science (M.Sc.)"),
        ("Computer Science B.Sc.", "Computer Science (M.Sc.)"),
    ],
)
def test_genuinely_different_titles_conflict(a, b):
    members = [(None, {"field": "programme_title", "value": v}) for v in (a, b)]
    assert Engine._values_disagree(members)
    assert canonical_title(a) != canonical_title(b)


def test_non_title_conflict_logic_unchanged():
    m = [(None, {"field": "ects", "value": v}) for v in ("120", "120 ")]
    assert not Engine._values_disagree(m)
    m = [(None, {"field": "ects", "value": v}) for v in ("120", "90")]
    assert Engine._values_disagree(m)


# ---- 3. placeholders --------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "Not specified",
        "See current fee structure",
        "Semester fee See current fee structure",
        "n/a",
        "N/A",
        "TBA",
        "unknown",
        "Varies",
    ],
)
@pytest.mark.parametrize("field", ["deadline", "tuition", "semester_contribution"])
def test_placeholders_rejected_before_grounding(field, value):
    assert is_placeholder(value, field)
    # even with a location that does not exist: placeholder wins over EVIDENCE_NOT_FOUND
    doc = {"blocks": [blk("other", "Something else entirely about fees and deadlines.")]}
    result = validate(
        claim(
            field,
            value,
            quote="Fee info: " + value,
            id="b0001",
            intake="winter semester 2026",
        ),
        doc,
    )
    assert result == "NOT_A_FACT"


def test_real_values_are_not_placeholders():
    for value in ("€412.30", "190 EUR per semester", "15 July", "Not applicable"):
        assert not is_placeholder(value, "tuition")
    long_req = "Applicants must read the see current page details before applying and must submit documents."
    assert not is_placeholder(long_req, "requirement")


def test_placeholder_never_conflicts_with_real_fee(settings):
    # primary page says "See current fee structure"; follow-up has the real number
    primary = page(
        "Computer Science (B.Sc.)",
        "<table><tr><td>Tuition fees</td><td>See current fee structure</td></tr></table>",
        LINKS,
    )
    e, _ = make(settings, extra={"/cs": primary})
    rid = e.enqueue(targets=[target()])
    e.work(rid)
    rows = [
        (json.loads(r["body"]), r["validation"])
        for r in e.store.rows(claims, run_id=rid)
        if json.loads(r["body"])["field"] == "tuition"
    ]
    by_value = {b["value"]: v for b, v in rows}
    assert by_value["See current fee structure"] == "NOT_A_FACT"
    assert not any(v == "CONFLICTING_VALUES" for v in by_value.values())
    assert any("190 EUR" in k for k in by_value)


# ---- 4. grounding misses ----------------------------------------------------------

PASSAU_A = 'You have to pay a semester fee (" Semesterbeitrag " in German) at the start of each semester. This must be paid when you enrol for the first time, or re-register to continue your studies.'
PASSAU_B = "For summer semester 2027, the fee is € 134 . Of this, € 87 go to the Student Services Association ( Studierendenwerk ), which operate the refectory, cafeterias and halls of residence, among other things."
PASSAU_C = "Please don't forget to validate your campus card at the start of each semester, before you use it on any buses."
PASSAU_D = "Should you change your mind and de-register from your programme before the semester officially starts, you can obtain a refund of this fee."


def test_multiblock_quote_with_value_in_one_block_is_grounded():
    """Run-4 passau-msc: the model joined three non-adjacent paragraphs with newlines."""
    blocks = [
        blk("b0065", PASSAU_A, "Semester fee"),
        blk("b0066", PASSAU_B, "Semester fee"),
        blk("b0067", PASSAU_C, "Semester fee"),
        blk("b0070", PASSAU_D, "Semester fee"),
    ]
    raw = claim(
        "semester_contribution",
        "134",
        quote=PASSAU_A + "\n" + PASSAU_B + "\n" + PASSAU_D,
        id="b0065",
    )
    doc = {"blocks": blocks}
    assert validate(raw, doc) == "EVIDENCE_NOT_FOUND"
    result, action = ground(raw, blocks, source_blocks=blocks)
    assert [r.location_id for r in result] == ["b0066"]
    assert action["source_locations"] == ["b0066"]
    assert "€ 134" in result[0].value
    assert validate(result[0], doc) == "valid"


def test_multiblock_quote_without_unique_value_block_stays_unrepaired():
    blocks = [blk("a", "The fee is 134 euro."), blk("b", "Also 134 euro for others.")]
    raw = claim(
        "semester_contribution",
        "134",
        quote="The fee is 134 euro.\nAlso 134 euro for others.",
        id="a",
    )
    result, action = ground(raw, blocks, source_blocks=blocks)
    assert result == [raw] and action is None


def test_multiblock_quote_with_invented_line_stays_unrepaired():
    blocks = [blk("a", "The fee is 134 euro."), blk("b", "Unrelated paragraph.")]
    raw = claim(
        "semester_contribution",
        "134",
        quote="The fee is 134 euro.\nAn invented extra sentence.",
        id="a",
    )
    result, action = ground(raw, blocks, source_blocks=blocks)
    assert result == [raw] and action is None


SAARLAND = (
    "Section 5 Standard period of study (1) The standard period of full-time study for a "
    "single-subject Bachelor’s degree programme is six semesters, which includes the time "
    "taken to complete the final academic assessment."
)
SAARLAND_QUOTE = "The standard period of full-time study for a single-subject Bachelor’s degree programme is six semesters"


def test_number_word_duration_is_grounded_and_relocated():
    """Run-4 saarland-bsc duration '6': quote says 'six semesters', location was wrong."""
    blocks = [blk("b0000", "Joint Examination Regulations"), blk("b0002", SAARLAND)]
    raw = claim("duration_semesters", "6", quote=SAARLAND_QUOTE, id="b0000")
    result, action = ground(raw, blocks, source_blocks=blocks)
    assert result[0].location_id == "b0002" and action is not None
    assert validate(result[0], {"blocks": blocks}) == "valid"


def test_number_words_only_count_for_semester_durations():
    assert value_in_quote("duration_semesters", "6", "beträgt sechs Semester.")
    assert value_in_quote("duration_semesters", "4", "a four-semester programme")
    assert not value_in_quote("duration_semesters", "6", "six credits")
    assert not value_in_quote("ects", "6", "six semesters")
    assert not value_in_quote("duration_semesters", "5", "six semesters")


# ---- 5. duplicate structured facts -----------------------------------------------


def test_duplicate_language_tests_merge_with_all_evidence_ids():
    quotes = ["DSH -2", "DSH -2 C1 CEFR ; DSH -2", "B.Sc. Computer Science C1 CEFR ; DSH -2 B2 CEFR"]
    pairs = [(f"c{i}", claim("requirement", q)) for i, q in enumerate(quotes)]
    facts = [f for f in normalize_claims(pairs) if f.kind == "language_test"]
    assert len(facts) == 1
    assert facts[0].data.test == "DSH" and facts[0].data.min_score == "2"
    assert facts[0].evidence_claim_ids == ["c0", "c1", "c2"]


def test_duplicate_required_degree_rows_merge_but_other_scores_stay_apart():
    quotes = [
        "an undergraduate degree is required",
        "A Bachelor's degree is required.",
        "You must hold a bachelor's degree.",
    ]
    pairs = [(f"c{i}", claim("requirement", q)) for i, q in enumerate(quotes)]
    degrees = [f for f in normalize_claims(pairs) if f.kind == "required_degree"]
    assert len(degrees) == 1 and len(degrees[0].evidence_claim_ids) == 3
    pairs = [("a", claim("requirement", "DSH -1")), ("b", claim("requirement", "DSH -2"))]
    assert len([f for f in normalize_claims(pairs) if f.kind == "language_test"]) == 2


def test_fact_key_ignores_evidence_wording():
    a = normalize_claim("a", claim("requirement", "DSH -2"))[0]
    b = normalize_claim("b", claim("requirement", "DSH -2 C1 CEFR ; DSH -2"))[0]
    assert a.evidence_text != b.evidence_text and a.key() == b.key()
    assert len(merge_facts([a, b])) == 1


# ---- 6. year-specific application windows ------------------------------------------


def windows(*quotes, field="deadline"):
    pairs = [(f"c{i}", claim(field, q)) for i, q in enumerate(quotes)]
    return [f for f in normalize_claims(pairs) if f.kind == "application_window"]


def test_window_year_is_captured_when_stated():
    (w,) = windows("Applications must be received by July 31, 2025.")
    assert w.data.year == 2025 and w.data.end == "31-07"
    assert "2025" in w.evidence_text
    (w,) = windows("Bewerbungsfrist: 15.07.2026")
    assert w.data.year == 2026


def test_recurring_window_without_year_has_no_year():
    (w,) = windows("Applications must be received by July 31.")
    assert w.data.year is None
    assert superseded_windows([w]) == set()


def test_older_year_of_same_window_is_superseded():
    facts = windows(
        "Applications must be received by July 31, 2024.",
        "Applications are accepted until July 31, 2025.",
    )
    assert sorted(f.data.year for f in facts) == [2024, 2025]
    old = superseded_windows(facts)
    assert {f.data.year for f in facts if f.key() in old} == {2024}


def test_different_dates_are_not_superseded_and_recurring_is_kept():
    facts = windows(
        "Applications must be received by July 31, 2024.",
        "Applications must be received by January 15, 2025.",
        "Applications must be received by July 31.",
    )
    assert len(facts) == 3 and superseded_windows(facts) == set()


def test_superseded_window_staged_with_review_status(settings):
    body = (
        "<p>Applicants must send the application so that it is received by July 31, 2024.</p>"
        "<p>Applicants must send the application so that it is received by July 31, 2025.</p>"
    )
    e, _ = make(settings, extra={"/cs": page("Computer Science (B.Sc.)", body)})
    rid = e.enqueue(targets=[target()])
    e.work(rid)
    rows = [
        r for r in e.store.rows(structured, run_id=rid) if r["kind"] == "application_window"
    ]
    status = {json.loads(r["data"])["year"]: r["review"] for r in rows}
    assert status == {2024: "superseded", 2025: "pending"}
    listed = {f["data"]["year"]: f["review"] for f in list_structured(e.store, rid) if f["kind"] == "application_window"}
    assert listed == status


# ---- 7. IELTS / TOEFL / APS ---------------------------------------------------------

FREIBURG_ENGLISH = (
    "English language proficiency : The following English language certificates are accepted: "
    "Academic IELTS, including IELTS Online Academic (minimum 7.0), TOEFL, including TOEFL ibT home "
    "edition and TOEFL Essentials (minimum ibT score 95 or 5.0 according to the new TOEFL scale 2026), "
    "Cambridge CAE or CPE, Pearson PTE Academic (minimum score 76), telc University, TOEIC, OOPT. "
    "Only native speakers from the USA, the UK, Australia, New Zealand and Canada or students having "
    "completed their bachelor's degree in one of these countries are exempted from submitting a test score."
)
FREIBURG_APS = "APS certificate (only for applicants who have studied in China, India or Vietnam). Please note: It is not possible to submit the APS certificate after the application deadline."
SAARLAND_OLYMPIAD = "olympiad track You can provide a documentation of having successfully participated in a recognized science/informatics/mathematics olympiad, and results from an English test (IELTS or TOEFL or another accepted test result)."


def doc_of(*texts, heading="Application"):
    return {
        "blocks": [blk("b%04d" % i, t, heading, "li" if t.startswith("APS") else "p") for i, t in enumerate(texts)]
    }


@pytest.mark.parametrize("text", [FREIBURG_ENGLISH, FREIBURG_APS, SAARLAND_OLYMPIAD])
def test_rules_emit_requirement_for_test_and_aps_blocks_without_must(text):
    """These blocks say 'accepted' / name a test, never 'must/required'."""
    from kb_pipeline.contracts import Target

    tgt = Target(
        id="t",
        institution="U",
        programme="Computer Science",
        level="master",
        url=f"https://{HOST}/x",
        allowed_hosts=[HOST],
    )
    got = rule_claims(doc_of(text), tgt)
    assert [c.field for c in got if c.field == "requirement"] == ["requirement"]


def facts_of(text, field="requirement"):
    return {
        (f.kind, f.data.test if hasattr(f.data, "test") else None, getattr(f.data, "min_score", None))
        for f in normalize_claim("c", claim(field, text, group="not established"))
    }


def test_freiburg_english_certificates_yield_ielts_toefl_cambridge_pte():
    got = facts_of(FREIBURG_ENGLISH)
    assert ("language_test", "IELTS", "7.0") in got
    assert ("language_test", "TOEFL_IBT", "95") in got
    assert ("language_test", "CAMBRIDGE", None) in got
    assert ("language_test", "PTE", "76") in got


@pytest.mark.parametrize(
    "text,expected",
    [
        ("IELTS Academic with an overall band score of at least 6.5.", ("IELTS", "6.5")),
        ("Applicants need TOEFL iBT with at least 90 points.", ("TOEFL_IBT", "90")),
        ("Language certificate: TOEFL (iBT) 80 points or IELTS 6.0", ("TOEFL_IBT", "80")),
        ("English: IELTS (band 6.5)", ("IELTS", "6.5")),
    ],
)
def test_ielts_toefl_scores(text, expected):
    assert any(k[1:] == expected for k in facts_of(text))


@pytest.mark.parametrize(
    "text",
    [
        "IELTS is not required if you studied in English.",
        "No TOEFL is required for native speakers.",
        "Applicants are exempt from IELTS 6.5 if they studied in English.",
    ],
)
def test_negated_tests_still_not_emitted(text):
    assert facts_of(text) == set()


def test_aps_countries_before_and_after():
    def aps(text):
        return [
            f.data.model_dump()
            for f in normalize_claim("c", claim("requirement", text))
            if f.kind == "aps_required"
        ]

    assert aps(FREIBURG_APS) == [
        {"required": True, "countries": ["China", "India", "Vietnam"]}
    ]
    assert aps("Applicants from India must submit the APS certificate.") == [
        {"required": True, "countries": ["India"]}
    ]
    assert aps("No APS certificate is required for EU applicants.") == []


def test_scope_held_test_and_aps_claims_still_stage_facts(settings):
    body = (
        "<h2>Application</h2><ul><li>" + FREIBURG_APS + "</li></ul>"
        "<p>" + FREIBURG_ENGLISH + "</p>"
    )
    e, _ = make(settings, extra={"/cs": page("Computer Science (M.Sc.)", body)})
    rid = e.enqueue(targets=[target(level="master")])
    e.work(rid)
    held = {
        r["validation"] for r in e.store.rows(claims, run_id=rid) if "APS" in r["body"] or "IELTS" in r["body"]
    }
    assert "MISSING_APPLICANT_SCOPE" in held
    kinds = {r["kind"] for r in e.store.rows(structured, run_id=rid)}
    assert {"aps_required", "language_test"} <= kinds
    # held claims can never be approved, so these facts can never be published
    facts = list_structured(e.store, rid)
    assert not any(f["all_evidence_approved"] for f in facts if f["kind"] in ("aps_required",))


# ---- 8. follow-up rate limit does not fail the job ------------------------------------


class _RateLimitedFollowups:
    """Primary page answers, every later model call exhausts its 429 retries."""

    def __init__(self):
        self.calls, self.job_id = 0, None

    def close(self):
        pass

    def extract(self, blocks, target, *, offline=False):
        self.calls += 1
        if self.calls == 1:
            return []
        raise PipelineError("MODEL_RATE_LIMIT", "retries exhausted", retryable=False)


def test_followup_rate_limit_is_recorded_and_job_completes(settings, monkeypatch):
    stub = _RateLimitedFollowups()
    monkeypatch.setattr(engine_module, "extractor", lambda *a, **k: stub)
    cfg = replace(
        settings,
        provider="groq",
        model="openai/gpt-oss-20b",
        fallback_model="",
        api_key="synthetic-key",
        input_rate=Decimal(".075"),
        output_rate=Decimal(".30"),
    )
    client, _ = __import__("test_followups_integration").site()
    e = Engine(cfg, fetch_client=client, sleep=lambda _: None)
    rid = e.enqueue(targets=[target()], llm=True)
    report = e.work(rid)
    assert report["status"] != "paused"
    assert report["documents"] == {"done": 1}
    (job,) = e.store.rows(jobs, run_id=rid)
    assert job["status"] == "done"
    rows = {
        p["url"].rsplit("/", 1)[1]: p
        for p in e.store.rows(pages, job_id=job["id"])
    }
    assert rows["admissions"]["status"] == "skipped"
    assert rows["admissions"]["error_code"] == "MODEL_RATE_LIMIT"
    # after the first exhaustion the model is not hammered again for this job
    assert stub.calls == 2
    assert rows["fees"]["status"] == "skipped"
    # rule claims of the rate-limited follow-up pages were kept
    bodies = [json.loads(r["body"]) for r in e.store.rows(claims, run_id=rid)]
    assert any("IELTS" in b["quote"] for b in bodies)
    assert any("190 EUR" in b["value"] for b in bodies)
    assert any(
        err["code"] == "MODEL_RATE_LIMIT"
        for err in e.store.rows(__import__("kb_pipeline.db", fromlist=["errors"]).errors, run_id=rid)
    )


def test_primary_rate_limit_still_pauses(settings, monkeypatch):
    class Always:
        job_id = None

        def close(self):
            pass

        def extract(self, blocks, target, *, offline=False):
            raise PipelineError("MODEL_RATE_LIMIT", "retries exhausted")

    monkeypatch.setattr(engine_module, "extractor", lambda *a, **k: Always())
    cfg = replace(
        settings,
        provider="groq",
        model="openai/gpt-oss-20b",
        fallback_model="",
        api_key="synthetic-key",
        input_rate=Decimal(".075"),
        output_rate=Decimal(".30"),
    )
    client, _ = __import__("test_followups_integration").site()
    e = Engine(cfg, fetch_client=client, sleep=lambda _: None)
    rid = e.enqueue(targets=[target()], llm=True)
    assert e.work(rid)["status"] == "paused"


def test_versions_bumped():
    from kb_pipeline.extract import EXTRACTOR_VERSION
    from kb_pipeline.structured import NORMALIZER_VERSION
    from kb_pipeline.acquire import PARSER_VERSION

    assert (EXTRACTOR_VERSION, NORMALIZER_VERSION) == ("rules-v6", "regex-v3")
    assert PARSER_VERSION == "blocks-v2"
