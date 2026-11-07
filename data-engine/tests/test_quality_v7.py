"""Quality fixes after the run-5 analysis (rules-v7 / exact-blocks-v3 / regex-v4).

Fixtures are real rows from RUN5 (d601ad96...): tests/fixtures/run5_evidence_not_found.json
holds the 23 EVIDENCE_NOT_FOUND claims with the source blocks involved; other texts are
quoted from the same run.
"""

import json
from pathlib import Path

import pytest

from kb_pipeline.contracts import Claim, GENERAL_SCOPE
from kb_pipeline.engine import Engine
from kb_pipeline.extract import (
    canonical_title,
    classify,
    is_placeholder,
    validate,
    value_in_quote,
)
from kb_pipeline.grounding import ground
from kb_pipeline.normalize import filter_facts_for_level, normalize_claim, normalize_claims

GEN = GENERAL_SCOPE
CASES = {
    c["id"]: c
    for c in json.loads(
        (Path(__file__).parent / "fixtures" / "run5_evidence_not_found.json").read_text()
    )
}


def mk(**kw):
    kw.setdefault("intake", None)
    kw.setdefault("conditions", None)
    return Claim(**kw)


def blk(id, text, heading="Study", tag="p"):
    return {"id": id, "text": text, "heading": heading, "location": {"tag": tag}}


def regrade(case_id):
    case = CASES[case_id]
    blocks = case["blocks"]
    claim = Claim.model_validate(case["claim"])
    relevant = [b for b in blocks if classify(b) == "relevant"]
    grounded, action = ground(claim, relevant, source_blocks=blocks)
    doc = {"blocks": blocks}
    return grounded, action, [validate(g, doc) for g in grounded], doc


# ---- 1. EVIDENCE_NOT_FOUND ---------------------------------------------------------

# id -> (expected source block, cause)
RELOCATED = {
    # verbatim in another block; the block is over the 3000/4000 char retention limits
    "a05c2d23": ("b0019", "wrong location, oversized block"),
    "69576f65": ("b0019", "wrong location, oversized block"),
    "e5dbad65": ("b0019", "wrong location, oversized block"),
    "53dc78de": ("b0003", "wrong location, block > 4000 chars"),
    "65e3d6df": ("b0003", "wrong location, block > 4000 chars"),
    "80725554": ("b0003", "wrong location, block > 4000 chars"),
    # typography: LLM wrote U+2011 where the page has "-"
    "5da66440": ("b0018", "non-breaking hyphen"),
    "1b1de4d2": ("b0020", "non-breaking hyphen"),
    "c9d3e8c0": ("b0018", "non-breaking hyphen"),
    # PDF line-break hyphenation the model repaired ("ord- nung", "Appli- cations")
    "afce880a": ("b0002", "hyphenation"),
    "27cea012": ("b0002", "hyphenation"),
    "49433275": ("b0000", "hyphenation"),
    # trailing full stop added by the model + wrong location + block > 4000
    "4b0fc132": ("b0003", "trailing punctuation, wrong location"),
    # three identical "M.Sc. Computer Science" blocks; model cited a fourth id
    "e8ed612a": (None, "ambiguous duplicate blocks"),
}
# Not verbatim anywhere: elided/renumbered/invented text must stay rejected.
STAY_REJECTED = {
    "7a4c51de": "model dropped '(section 2 paragraph 1 clause 1)'",
    "0bd469ae": "model dropped '(section 2 paragraph 1 clause 1)'",
    "cd179cd0": "PDF footnote marker '1' dropped",
    "24046294": "footnote markers rewritten into a numbered list",
    "2919a97f": "quote spans a page break (two blocks)",
    "6c9200f1": "title invented from the target name",
    "6057c2e2": "title invented from the target name",
    "101b0ffd": "title invented from the target name",
    "bb35ad10": "title invented from the target name",
}


def test_all_23_cases_are_classified():
    assert set(CASES) == set(RELOCATED) | set(STAY_REJECTED)
    assert len(CASES) == 23


@pytest.mark.parametrize("case_id", sorted(RELOCATED))
def test_run5_claims_with_verbatim_evidence_are_grounded(case_id):
    expected_block, _ = RELOCATED[case_id]
    grounded, action, codes, doc = regrade(case_id)
    assert "EVIDENCE_NOT_FOUND" not in codes and "VALUE_NOT_GROUNDED" not in codes
    assert len(grounded) == 1
    text = {b["id"]: b["text"] for b in doc["blocks"]}
    g = grounded[0]
    assert " ".join(g.quote.split()) in text[g.location_id]  # still verbatim
    if expected_block:
        assert g.location_id == expected_block
    assert action and action["grounder"] == "exact-blocks-v3"


