"""blocks-v5 key facts: <dl> rows, heading + value boxes and label + value boxes become
blocks under new ids, while every blocks-v4 block keeps its id, text and heading."""

import json
from dataclasses import replace
from decimal import Decimal

import pytest

from kb_pipeline.acquire import core_blocks, parse
from kb_pipeline.contracts import Claim, Target
from kb_pipeline.extract import rule_claims

URL = "https://university.example/cs"


FILLER = "<p>A synthetic programme page used only by the parser tests in this file.</p>"


def blocks(html):
    return parse(html.replace("</main>", FILLER + "</main>").encode(), "text/html", URL)["blocks"]


def extras(html):
    core = core_blocks(blocks(html))
    return [(b["id"], b["location"]["tag"], b["text"]) for b in blocks(html) if b not in core]


RWTH = (
    "<main><h1>Computer Science B.Sc.</h1><h2>Key Info</h2><h3>Basic Information</h3>"
    "<dl><dt>Degree</dt><dd>Bachelor of Science</dd>"
    "<dt>Standard Period of Studies</dt><dd>6 semesters</dd>"
    "<dt>ECTS Credits</dt><dd>180<span>Further Information: ECTS are credit points.</span></dd>"
    "<dt>Language</dt><dd>German and English</dd></dl>"
    "<p>Admission requires a school leaving certificate.</p></main>"
)
STUTTGART = (
    "<main><h1>Informatik B.Sc.</h1>"
    '<div class="fact"><h3>REGELSTUDIENZEIT</h3><div class="value"> 6 Semester</div></div>'
    '<div class="fact"><h3>UNTERRICHTSSPRACHE</h3><div class="value">Deutsch</div></div>'
    "<p>Informatik ist eine zentrale Grundlagenwissenschaft.</p></main>"
)
BONN = (
    "<main><h1>Computer Science (M.Sc.)</h1><p>Intro text for the programme.</p>"
    '<div class="keyfact"><label><span>Language of instruction</span><a title="i"></a>'
    "</label><span>English</span><br/></div>"
    '<div class="keyfact"><label><span>Standard period of study</span></label>'
    "<span>4 Semester</span></div></main>"
)


def test_dl_rows_are_term_plus_values():
    assert extras(RWTH) == [
        ("b0002.1", "tr", "Degree Bachelor of Science"),
        ("b0002.2", "tr", "Standard Period of Studies 6 semesters"),
        ("b0002.3", "tr", "ECTS Credits 180 Further Information: ECTS are credit points."),
        ("b0002.4", "tr", "Language German and English"),
    ]


def test_heading_and_value_box_is_one_row():
    rows = [t for _, tag, t in extras(STUTTGART) if tag == "tr"]
    assert rows == ["REGELSTUDIENZEIT 6 Semester", "UNTERRICHTSSPRACHE Deutsch"]


def test_label_and_value_box_is_one_row():
    rows = [t for _, tag, t in extras(BONN) if tag == "tr"]
    assert rows == ["Language of instruction English", "Standard period of study 4 Semester"]


def test_dt_dd_pairs_inside_a_list_with_links():
    html = (
        "<main><h1>Informatik</h1><dl><dt>Studiensprache</dt><dd>Deutsch</dd>"
        "<dt>Links</dt><dd><ul><li><a href='/x'>Modulhandbuch</a></li></ul></dd></dl></main>"
    )
    assert ("b0000.1", "tr", "Studiensprache Deutsch") in extras(html)


@pytest.mark.parametrize("html", [RWTH, STUTTGART, BONN])
def test_core_blocks_are_numbered_as_before(html):
    core = core_blocks(blocks(html))
    assert [b["id"] for b in core] == [f"b{i:04d}" for i in range(len(core))]
    assert all("source" not in b["location"] for b in core)


def test_loose_text_never_moves_core_ids():
    html = (
        "<main><h1>T</h1><div>Loose intro words</div><p>First paragraph text.</p>"
        "<div><span>More loose words</span></div><p>Second paragraph text.</p></main>"
    )
    got = [(b["id"], b["text"]) for b in blocks(html)]
    assert got == [
        ("b0000", "T"),
        ("b0000.1", "Loose intro words"),
        ("b0001", "First paragraph text."),
        ("b0001.1", "More loose words"),
        ("b0002", "Second paragraph text."),
        ("b0003", "A synthetic programme page used only by the parser tests in this file."),
    ]


# ---- rules on key-fact rows ---------------------------------------------------------

TARGET = Target(
    id="x-bsc",
    institution="X",
    programme="Computer Science",
    level="bachelor",
    url=URL,
    allowed_hosts=["university.example"],
)


