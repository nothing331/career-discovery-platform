"""Regex normaliser: real crawled fixtures plus German synthetic cases."""

import pytest
from pydantic import ValidationError

from kb_pipeline.contracts import Claim
from kb_pipeline.normalize import normalize_claim, normalize_claims
from kb_pipeline.structured import (
    NORMALIZER_VERSION,
    ApplicationWindow,
    FeeAmount,
    LanguageTest,
    StructuredFact,
)

GEN = "general (no specific applicant group stated)"

FIXTURES = {
    1: (
        "requirement",
        "olympiad track You can provide a documentation of having successfully participated in a recognized science/informatics/mathematics olympiad, and results from an English test (IELTS or TOEFL or another accepted test result).",
    ),
    2: ("requirement", "English language requirements CEFR: B2 advanced (recommended)"),
    3: (
        "requirement",
        "English language requirements Level C1 (a MOI (Medium of Instruction) is not accepted, see FAQ )",
    ),
    4: (
        "requirement",
        "German : You should provide proof of German language skills equivalent to level B2 CEFR .",
    ),
    5: (
        "requirement",
        "Even if you plan to choose only modules taught in English, you also need German language skills at level A1 CEFR (beginner's level) or higher. If you do not meet this requirement at the time of application, you will have to complete a beginner's German course and provide a certificate by the end of your first year of study.",
    ),
    6: (
        "requirement",
        "English language proficiency : The following English language certificates are accepted: Academic IELTS, including IELTS Online Academic (minimum 7.0), TOEFL, including TOEFL ibT home edition and TOEFL Essentials (minimum ibT score 95 or 5.0 according to the new TOEFL scale 2026), Cambridge CAE or CPE, Pearson PTE Academic (minimum score 76), telc University, TOEIC, OOPT. Only native speakers from the USA, the UK, Australia, New Zealand and Canada or students having completed their bachelor's degree in one of these countries are exempted from submitting a test score. A confirmation that the medium of instruction at your university was English is not sufficient.",
    ),
    7: (
        "requirement",
        "To apply, you need to have an undergraduate university degree in computer science or a related discipline with a computer science component of at least 110 ECTS credits . You must be ranked among the best 70% of graduates within your cohort or the final grade for your first degree was 2.7 or better (according to the German grading scale ; foreign grades will be converted once we receive your application).",
    ),
    8: (
        "deadline",
        "From the middel of December, applications for the winter semester can be submitted via the SIC application portal, which you can find here .",
    ),
    9: ("deadline", "1 April - 31 May (applications via uni-assist e.V.)"),
    10: (
        "requirement",
        "APS certificate (only for applicants who have studied in China, India or Vietnam). Please note: It is not possible to submit the APS certificate after the application deadline.",
    ),
    11: (
        "requirement",
        "The English-language bachelor's program is subject to an admission restriction and is only offered with a start date in the winter semester. The regular application deadline is July 15 . An optional application for early admission is possible by January 15 and by June 15 . The central requirement for an application is the proof of a university entrance qualification enabling for direct access to undergraduate degree programme at German universities.",
    ),
    12: (
        "deadline",
        "Application deadline For winter semester: Regular deadline: 15 July Deadline interview track: 15 June",
    ),
    13: (
        "deadline",
        "Students can begin the M.Sc. programme at the beginning of the summer or winter semester. Applications should normally be received by 15 May for students seeking to begin studying in the winter semester and by 15 November for students looking to start their studies in summer. ...",
    ),
    14: (
        "deadline",
        "Application periods: April 15 - May 31 (non-EU nationals), April 15 - July 15 (EU nationals) for the winter semester. November 1 - December 15 (non-EU nationals), November 1 - January 15 (EU nationals) for the summer semester",
    ),
    15: (
        "tuition",
        "German and EU nationals 103 € to support the services offered by Studierendenwerk (SWFR) 80 € administrative fee 7 € to support the student council Altogether 190 € per semester to be paid to the university. Non-EU nationals 1500 € tuition fees 103 € to support the services offered by Studierendenwerk (SWFR) 80 € administrative fee 7 € to support the student council Altogether 1690 € per semester to be paid to the university.",
    ),
    16: (
        "tuition",
        "At the University of Passau, there a no tuition fees . However, students do pay a semester fee .",
    ),
    17: (
        "requirement",
        "Admissions: First semester: without special admission requirements (admission-free) Higher semesters: with special admission requirements according to the admission regulations",
    ),
    18: (
        "requirement",
        "Bachelor's degree in computer science, math, or in a closely related field. Very good command of mathematics ...",
    ),
    19: (
        "requirement",
        "Very good German language skills (level C1 of the European reference framework required for application already)",
    ),
    20: ("deadline", "Bewerbungsfrist für das Wintersemester: 15. Juli"),
    21: ("requirement", "Sprachnachweis Deutsch: DSH-2 oder TestDaF 4x4"),
    22: ("requirement", "zulassungsbeschränkt (NC)"),
    23: ("semester_contribution", "Semesterbeitrag: 158,50 €"),
    24: ("tuition", "Not applicable"),
    25: ("tuition", "See current fee structure"),
}