@pytest.mark.parametrize("case_id", sorted(STAY_REJECTED))
def test_run5_paraphrased_or_invented_quotes_stay_rejected(case_id):
    grounded, action, codes, _ = regrade(case_id)
    assert codes == ["EVIDENCE_NOT_FOUND"]
    assert action is None


@pytest.mark.parametrize("case_id", ["a05c2d23", "69576f65", "e5dbad65", "5da66440", "1b1de4d2", "c9d3e8c0"])
def test_regulation_clauses_end_up_not_a_fact_once_grounded(case_id):
    _, _, codes, _ = regrade(case_id)
    assert codes == ["NOT_A_FACT"]


def test_typographic_hyphen_and_quotes_match_on_both_sides():
    block = blk("b1", "The thesis is peer‑reviewed and the duration is 4 semesters. It’s “fine”.")
    claim = mk(
        field="duration_semesters",
        value="4",
        quote="peer-reviewed and the duration is 4 semesters. It's \"fine\".",
        location_id="b9",
        applicant_group=GEN,
    )
    grounded, action = ground(claim, [block])
    assert grounded[0].location_id == "b1" and action


def test_paraphrase_is_not_accepted():
    block = blk("b1", "The programme lasts four semesters in total.")
    claim = mk(
        field="duration_semesters",
        value="4",
        quote="The programme takes 4 semesters in total.",
        location_id="b1",
        applicant_group=GEN,
    )
    grounded, action = ground(claim, [block])
    assert grounded == [claim] and action is None


# ---- 2. decimal-comma money --------------------------------------------------------

SAARLAND_FEE = "Before enrolling or re-registering, all students must currently pay a semester fee of €412,30 , which includes the student-services payment, the administrative charge and the General Student Committee fees. The semester fee also covers the cost of the nationwide student travel ticket . It is valid throughout Germany to the same extent as the 'Deutschlandticket'."


@pytest.mark.parametrize(
    "value,quote",
    [
        ("€412.30", "a semester fee of €412,30 , which includes"),
        ("412.30", "a semester fee of €412,30 ."),
        ("412.3", "fee of 412,30 € per semester"),
        ("€1500", "tuition of 1.500 € per semester"),
        ("1,500", "tuition of €1.500 per semester"),
        ("1.500", "fee: EUR 1,500 per year"),
        ("1500.00", "tuition €1,500"),
    ],
)
def test_money_values_equivalent_across_separators(value, quote):
    assert value_in_quote("semester_contribution", value, quote)


@pytest.mark.parametrize(
    "value,quote",
    [
        ("€412.30", "a semester fee of €412,31 ."),
        ("€150", "tuition of 1.500 € per semester"),
        ("€1.5", "tuition of 1.500 € per semester"),
    ],
)
def test_money_equivalence_does_not_accept_different_amounts(value, quote):
    assert not value_in_quote("tuition", value, quote)


def test_money_equivalence_is_limited_to_money_fields():
    assert not value_in_quote("requirement", "412.30", "fee €412,30")


def test_saarland_semester_fee_claim_is_valid_and_yields_fee_fact():
    doc = {"blocks": [blk("b0008", SAARLAND_FEE, heading="Semester fee")]}
    claim = mk(
        field="semester_contribution",
        value="€412.30",
        quote=SAARLAND_FEE,
        location_id="b0008",
        applicant_group=GEN,
    )
    assert validate(claim, doc) == "valid"
    facts = normalize_claim("c1", claim)
    assert [(f.kind, f.data.model_dump()) for f in facts] == [
        (
            "fee_amount",
            {
                "amount_eur": "412.30",
                "period": "per_semester",
                "fee_type": "semester_contribution",
                "applicant_group": GEN,
            },
        )
    ]


# ---- 3. Passau semester fee -------------------------------------------------------

PASSAU_FEE = "For summer semester 2027, the fee is € 134 . Of this, € 87 go to the Student Services Association ( Studierendenwerk ), which operate the refectory, cafeterias and halls of residence, among other things. The remaining € 47 pay for the semester bus pass that is included with your CampusCard (student ID card) and that permits you to use the buses in town at no extra cost until the valid-to date printed on your card."


