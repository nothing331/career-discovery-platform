"""Held-claim fixes: recurring intake from the claim's own block, euro-amount
comparison for fees, and programme-page precedence in conflicts."""

from decimal import Decimal

import pytest

from kb_pipeline.contracts import Claim, GENERAL_SCOPE
from kb_pipeline.engine import Engine
from kb_pipeline.extract import euro_amounts, fill_recurring_intake, validate


def doc(heading, text, tag="p"):
    return {
        "blocks": [
            {"id": "b0001", "heading": heading, "text": text, "location": {"tag": tag}}
        ]
    }


def deadline(quote, intake=None, value=None):
    return Claim(
        field="deadline",
        value=value or quote,
        quote=quote,
        location_id="b0001",
        applicant_group=GENERAL_SCOPE,
        intake=intake,
        conditions=None,
        method="openrouter:test",
    )


# ---- recurring intake ----------------------------------------------------------------


def test_semester_heading_and_date_give_recurring_intake():
    d = doc("Winter semester", "Application period from June until July 15.")
    c = fill_recurring_intake(deadline("Application period from June until July 15."), d)
    assert c.intake == "winter semester (recurring)"
    assert validate(c, d) == "valid"


def test_quote_names_one_of_two_semesters_in_block():
    text = "Wintersemester: 15. Juli. Sommersemester: 15. Januar."
    d = doc("Bewerbungsfristen", text)
    c = fill_recurring_intake(deadline("Sommersemester: 15. Januar."), d)
    assert c.intake == "summer semester (recurring)"
    assert validate(c, d) == "valid"


@pytest.mark.parametrize(
    "heading, text, quote",
    [
        # a year in sight: the date belongs to a specific intake, never inferred
        ("Winter semester 2026/27", "Apply by July 15.", "Apply by July 15."),
        # no semester named
        ("Deadlines", "Apply by July 15.", "Apply by July 15."),
        # no day+month date
        ("Winter semester", "Results are announced in the portal.", "Results are announced in the portal."),
        # the quote itself covers both semesters
        (
            "Bewerbung",
            "1. Mai bis 15. Juni (Wintersemester) und 1. Dezember bis 15. Januar (Sommersemester)",
            "1. Mai bis 15. Juni (Wintersemester) und 1. Dezember bis 15. Januar (Sommersemester)",
        ),
    ],
)
def test_intake_left_empty_without_unambiguous_evidence(heading, text, quote):
    d = doc(heading, text)
    c = fill_recurring_intake(deadline(quote), d)
    assert c.intake is None
    assert validate(c, d) != "valid"


def test_stated_intake_and_other_fields_untouched():
    d = doc("Winter semester", "Apply by July 15.")
    given = deadline("Apply by July 15.", intake="winter semester 2026/27")
    assert fill_recurring_intake(given, d) is given
    fee = given.model_copy(update={"field": "tuition", "intake": None})
    assert fill_recurring_intake(fee, d) is fee


# ---- euro amounts ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, amounts",
    [
        ("tuition fees in the amount of EUR 1,500.- per semester", {"1500"}),
        ("a tuition fee of 1,500.00 euros per semester", {"1500"}),
        ("usually 4,000 or 6,000 euros per semester", {"4000", "6000"}),
        ("for Bachelor's programs : 2,300 euros or 3,400 euros", {"2300", "3400"}),
        ("a semester fee of €412,30 , which includes", {"412.30"}),
        ("Since winter semester 2017/18 ... a tuition fee of EUR 1,500", {"1500"}),
        ("The regular semester fee must be paid in addition.", set()),
    ],
)
def test_euro_amounts(text, amounts):
    assert euro_amounts(text) == {Decimal(a) for a in amounts}


# ---- conflicts -------------------------------------------------------------------------

PRIMARY = "snap-programme-page"


def member(cid, field, value, snapshot="snap-followup"):
    return ({"id": cid, "snapshot_id": snapshot}, {"field": field, "value": value})