def claim(field, quote, group=GEN):
    return Claim(
        field=field,
        value=quote[:60],
        quote=quote,
        location_id="loc",
        applicant_group=group,
        intake=None,
        conditions=None,
    )


def run(n, group=GEN):
    field, quote = FIXTURES[n]
    return normalize_claim(f"c{n}", claim(field, quote, group))


def brief(facts):
    """(kind, data without Nones, evidence) tuples for readable asserts."""
    return [(f.kind, f.data.model_dump(exclude_none=True)) for f in facts]


def win(season, end, start=None, group=GEN, year=None):
    d = {"season": season, "end": end, "applicant_group": group}
    if start:
        d["start"] = start
    if year:
        d["year"] = year
    return ("application_window", d)


def test_olympiad_track_names_ielts_only_without_score():
    # plain "TOEFL" is ambiguous (iBT vs Essentials), so it is not emitted
    assert brief(run(1)) == [
        ("language_test", {"test": "IELTS", "language": "english"})
    ]


def test_cefr_recommended_vs_required():
    assert brief(run(2)) == [
        (
            "language_level",
            {"language": "english", "cefr": "B2", "strength": "recommended"},
        )
    ]
    assert brief(run(3)) == [
        (
            "language_level",
            {"language": "english", "cefr": "C1", "strength": "required"},
        )
    ]


def test_should_provide_proof_stays_required():
    assert brief(run(4)) == [
        ("language_level", {"language": "german", "cefr": "B2", "strength": "required"})
    ]
    assert brief(run(19)) == [
        ("language_level", {"language": "german", "cefr": "C1", "strength": "required"})
    ]


def test_german_a1_even_for_english_modules():
    assert brief(run(5)) == [
        ("language_level", {"language": "german", "cefr": "A1", "strength": "required"})
    ]


def test_english_certificate_list():
    got = {(f.data.test, f.data.min_score) for f in run(6)}
    assert got == {
        ("IELTS", "7.0"),
        (
            "TOEFL_IBT",
            "95",
        ),  # "5.0 according to the new TOEFL scale" is ambiguous: not used
        ("TOEFL_ESSENTIALS", None),
        ("PTE", "76"),
        ("CAMBRIDGE", None),
        ("TELC", None),  # language inferred from the English-only quote
    }
    assert all(
        f.kind == "language_test" for f in run(6)
    )  # TOEIC/OOPT skipped, no degree fact


def test_degree_grade_alternative_and_ects():
    facts = {f.kind: f for f in run(7)}
    assert facts["min_grade"].data.model_dump() == {
        "value": "2.7",
        "scale": "DE_1_TO_4",
        "alternative": "ranked among the best 70% of graduates within your cohort",
    }
    assert facts["subject_ects_min"].data.model_dump() == {
        "min_ects": 110,
        "subject": "computer science",
    }
    assert facts["required_degree"].data.model_dump() == {
        "level": "bachelor",
        "subjects": ["computer science", "related discipline"],
    }


def test_portal_and_uni_assist_routes():
    assert brief(run(8)) == [("application_route", {"route": "university_portal"})]
    assert ("application_route", {"route": "uni_assist"}) in brief(run(9))


def test_window_with_uni_assist():
    assert brief(run(9)) == [
        ("application_route", {"route": "uni_assist"}),
        win("unknown", "31-05", "01-04"),
    ]


def test_aps_countries():
    assert brief(run(10)) == [
        ("aps_required", {"required": True, "countries": ["China", "India", "Vietnam"]})
    ]


def test_restriction_window_degree_and_skipped_early_dates():
    got = brief(run(11))
    assert (
        "restricted_admission",
        {"restricted": True, "basis": "subject to an admission restriction"},
    ) in got
    assert ("required_degree", {"level": "school_leaving", "subjects": []}) in got
    windows = [d for k, d in got if k == "application_window"]
    # optional early-admission dates (January 15 / June 15) must not appear
    assert windows == [{"season": "winter", "end": "15-07", "applicant_group": GEN}]