def test_passau_fee_is_total_134_not_the_87_component():
    claim = mk(
        field="semester_contribution",
        value=PASSAU_FEE,
        quote=PASSAU_FEE,
        location_id="b0066",
        applicant_group=GEN,
    )
    facts = normalize_claim("c1", claim)
    assert [(f.kind, f.data.model_dump()) for f in facts] == [
        (
            "fee_amount",
            {
                "amount_eur": "134",
                "period": "per_semester",
                "fee_type": "semester_contribution",
                "applicant_group": GEN,
            },
        )
    ]
    # the stated term travels with the evidence
    assert facts[0].evidence_text == "For summer semester 2027, the fee is € 134"
    assert facts[0].grounded_in_quote(PASSAU_FEE)


def test_fee_is_without_semester_context_stays_unemitted():
    claim = mk(
        field="requirement",
        value="x",
        quote="Please note the fee is € 50 for the late registration form.",
        location_id="b0",
        applicant_group=GEN,
    )
    assert normalize_claim("c1", claim) == []


# ---- 4. placeholders ---------------------------------------------------------------


@pytest.mark.parametrize(
    "value", ["not established", "Not established", "not established.", "Not mentioned", "not listed"]
)
@pytest.mark.parametrize("field", ["tuition", "semester_contribution"])
def test_not_established_is_a_placeholder(field, value):
    assert is_placeholder(value, field)
    doc = {"blocks": [blk("b0000", "Intro text.")]}
    claim = mk(
        field=field, value=value, quote=value, location_id="b0000", applicant_group=GEN
    )
    assert validate(claim, doc) == "NOT_A_FACT"


def test_not_applicable_tuition_stays_a_real_value():
    # "Tuition fees Not applicable" is a statement about the programme, kept since run 4.
    assert not is_placeholder("Not applicable", "tuition")


# ---- 5. title variants -------------------------------------------------------------


@pytest.mark.parametrize(
    "a,b",
    [
        ("Master of Science Informatik/Computer Science", "Computer Science M.Sc."),
        ("Master of Science Informatik / Computer Science", "Computer Science (M.Sc.)"),
        ("Master of Science Informatik/Computer Science", "M.Sc. Informatik"),
        ("Master’s Degree Programme in Computer Science", "Computer Science (M.Sc.)"),
        ("Bachelor's Programme in Computer Science", "B.Sc. Computer Science"),
        ("Studiengang Informatik (M.Sc.)", "Informatik M.Sc."),
        ("Master's Degree Programme in Computer Science", "Computer Science"),
    ],
)
def test_run5_title_variants_agree(a, b):
    members = [(None, {"field": "programme_title", "value": v}) for v in (a, b)]
    assert not Engine._values_disagree(members)


@pytest.mark.parametrize(
    "a,b",
    [
        ("Master of Science Informatik/Computer Science", "Data Science M.Sc."),
        ("Master’s Degree Programme in Computer Science", "Data Science (M.Sc.)"),
        ("Master’s Degree Programme in Computer Science", "Computer Science B.Sc."),
        ("Master of Science Informatik/Computer Science", "Computer Science B.Sc."),
        ("Computer Science", "Computer Science and Engineering"),
    ],
)
def test_title_differences_still_conflict(a, b):
    members = [(None, {"field": "programme_title", "value": v}) for v in (a, b)]
    assert Engine._values_disagree(members)


def test_canonical_title_strips_programme_phrases():
    words, levels = canonical_title("Master’s Degree Programme in Computer Science")
    assert words == "computer science" and levels == frozenset({"master"})


# ---- 6. fee text filed under tuition -----------------------------------------------

FREIBURG_FEES = "German and EU nationals 103 € to support the services offered by Studierendenwerk (SWFR) 80 € administrative fee 7 € to support the student council Altogether 190 € per semester to be paid to the university. Non-EU nationals 1500 € tuition fees 103 € to support the services offered by Studierendenwerk (SWFR) 80 € administrative fee 7 € to support the student council Altogether 1690 € per semester to be paid to the university."
FREIBURG_VALUE = "German and EU nationals 103 € to support the services offered by Studierendenwerk (SWFR) 80 € administrative fee 7 € to support the student council Altogether 190 € per semester to be paid to the university."


def _tuition(value, quote=FREIBURG_FEES, group="German and EU nationals"):
    doc = {"blocks": [blk("b0015", quote, heading="Fees")]}
    claim = mk(
        field="tuition", value=value, quote=quote, location_id="b0015", applicant_group=group
    )
    return validate(claim, doc)