def held(members):
    return {row["id"] for row, _ in Engine._conflict_holds(members, PRIMARY)}


def test_same_euro_amount_in_different_sentences_agrees():
    members = [
        member("a", "tuition", "obliged to pay tuition fees of EUR 1,500.- per semester"),
        member("b", "tuition", "international students pay 1,500 euros per semester"),
    ]
    assert held(members) == set()


def test_fee_text_without_amount_never_conflicts():
    members = [
        member("a", "semester_contribution", "a semester fee of €412,30 , which includes"),
        member("b", "semester_contribution", "All students currently pay a semester fee."),
    ]
    assert held(members) == set()


def test_programme_page_wins_over_disagreeing_followups():
    members = [
        member("p", "tuition", "for this degree program are 6,000 euros per semester", PRIMARY),
        member("f1", "tuition", "Master's degree programs: usually 4,000 or 6,000 euros"),
        member("f2", "tuition", "for Master's programs : 4,600 or 6,800 euros"),
        member("f3", "tuition", "Non-EU students pay EUR 6,000 per semester"),
    ]
    assert held(members) == {"f1", "f2"}


def test_programme_page_wins_for_text_fields():
    members = [
        member("p", "teaching_language", "English", PRIMARY),
        member("f", "teaching_language", "German C1 or English C1"),
    ]
    assert held(members) == {"f"}


def test_disagreement_on_the_programme_page_holds_everything():
    members = [
        member("p1", "duration_semesters", "4", PRIMARY),
        member("p2", "duration_semesters", "6", PRIMARY),
        member("f", "duration_semesters", "4"),
    ]
    assert held(members) == {"p1", "p2", "f"}


def test_followups_alone_still_conflict():
    members = [
        member("a", "tuition", "EUR 1,500 per semester"),
        member("b", "tuition", "Tuition fee for a second degree EUR 650.00"),
    ]
    assert held(members) == {"a", "b"}


# ---- applicant group stated in the quote ------------------------------------------------

from kb_pipeline.extract import fill_stated_group  # noqa: E402


def fee(quote, group=GENERAL_SCOPE, field="tuition"):
    return Claim(
        field=field,
        value=quote,
        quote=quote,
        location_id="b0001",
        applicant_group=group,
        intake=None,
        conditions=None,
        method="openrouter:test",
    )


@pytest.mark.parametrize(
    "quote, group",
    [
        (
            "The tuition fees for international students from third countries for this "
            "degree program are 6,000 euros per semester.",
            "international students from third countries",
        ),
        ("Costs: Semester fees , tuitions fees for Students from Non-EU Countries", "students from non-eu countries"),
        (
            "International students coming from outside of the EU to study at KIT are "
            "obliged to pay tuition fees in the amount of EUR 1,500.- per semester",
            "international students",
        ),
        (
            "international students who are not citizens of an EU/EEA country have to pay "
            "a tuition fee of EUR 1,500",
            "international students",
        ),
    ],
)
def test_group_copied_from_quote(quote, group):
    d = doc("Tuition fees", quote)
    c = fill_stated_group(fee(quote), d)
    assert c.applicant_group == group
    assert validate(c, d) == "valid"


def test_group_only_replaces_general_scope_on_fee_and_deadline_fields():
    quote = "International students pay EUR 1,500 per semester."
    stated = fee(quote, group="non-EU students")
    assert fill_stated_group(stated, doc("Fees", quote)) is stated
    req = fee(quote, field="requirement")
    assert fill_stated_group(req, doc("Fees", quote)) is req


def test_no_group_phrase_in_quote_leaves_claim_held():
    # the group is only in the heading: nothing in the quote to copy
    quote = "The fee is EUR 1,500 per semester."
    d = doc("Fees for international students", quote)
    c = fill_stated_group(fee(quote), d)
    assert c.applicant_group == GENERAL_SCOPE
    assert validate(c, d) == "APPLICANT_SCOPE_CONFLICT"