def test_regular_deadline_under_winter_skips_interview_track():
    assert brief(run(12)) == [win("winter", "15-07")]


def test_by_dates_per_season():
    assert brief(run(13)) == [win("winter", "15-05"), win("summer", "15-11")]


def test_four_windows_per_group_and_season():
    assert brief(run(14)) == [
        win("winter", "31-05", "15-04", "non-EU nationals"),
        win("winter", "15-07", "15-04", "EU nationals"),
        win("summer", "15-12", "01-11", "non-EU nationals"),
        win("summer", "15-01", "01-11", "EU nationals"),
    ]


def test_fee_table_per_group():
    got = brief(run(15))
    assert got == [
        (
            "fee_amount",
            {
                "amount_eur": "190",
                "period": "per_semester",
                "fee_type": "total",
                "applicant_group": "German and EU nationals",
            },
        ),
        (
            "fee_amount",
            {
                "amount_eur": "1500",
                "period": "per_semester",
                "fee_type": "tuition",
                "applicant_group": "Non-EU nationals",
            },
        ),
        (
            "fee_amount",
            {
                "amount_eur": "1690",
                "period": "per_semester",
                "fee_type": "total",
                "applicant_group": "Non-EU nationals",
            },
        ),
    ]


def test_explicit_no_tuition_is_zero_but_semester_fee_without_amount_is_nothing():
    facts = run(16)
    assert brief(facts) == [
        (
            "fee_amount",
            {"amount_eur": "0", "fee_type": "tuition", "applicant_group": GEN},
        )
    ]
    assert facts[0].evidence_text == "no tuition fees"
    assert facts[0].data.period is None


def test_mixed_admission_statement_is_ambiguous():
    assert run(17) == []


def test_bachelor_degree_subjects():
    assert brief(run(18)) == [
        (
            "required_degree",
            {
                "level": "bachelor",
                "subjects": ["computer science", "math", "related field"],
            },
        )
    ]


def test_german_synthetic():
    assert brief(run(20)) == [win("winter", "15-07")]
    assert brief(run(21)) == [
        ("language_test", {"test": "DSH", "min_score": "2", "language": "german"}),
        (
            "language_test",
            {"test": "TESTDAF", "min_score": "4x4", "language": "german"},
        ),
    ]
    assert brief(run(22)) == [
        (
            "restricted_admission",
            {"restricted": True, "basis": "zulassungsbeschränkt (NC)"},
        )
    ]
    assert brief(run(23)) == [
        (
            "fee_amount",
            {
                "amount_eur": "158.50",
                "period": "per_semester",
                "fee_type": "semester_contribution",
                "applicant_group": GEN,
            },
        )
    ]


@pytest.mark.parametrize("n", [24, 25])
def test_not_applicable_fee_text_emits_nothing(n):
    assert run(n) == []


@pytest.mark.parametrize(
    "field,quote,expected",
    [
        (
            "deadline",
            "Bewerbungsfrist: 1. April bis 31. Mai",
            win("unknown", "31-05", "01-04"),
        ),
        ("deadline", "Wintersemester: 15.07.2025", win("winter", "15-07", year=2025)),
        ("deadline", "Sommersemester: 15.01.", win("summer", "15-01")),
        (
            "deadline",
            "Application deadline for the summer semester: 15th of January",
            win("summer", "15-01"),
        ),
        (
            "deadline",
            "Applications between 1 March and 15 April for the winter term",
            win("winter", "15-04", "01-03"),
        ),
    ],
)
def test_window_formats(field, quote, expected):
    assert brief(normalize_claim("c", claim(field, quote))) == [expected]


@pytest.mark.parametrize(
    "quote",
    [
        "The winter semester starts on 1 October.",
        "Lectures begin 14 October",
        "Application deadline: to be announced",
        "Early application deadline: 15 January",
    ],
)
def test_no_window_from_non_deadlines(quote):
    assert [
        f
        for f in normalize_claim("c", claim("deadline", quote))
        if f.kind == "application_window"
    ] == []


def test_fee_formats_and_inherit_requires_arithmetic():
    f = normalize_claim("c", claim("tuition", "Tuition fees: 1.500,00 EUR per year"))
    assert brief(f) == [
        (
            "fee_amount",
            {
                "amount_eur": "1500",
                "period": "per_year",
                "fee_type": "tuition",
                "applicant_group": GEN,
            },
        )
    ]
    # components that do not sum to the total: tuition has no period of its own -> nothing
    f = normalize_claim(
        "c",
        claim(
            "tuition",
            "1500 € tuition fees 103 € social fee Altogether 2000 € per semester",
        ),
    )
    assert [x.data.fee_type for x in f] == ["total"]
    # unlabeled amount in another fee context is not a tuition fee
    assert (
        normalize_claim("c", claim("tuition", "Application fee 75 € per application"))
        == []
    )