def test_semester_fee_text_under_tuition_is_held():
    assert _tuition(FREIBURG_VALUE) == "NOT_A_FACT"


def test_same_text_under_semester_contribution_is_not_affected():
    doc = {"blocks": [blk("b0015", FREIBURG_FEES, heading="Fees")]}
    claim = mk(
        field="semester_contribution",
        value=FREIBURG_VALUE,
        quote=FREIBURG_FEES,
        location_id="b0015",
        applicant_group="German and EU nationals",
    )
    assert validate(claim, doc) == "valid"


def test_real_tuition_value_after_a_tuition_label_is_kept():
    # rules-v6 row 18f326d3: the value is what follows "tuition fees" in the quote
    value = "103 € to support the services offered by Studierendenwerk (SWFR) 80 € administrative fee 7 € to support the student council Altogether 1690 € per semester to be paid to the university."
    assert _tuition(value, group="Non-EU nationals") == "valid"
    assert _tuition("1500 € tuition fees", group="Non-EU nationals") == "valid"


def test_freiburg_conflict_between_semester_fee_text_and_placeholder_disappears():
    # tuition rows: the fee-text claim (held) and 'not established' (placeholder)
    held = _tuition(FREIBURG_VALUE)
    assert held == "NOT_A_FACT"
    assert is_placeholder("not established", "tuition")


# ---- 7. required_degree on bachelor programmes -------------------------------------

PASSAU_MASTER_PREREQ = "The fundamental prerequisite for joining a Master's programme is a completed undergraduate degree. Please look up the specific requirements for the Master's programme of your choice in the 'Academic Requirements' section of its web page."


def test_undergraduate_degree_fact_is_dropped_on_bachelor_entity():
    claim = mk(
        field="requirement",
        value=PASSAU_MASTER_PREREQ,
        quote=PASSAU_MASTER_PREREQ,
        location_id="b0076",
        applicant_group=GEN,
    )
    facts = normalize_claims([("c1", claim)])
    assert [f.data.level for f in facts if f.kind == "required_degree"] == ["bachelor"]
    assert [f for f in filter_facts_for_level(facts, "bachelor") if f.kind == "required_degree"] == []
    # a master programme keeps it
    assert filter_facts_for_level(facts, "master") == facts


def test_school_leaving_degree_survives_on_bachelor_entity():
    claim = mk(
        field="requirement",
        value="x",
        quote="The central requirement for an application is the proof of a university entrance qualification enabling for direct access to undergraduate degree programme at German universities.",
        location_id="b0",
        applicant_group=GEN,
    )
    facts = filter_facts_for_level(normalize_claims([("c1", claim)]), "bachelor")
    assert [f.data.level for f in facts if f.kind == "required_degree"] == ["school_leaving"]


@pytest.mark.parametrize(
    "text",
    [
        "The undergraduate degree programme lasts six semesters and requires proof of a university entrance qualification.",
        "Der undergraduate Studiengang Informatik erfordert einen Nachweis der Hochschulreife.",
    ],
)
def test_undergraduate_degree_programme_is_not_a_required_degree(text):
    claim = mk(
        field="requirement", value=text, quote=text, location_id="b0", applicant_group=GEN
    )
    assert [f.data.level for f in normalize_claim("c1", claim) if f.kind == "required_degree"] == [
        "school_leaving"
    ]


# ---- title claims never feed the fact normaliser -----------------------------------


def test_title_claim_with_whole_page_quote_yields_no_facts():
    # RUN5 9c768b72: valid once the title variants agree; its quote is the regulation
    # preamble block ("... passed by the university senate on 30th March 2022 ...").
    claim = Claim.model_validate(
        json.loads(
            (Path(__file__).parent / "fixtures" / "run5_freiburg_title_claim.json").read_text()
        )
    )
    assert claim.field == "programme_title" and "30th March 2022" in claim.quote
    assert normalize_claim("c1", claim) == []


# ---- versions ---------------------------------------------------------------------


def test_versions_bumped():
    from kb_pipeline.acquire import PARSER_VERSION
    from kb_pipeline.extract import EXTRACTOR_VERSION
    from kb_pipeline.grounding import GROUNDING_VERSION
    from kb_pipeline.structured import NORMALIZER_VERSION

    assert (EXTRACTOR_VERSION, GROUNDING_VERSION, NORMALIZER_VERSION) == (
        "rules-v7",
        "exact-blocks-v3",
        "regex-v4",
    )
    assert PARSER_VERSION == "blocks-v2"