def facts(html):
    doc = parse(html.replace("</main>", FILLER + "</main>").encode(), "text/html", URL)
    return {(c.field, c.value) for c in rule_claims(doc, TARGET) if c.field != "programme_title"}


def test_rules_read_key_fact_rows():
    assert {
        ("duration_semesters", "6"),
        ("ects", "180"),
        ("teaching_language", "German and English"),
    } <= facts(RWTH)
    assert {("duration_semesters", "6"), ("teaching_language", "Deutsch")} <= facts(STUTTGART)
    assert {("duration_semesters", "4"), ("teaching_language", "English")} <= facts(BONN)


@pytest.mark.parametrize(
    "row",
    [
        "Language requirements B2 level certificate",
        "Language courses Offered every semester",
        "ECTS Credits per module vary",
    ],
)
def test_rules_skip_rows_that_are_not_the_fact(row):
    html = f"<main><h1>Informatik</h1><dl><dt>{row.split(' ', 1)[0]}</dt><dd>{row.split(' ', 1)[1]}</dd></dl></main>"
    assert not {f for f, _ in facts(html)} & {"teaching_language", "ects"}


# ---- model requests and carry-over --------------------------------------------------


class _Recorder:
    job_id = None

    def __init__(self):
        self.calls = []

    def close(self):
        pass

    def extract(self, blocks, target, *, offline=False):
        self.calls.append([b["id"] for b in blocks])
        return []


def test_new_blocks_go_in_a_separate_model_request(settings, monkeypatch):
    import kb_pipeline.engine as engine_module
    from kb_pipeline.engine import Engine
    from test_followups_integration import site

    recorder = _Recorder()
    monkeypatch.setattr(engine_module, "extractor", lambda *a, **k: recorder)
    cfg = replace(
        settings,
        provider="groq",
        model="openai/gpt-oss-20b",
        fallback_model="",
        api_key="synthetic-key",
        input_rate=Decimal(".075"),
        output_rate=Decimal(".30"),
    )
    client, _ = site({"/cs": RWTH.encode()})
    e = Engine(cfg, fetch_client=client, sleep=lambda _: None)
    target = TARGET.model_copy(update={"follow_links": False})
    e.work(e.enqueue(targets=[target], llm=True))
    core_call, extra_call = recorder.calls
    assert all("." not in i for i in core_call)
    assert extra_call and all("." in i for i in extra_call)


def test_evidence_ignores_new_key_fact_blocks(settings, tmp_path):
    from kb_pipeline.knowledge import _evidence_hash

    class Store:
        directory = tmp_path

    v5 = parse(RWTH.encode(), "text/html", URL)
    v4 = {"blocks": core_blocks(v5["blocks"])}
    for name, doc in (("new", v5), ("old", v4)):
        version = "blocks-v5" if name == "new" else "blocks-v4"
        path = tmp_path / "parsed" / name / version / "document.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(doc))
    assert _evidence_hash(Store, "new", {}) == _evidence_hash(Store, "old", {})
    assert _evidence_hash(Store, "new", {}).startswith("text:")


def test_claim_on_new_block_validates():
    from kb_pipeline.extract import validate

    doc = parse(STUTTGART.encode(), "text/html", URL)
    row = next(b for b in doc["blocks"] if b["text"] == "REGELSTUDIENZEIT 6 Semester")
    claim = Claim(
        field="duration_semesters",
        value="6",
        quote=row["text"],
        location_id=row["id"],
        applicant_group="general (no specific applicant group stated)",
        intake=None,
        conditions=None,
        method="rules",
    )
    assert validate(claim, doc) == "valid"


# ---- regular semester fee sentence ----------------------------------------------------

from kb_pipeline.extract import semester_fee_sentence  # noqa: E402


@pytest.mark.parametrize(
    "text, expected",
    [
        (
            "Der Sozialbeitrag für das Wintersemester 2026/2027 beläuft sich auf insgesamt "
            "380,00 Euro. Dies setzt sich zusammen aus Beiträgen für:",
            (
                "Der Sozialbeitrag für das Wintersemester 2026/2027 beläuft sich auf "
                "insgesamt 380,00 Euro",
                "winter semester 2026/2027",
            ),
        ),
        (
            "The semester contribution for the winter semester 2026/27 is €402 .",
            ("The semester contribution for the winter semester 2026/27 is €402", "winter semester 2026/27"),
        ),
        ("The semester fee is EUR 312.50 per semester.", ("The semester fee is EUR 312.50", None)),
    ],
)
def test_regular_semester_fee_sentence(text, expected):
    assert semester_fee_sentence(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        # reduced, late and leave-of-absence amounts are not the regular fee
        "The reduced semester fee during a leave of absence is € 21.26.",
        "Die Verspätungsgebühr beträgt 15 Euro.",
        "The semester fee for auditors is € 100.00",
        # the fee is not the sentence's subject
        "Students who pay the semester contribution of €402 get a ticket.",
        # no amount
        "The semester contribution is due before re-enrollment.",
    ],
)
def test_other_fee_sentences_are_not_the_regular_fee(text):
    assert semester_fee_sentence(text) is None