def test_grade_scale_and_foreign_grades():
    f = normalize_claim("c", claim("requirement", "Abschlussnote mindestens 2,5"))
    assert brief(f) == [("min_grade", {"value": "2.5", "scale": "DE_1_TO_4"})]
    f = normalize_claim("c", claim("requirement", "A GPA of 3.2 or higher is required"))
    assert brief(f) == [("min_grade", {"value": "3.2", "scale": "UNKNOWN"})]
    assert (
        normalize_claim("c", claim("requirement", "The programme lasts 2.5 years"))
        == []
    )


def test_cefr_range_is_ambiguous_and_aps_negation():
    assert (
        normalize_claim(
            "c", claim("requirement", "German language skills at level B2 or C1")
        )
        == []
    )
    assert (
        normalize_claim("c", claim("requirement", "No APS certificate is needed")) == []
    )
    assert (
        normalize_claim("c", claim("requirement", "Not via uni-assist but directly"))
        == []
    )


def test_all_evidence_is_verbatim_substring_and_method_set():
    for n, (field, quote) in FIXTURES.items():
        for fact in run(n):
            assert fact.grounded_in_quote(quote), (n, fact.evidence_text)
            assert fact.method == NORMALIZER_VERSION == "regex-v4"
            assert fact.evidence_claim_ids == [f"c{n}"]


def test_dedupe_merges_claim_ids():
    field, quote = FIXTURES[14]
    one = claim(field, quote)
    facts = normalize_claims(
        [("a", one), ("b", one), ("c", claim("deadline", "Wintersemester: 15. Juli"))]
    )
    assert len(facts) == 5
    merged = [
        f
        for f in facts
        if f.data.applicant_group == "EU nationals" and f.data.season == "winter"
    ]
    assert merged[0].evidence_claim_ids == ["a", "b"]
    assert [f.evidence_claim_ids for f in facts[-1:]] == [["c"]]


def test_custom_normalizer_plugs_in():
    class Fixed:
        name = "llm-test"

        def normalize(self, claim_id, claim):
            return [
                StructuredFact(
                    kind="restricted_admission",
                    data={"restricted": True, "basis": "NC"},
                    evidence_claim_ids=[claim_id],
                    evidence_text="NC (restricted)",
                    method=self.name,
                )
            ]

    facts = normalize_claims(
        [("x", claim("requirement", "NC (restricted)"))], normalizers=[Fixed()]
    )
    assert facts[0].method == "llm-test"


def test_model_rejects_score_not_in_evidence():
    with pytest.raises(ValidationError, match="not in evidence_text"):
        StructuredFact(
            kind="language_test",
            data=LanguageTest(test="IELTS", min_score="6.5", language="english"),
            evidence_claim_ids=["c"],
            evidence_text="IELTS (minimum 7.0)",
        )
    with pytest.raises(ValidationError):
        StructuredFact(
            kind="fee_amount",
            data=FeeAmount(
                amount_eur="190",
                period="per_semester",
                fee_type="total",
                applicant_group="g",
            ),
            evidence_claim_ids=["c"],
            evidence_text="Altogether 1900 € per semester",
        )
    with pytest.raises(ValidationError):
        StructuredFact(
            kind="application_window",
            data=ApplicationWindow(season="winter", end="16-07", applicant_group="g"),
            evidence_claim_ids=["c"],
            evidence_text="15 July",
        )


def test_model_rejects_kind_mismatch_missing_ids_and_extra_fields():
    data = LanguageTest(test="IELTS", language="english")
    with pytest.raises(ValidationError):
        StructuredFact(
            kind="aps_required",
            data=data,
            evidence_claim_ids=["c"],
            evidence_text="IELTS",
        )
    with pytest.raises(ValidationError):
        StructuredFact(
            kind="language_test",
            data=data,
            evidence_claim_ids=[],
            evidence_text="IELTS",
        )
    with pytest.raises(ValidationError):
        StructuredFact(
            kind="language_test",
            data=data,
            evidence_claim_ids=["c"],
            evidence_text="IELTS",
            junk=1,
        )
    with pytest.raises(ValidationError):
        FeeAmount(amount_eur="190", period=None, fee_type="total", applicant_group="g")


def test_json_round_trip_picks_model_by_kind():
    fact = run(10)[0]
    again = StructuredFact.model_validate(fact.model_dump(mode="json"))
    assert again == fact
