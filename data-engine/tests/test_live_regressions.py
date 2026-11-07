"""Sanitized regressions from the first live Groq response; no credentials/source capture."""

import json
import pytest
from kb_pipeline.contracts import Claim
from kb_pipeline.extract import validate
from kb_pipeline.db import runs, claims
from kb_pipeline.knowledge import review, publish
from kb_pipeline.contracts import PipelineError


def candidate(field, value, quote, **kw):
    return Claim(
        field=field,
        value=value,
        quote=quote,
        location_id="b0",
        applicant_group=kw.pop("applicant_group", "not established"),
        intake=kw.pop("intake", None),
        conditions=kw.pop("conditions", None),
        **kw,
    )


def document(text, heading=""):
    return {"blocks": [{"id": "b0", "text": text, "heading": heading}]}


@pytest.mark.parametrize(
    "placeholder",
    ["not established", "UNKNOWN", " null ", "None", "N/A", "", "not specified"],
)
def test_nullable_scope_strings_cannot_approve_recurring_deadlines(placeholder):
    claim = candidate(
        "deadline",
        "31 May",
        "Applications close 31 May",
        intake=placeholder,
        conditions="null",
    )
    assert claim.intake is None and claim.conditions is None
    assert (
        validate(claim, document("Applications close 31 May")) == "MISSING_INTAKE_SCOPE"
    )


@pytest.mark.parametrize("applicants", ["UNKNOWN", " not established ", "null", "N/A"])
def test_unknown_applicant_aliases_remain_held(applicants):
    text = "Applicants must provide a prior degree; equivalent qualifications may be accepted."
    claim = candidate("requirement", text, text, applicant_group=applicants)
    assert claim.applicant_group == "not established"
    assert validate(claim, document(text)) == "MISSING_APPLICANT_SCOPE"


def test_intake_needs_a_source_backed_year():
    quote = "Applications close 31 May"
    recurring = candidate("deadline", "31 May", quote, intake="winter semester")
    assert (
        validate(recurring, document(quote, "Winter semester"))
        == "MISSING_INTAKE_SCOPE"
    )
    invented = candidate("deadline", "31 May", quote, intake="winter 2030")
    assert (
        validate(invented, document(quote, "Winter semester")) == "INTAKE_NOT_GROUNDED"
    )
    explicit = candidate("deadline", "31 May", quote, intake="winter 2030")
    assert validate(explicit, document(quote, "Winter semester 2030")) == "valid"


def test_partial_requirements_cannot_drop_alternatives_or_waivers():
    text = "Applicants must have 90 credits OR equivalent experience; a certificate is waived for prior English-medium education."
    partial = candidate("requirement", "Applicants must have 90 credits", text)
    assert validate(partial, document(text)) == "INCOMPLETE_REQUIREMENT"
    full = candidate("requirement", text, text)
    assert validate(full, document(text)) == "MISSING_APPLICANT_SCOPE"


@pytest.mark.parametrize(
    "field,value", [("duration_semesters", "4 semesters"), ("ects", "120 ECTS credits")]
)
def test_numeric_units_are_rejected_instead_of_silently_coerced(field, value):
    text = "Programme duration is 4 semesters and awards 120 ECTS credits."
    bad = candidate(field, value, text)
    assert validate(bad, document(text)) == "INVALID_NUMERIC_VALUE"
    good = candidate(field, value.split()[0], text)
    assert validate(good, document(text)) == "valid"


def test_older_candidates_cannot_bypass_updated_approval_checks(engine):
    rid = engine.enqueue()
    engine.work(rid)
    config = json.loads(engine.store.one(runs, id=rid)["config"])
    config["schema"] = "claims-v1"
    engine.store.update(runs, rid, config=json.dumps(config))
    title = next(
        r
        for r in engine.store.rows(claims, run_id=rid)
        if json.loads(r["body"])["field"] == "programme_title"
    )
    assert not engine.report(rid)["validation_version_current"]
    with pytest.raises(PipelineError) as error:
        review(engine.store, title["id"], "test reviewer", "approved")
    assert error.value.code == "REVIEW_VERSION_CHANGED"
    with pytest.raises(PipelineError) as error:
        publish(engine.store, rid)
    assert error.value.code == "REVIEW_VERSION_CHANGED"