def test_fee_rule_claim_is_valid():
    from kb_pipeline.extract import validate

    html = (
        "<main><h1>Rückmeldung und Sozialbeitrag</h1><h2>Zusammensetzung</h2>"
        "<p>Der Sozialbeitrag für das Wintersemester 2026/2027 beläuft sich auf insgesamt "
        "380,00 Euro. Dies setzt sich zusammen aus Beiträgen für:</p></main>"
    )
    doc = parse(html.replace("</main>", FILLER + "</main>").encode(), "text/html", URL)
    (claim,) = [c for c in rule_claims(doc, TARGET) if c.field == "semester_contribution"]
    assert claim.intake == "winter semester 2026/2027"
    assert validate(claim, doc) == "valid"


def test_german_deadline_row_is_a_recurring_deadline():
    from kb_pipeline.extract import validate

    html = (
        "<main><h1>Informatik B.Sc.</h1>"
        '<div class="fact"><h3>BEWERBUNGSSCHLUSS</h3><div>15. Juli für Wintersemester</div></div>'
        "</main>"
    )
    doc = parse(html.replace("</main>", FILLER + "</main>").encode(), "text/html", URL)
    (claim,) = [c for c in rule_claims(doc, TARGET) if c.field == "deadline"]
    assert claim.value == "BEWERBUNGSSCHLUSS 15. Juli für Wintersemester"
    assert claim.intake == "winter semester (recurring)"
    assert validate(claim, doc) == "valid"


# ---- explicit "no tuition fees" statements --------------------------------------------

from kb_pipeline.extract import no_tuition_sentence  # noqa: E402


@pytest.mark.parametrize(
    "text, sentence, exceptions",
    [
        (
            "An der TU Dresden gibt es derzeit keine generellen Studiengebühren. Für "
            "Langzeitstudierende, im Zweitstudium oder Fernstudium sind jedoch "
            "Studiengebühren zu zahlen.",
            "An der TU Dresden gibt es derzeit keine generellen Studiengebühren.",
            "Für Langzeitstudierende, im Zweitstudium oder Fernstudium sind jedoch "
            "Studiengebühren zu zahlen.",
        ),
        (
            "Tuition Fees There are no tuition fees. However, each student must pay the so "
            "called Social Contribution Fee (approx. €330 per semester).",
            "Tuition Fees There are no tuition fees.",
            "However, each student must pay the so called Social Contribution Fee (approx. "
            "€330 per semester).",
        ),
        (
            "RWTH Aachen University continues its policy of not charging additional tuition "
            "fees for international students from non-EU countries. All students pay the "
            "semester fee.",
            "RWTH Aachen University continues its policy of not charging additional tuition "
            "fees for international students from non-EU countries.",
            None,
        ),
    ],
)
def test_no_tuition_sentence(text, sentence, exceptions):
    assert no_tuition_sentence(text) == (sentence, exceptions)


@pytest.mark.parametrize(
    "text",
    [
        # a campus exception, not the programme's rule
        "No tuition fees will be charged at the other locations.",
        "International students pay tuition fees of EUR 1,500 per semester.",
        "Tuition fees are not refunded after enrolment.",
    ],
)
def test_other_tuition_sentences_are_not_no_tuition(text):
    assert no_tuition_sentence(text) is None


# ---- one block read twice ---------------------------------------------------------------


def test_label_kept_or_dropped_from_one_block_agrees():
    from kb_pipeline.engine import Engine

    def m(value, loc="b0002.5", snap="s1", field="teaching_language"):
        return ({"snapshot_id": snap}, {"field": field, "value": value, "location_id": loc})

    assert not Engine._values_disagree([m("German and English"), m("Language German and English")])
    # different blocks: the texts still have to match
    assert Engine._values_disagree([m("German and English"), m("Language German and English", "b0044")])
    # numbers never match by containment
    assert Engine._values_disagree(
        [m("6", field="duration_semesters"), m("16", field="duration_semesters")]
    )
