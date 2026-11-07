import pytest
from kb_pipeline.contracts import Claim, GENERAL_SCOPE, Target
from kb_pipeline.extract import (
    detect_applicant_scope,
    detect_recurring_intake,
    quality,
    rule_claims,
    validate,
)

WINTER = "winter semester (recurring)"
SUMMER = "summer semester (recurring)"


def blk(text, heading="", tag="p", id="b0"):
    return {"id": id, "text": text, "heading": heading, "location": {"tag": tag}}


def doc(*blocks):
    return {"blocks": list(blocks)}


def claim(field, text, group=GENERAL_SCOPE, intake=None, value=None, **kw):
    return Claim(
        field=field,
        value=value or text,
        quote=text,
        location_id="b0",
        applicant_group=group,
        intake=intake,
        conditions=None,
        **kw,
    )


REQ = "Applicants must hold a bachelor degree in a related subject area."


def target():
    return Target(
        id="t",
        institution="Uni",
        programme="MSc X",
        level="master",
        url="https://example.edu/x",
        allowed_hosts=["example.edu"],
    )


def test_general_scope_accepted():
    assert validate(claim("requirement", REQ), doc(blk(REQ))) == "valid"
    assert quality(claim("requirement", REQ), "valid")["components"]["applicability"]


@pytest.mark.parametrize(
    "text",
    [
        "International applicants must provide a language certificate for entry.",
        "Non-EU students must pay tuition fees of 1500 euros per semester.",
        "Bildungsausländer müssen einen Sprachnachweis vorlegen und eingereicht haben.",
        "Applicants with a foreign school-leaving certificate must take the exam.",
    ],
)
def test_group_mentioning_block_held(text):
    assert detect_applicant_scope(text) == "not established"
    c = claim("requirement", text, group="not established")
    assert validate(c, doc(blk(text))) == "MISSING_APPLICANT_SCOPE"
    r = rule_claims(doc(blk(text)), target())
    assert r and all(x.applicant_group == "not established" for x in r)


def test_llm_general_scope_conflict():
    text = "International applicants must provide a language certificate."
    assert (
        validate(claim("requirement", text), doc(blk(text)))
        == "APPLICANT_SCOPE_CONFLICT"
    )
    assert not quality(claim("requirement", text), "APPLICANT_SCOPE_CONFLICT")[
        "components"
    ]["applicability"]


def test_rules_use_general_scope_and_keep_known_target_group():
    r = rule_claims(doc(blk(REQ)), target())
    assert r[0].applicant_group == GENERAL_SCOPE
    t = target().model_copy(update={"applicant_group": "EU applicants"})
    assert rule_claims(doc(blk(REQ)), t)[0].applicant_group == "EU applicants"


def test_recurring_winter_deadline_valid():
    text = "Application deadline: 15 July for the winter semester"
    b = blk(text, tag="tr")
    assert detect_recurring_intake(b) == WINTER
    c = rule_claims(doc(b), target())
    assert len(c) == 1 and c[0].intake == WINTER
    assert validate(c[0], doc(b)) == "valid"
    assert quality(c[0], "valid")["components"]["applicability"]


def test_recurring_not_grounded():
    text = "Application deadline: 15 July for the winter semester"
    c = claim("deadline", text, intake=SUMMER)
    assert validate(c, doc(blk(text))) == "INTAKE_NOT_GROUNDED"
    nodate = "Application deadline: see portal for the winter semester"
    c = claim("deadline", nodate, intake=WINTER)
    assert validate(c, doc(blk(nodate))) == "INTAKE_NOT_GROUNDED"


def test_both_seasons_held():
    text = "Application deadline: 15 July for the winter semester, 15 January for the summer semester"
    b = blk(text, tag="tr")
    assert detect_recurring_intake(b) is None
    c = rule_claims(doc(b), target())
    assert c[0].intake is None
    assert validate(c[0], doc(b)) == "MISSING_INTAKE_SCOPE"
    assert (
        validate(claim("deadline", text, intake=WINTER), doc(b))
        == "INTAKE_NOT_GROUNDED"
    )


def test_year_intake_still_works_and_no_season_no_recurring():
    q = "Applications close 31 May"
    c = claim("deadline", q, intake="winter 2030")
    assert validate(c, doc(blk(q, "Winter semester 2030"))) == "valid"
    assert validate(c, doc(blk(q, "Winter semester"))) == "INTAKE_NOT_GROUNDED"
    assert detect_recurring_intake(blk(q)) is None


def test_german_deadline():
    text = "Bewerbungsfrist für das Wintersemester: 15. Juli"
    b = blk(text, tag="tr")
    assert detect_recurring_intake(b) == WINTER
    c = rule_claims(doc(b), target())
    assert not c  # rule only fires on English 'deadline' rows
    assert validate(claim("deadline", text, intake=WINTER), doc(b)) == "valid"
    sose = blk("Bewerbung zum SoSe bis 15.01.")
    assert detect_recurring_intake(sose) == SUMMER


def test_german_group_and_march():
    assert (
        detect_applicant_scope("Für Bildungsinländer gilt eine andere Frist")
        == "not established"
    )
    assert (
        detect_applicant_scope("Bewerbungsfrist 1. März für das Sommersemester")
        == GENERAL_SCOPE
    )
    assert detect_recurring_intake(blk("Frist 1. März", "Sommersemester")) == SUMMER


def test_heading_claim_not_a_fact():
    h = blk("Requirements", tag="h2")
    c = claim("requirement", "Requirements")
    assert validate(c, doc(h)) == "NOT_A_FACT"
    same = blk(
        "Admission requirements and more text here that is long enough",
        "Admission requirements and more text here that is long enough",
    )
    assert validate(claim("requirement", same["text"]), doc(same)) == "NOT_A_FACT"
    assert not rule_claims(doc(blk("Requirements", tag="h2")), target())


def test_short_and_faq_requirement_not_a_fact():
    short = "A prior degree is required."
    assert validate(claim("requirement", short), doc(blk(short))) == "NOT_A_FACT"
    assert not rule_claims(doc(blk(short)), target())
    faq = "What documents are required for the application process here?"
    assert validate(claim("requirement", faq), doc(blk(faq))) == "NOT_A_FACT"
    faq2 = "Frequently Asked Questions about the requirements for admission"
    assert validate(claim("requirement", faq2), doc(blk(faq2))) == "NOT_A_FACT"


def test_title_exempt_from_noise_filter():
    b = blk("MSc Data Science", tag="h1")
    c = claim("programme_title", "MSc Data Science", group="not established")
    assert validate(c, doc(b)) == "valid"
