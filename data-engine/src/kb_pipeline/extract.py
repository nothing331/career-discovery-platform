"""Conservative rules and exact-evidence checks. No admissions decisions."""

import re
from .contracts import Claim, scope_known, GENERAL_SCOPE, RECURRING_INTAKES
from .acquire import normal
from .clauses import requirement_hold
from .structured import parse_amount

EXTRACTOR_VERSION = "rules-v7"
SCHEMA_VERSION = "claims-v3"
PROMPT_VERSION = "grounded-v4"
CLASSIFIER_VERSION = "keyword-v2"

_COUNTRIES = (
    "india|china|vietnam|pakistan|bangladesh|nepal|sri\\s+lanka|nigeria|ghana|kenya|egypt|iran|"
    "iraq|syria|turkey|russia|ukraine|belarus|brazil|mexico|colombia|peru|argentina|indonesia|"
    "malaysia|thailand|philippines|mongolia|uzbekistan|kazakhstan|korea|japan|morocco|tunisia|"
    "algeria|cameroon|ethiopia|jordan|lebanon|usa|uk|united\\s+states|united\\s+kingdom"
)
_NOT_ORIGIN = (
    "january|february|march|april|may|june|july|august|september|october|november|december|"
    "monday|tuesday|wednesday|thursday|friday|saturday|sunday|germany|german|"
    "winter|summer|computer|informatics|mathematics|science|bachelor|master|sommer|wintersemester|"
    "sommersemester|the|this|that|our|now|next|each"
)
GROUP_RE = re.compile(
    r"\b(?:international|foreign|non[-\s]?eu|eu|eea|nationals?|indian|chinese|vietnamese|pakistani"
    r"|iranian|turkish|russian|non[-\s]?german|third[-\s]countr\w*|drittstaat\w*|overseas"
    r"|citizens?|staatsangeh[oö]rig\w*|staatsb[uü]rger\w*|APS"
    rf"|(?:{_COUNTRIES})"
    r"|german\s+(?:applicants?|citizens?|nationals?|students?)"
    r"|(?:with|have|having|hold(?:ing)?)\s+(?:a\s+|an\s+)?german\s+(?:degree|school|secondary|university|qualification|bachelor|abitur)"
    r"|bildungsausl\w*|bildungsinl\w*|nicht[-\s]?eu\w*|deutsche\s+bewerber\w*)\b"
    r"|ausl[aä]ndisch\w*|ausl[aä]nder\w*"
    rf"|\bfrom\s+(?-i:(?!(?i:{_NOT_ORIGIN})\b)[A-Z][a-z]{{3,}})",
    re.I,
)
SEASONS = {
    "winter": re.compile(
        r"winter\s*semester|wintersemester|\bwise\b|winter\s+term", re.I
    ),
    "summer": re.compile(
        r"summer\s*semester|sommersemester|\bsose\b|summer\s+term", re.I
    ),
}
_MONTH = (
    r"(?:january|february|march|april|may|june|july|august|september|october|november|december"
    r"|januar|februar|m[aä]rz|maerz|mai|juni|juli|oktober|dezember"
    r"|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)"
)
DATE_RE = re.compile(
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?\.?\s*(?:of\s+)?{_MONTH}\b"
    rf"|\b{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\b"
    r"|(?<![\d.])(?:0?[1-9]|[12]\d|3[01])\.\s?(?:0?[1-9]|1[0-2])\.(?!\d)",
    re.I,
)


def _context(block):
    return block.get("heading", "") + " " + block["text"]


def _scope_context(document, block):
    """Heading + text, plus a short ':'-terminated label paragraph above a list/table row.

    Parser output is unchanged; this is a document-aware view. The label must be the
    nearest preceding ``p`` block of the same section (same heading).
    """
    ctx = _context(block)
    if block.get("location", {}).get("tag") not in ("li", "tr"):
        return ctx
    blocks = document["blocks"]
    idx = next((i for i, b in enumerate(blocks) if b["id"] == block["id"]), None)
    for prev in reversed(blocks[:idx] if idx is not None else []):
        tag = prev.get("location", {}).get("tag")
        if tag in HEADING_TAGS or prev.get("heading", "") != block.get("heading", ""):
            break
        if tag == "p":
            label = prev["text"].strip()
            if len(label) < 200 and label.endswith(":"):
                return label + " " + ctx
            break
    return ctx


YEAR_RE = re.compile(r"\b(?:19|20|21)\d{2}\b|\b\d{2,4}/\d{2,4}\b")


def detect_applicant_scope(text):
    """GENERAL_SCOPE unless the text mentions a specific applicant group."""
    return "not established" if GROUP_RE.search(text or "") else GENERAL_SCOPE


def _seasons(text):
    return {k for k, r in SEASONS.items() if r.search(text or "")}


def detect_recurring_intake(block):
    """Recurring semester intake when exactly one season and a day+month date appear."""
    seasons = _seasons(_context(block))
    if (
        len(seasons) != 1
        or not DATE_RE.search(block["text"])
        or YEAR_RE.search(_context(block))
    ):
        return None
    return f"{next(iter(seasons))} semester (recurring)"


def classify(block):
    text = (block.get("heading", "") + " " + block["text"]).lower()
    # Programme titles and qualification rows are useful even without topic words.
    if block.get("location", {}).get("tag") == "h1":
        return "relevant"
    return (
        "relevant"
        if re.search(
            r"admission|requir|\bmust\b|prerequis|fee|tuition|duration|semester|ects|language|deadline|degree awarded|application|examination regulation|zulassung|bewerbung|gebühr|sprach|regelstudienzeit|leistungspunkt|studienbeitrag|einschreib|zugangsvoraussetzung|erforderlich|nachweis",
            text,
        )
        else "other"
    )


HEADING_TAGS = ("h1", "h2", "h3", "h4")
# Words that make a paragraph/list item a requirement candidate. Language tests and
# APS are admission conditions even when the text says "accepted" instead of "required".
_REQUIREMENT_TRIGGER = (
    r"must|required|requirement|prerequisite|voraussetzung|nachweis"
    r"|\bIELTS\b|\bTOEFL\b|\bTestDaF\b|\bDSH\b|\bAPS\b|\bPTE\b"
    r"|language\s+(?:certificates?|proficiency)\s+(?:is|are)\s+(?:accepted|needed|necessary)"
)


def is_question(text):
    t = text.strip()
    return t.endswith("?") or t.casefold().startswith("frequently asked")


def rule_claims(document, target, primary=True):
    """primary=False (follow-up pages): never emit a programme title from the page h1."""
    result = []

    def add(field, value, block, conditions=None, intake=None):
        if len(str(value)) > 3000 or len(block["text"]) > 4000:
            document.setdefault("rule_skips", []).append(
                {"location_id": block["id"], "reason": "SECTION_TOO_LARGE"}
            )
            return
        result.append(
            Claim(
                field=field,
                value=str(value),
                quote=block["text"],
                location_id=block["id"],
                applicant_group=target.applicant_group
                if scope_known(target.applicant_group)
                else detect_applicant_scope(_scope_context(document, block)),
                intake=intake if intake is not None else target.intake,
                conditions=conditions,
                method=EXTRACTOR_VERSION,
            )
        )

    title = next(
        (b for b in document["blocks"] if b["location"].get("tag") == "h1"), None
    )
    if title and primary:
        add("programme_title", title["text"], title)
    for b in document["blocks"]:
        text = b["text"]
        if b["location"].get("tag") == "tr":
            if re.search(r"duration|period of study|regelstudienzeit", text, re.I):
                m = re.search(r"\b(\d{1,2})\s*semesters?\b", text, re.I)
                if m:
                    add("duration_semesters", m[1], b)
            if re.search(r"credits|scope|ects", text, re.I):
                m = re.search(r"\b(\d{2,3})\s*ECTS\b", text, re.I)
                if m:
                    add("ects", m[1], b)
            m = re.search(
                r"(?:languages? of instruction|teaching language)\s*[:：]?\s*(.+)",
                text,
                re.I,
            )
            if m:
                add("teaching_language", m[1], b)
            m = re.search(r"tuition fees\s*[:：]?\s*(.+)", text, re.I)
            if m:
                add(
                    "tuition",
                    m[1],
                    b,
                    conditions="Applicant applicability and exemptions require review",
                )
            if re.search(r"deadline", text, re.I):
                add(
                    "deadline",
                    text,
                    b,
                    conditions="Recurring/source dates only; no target year inferred",
                    intake=None if target.intake else detect_recurring_intake(b),
                )
        if (
            classify(b) == "relevant"
            and b["location"].get("tag") in ("p", "li")
            and re.search(_REQUIREMENT_TRIGGER, text, re.I)
            and 40 <= len(text) <= 3000
            and b["location"].get("tag") not in HEADING_TAGS
            and not is_question(text)
        ):
            add(
                "requirement",
                text,
                b,
                conditions="Verbatim requirement text; not an executable eligibility rule",
            )
    return result


# Placeholder text some pages/models emit instead of a value. Never a fact.
_PLACEHOLDER_EXACT = re.compile(
    r"(?:not\s+(?:specified|stated|provided|available|given|established|mentioned|listed|yet\s+\w+)|n/?a|tba|tbd|tbc|unknown|unspecified|varies|various|"
    r"to\s+be\s+(?:announced|determined|confirmed)|none\s+given|-+|\u2013|\u2014|\?+)",
    re.I,
)
_PLACEHOLDER_SEE = re.compile(
    r"\bsee\s+(?:the\s+)?(?:current\s+|latest\s+|our\s+)?(?:fee\s+(?:structure|table|schedule)|fees?|website|web\s*page|details|below|above|page|link)\b",
    re.I,
)


def is_placeholder(value, field=None):
    """True for 'Not specified', 'n/a', 'TBA', 'See current fee structure', ..."""
    text = re.sub(r"[\s.:;,!]+$", "", normal(value or "")).strip()
    if not text:
        return True
    if _PLACEHOLDER_EXACT.fullmatch(text):
        return True
    # Prefix-labelled placeholders such as "Semester fee See current fee structure".
    return field != "requirement" and len(text) <= 80 and bool(_PLACEHOLDER_SEE.search(text))


_DEGREE_TOKEN = re.compile(
    r"(?<![\w.])(?:(?P<b>b\.?\s?(?:sc|a|eng|ed)\.?|ll\.?\s?b\.?|bachelor(?:'s|\u2019s)?(?:\s+of\s+(?:science|arts|engineering|education|laws))?)"
    r"|(?P<m>m\.?\s?(?:sc|a|eng|ed)\.?|ll\.?\s?m\.?|master(?:'s|\u2019s)?(?:\s+of\s+(?:science|arts|engineering|education|laws))?))(?![\w])",
    re.I,
)


_TITLE_NOISE = re.compile(
    r"\b(?:degree\s+)?(?:programme|program)\s+(?:in|of)\b|\bdegree\s+in\b"
    r"|\b(?:studiengang|studienprogramm|degree|programme|program)\b"
)


def _title_words(text):
    text = re.sub(r"[()\[\]{}.,:;|\u2013\u2014-]+", " ", text)
    text = _TITLE_NOISE.sub(" ", text)
    words = " ".join(text.split())
    return re.sub(r"^(?:in|of|im|in\s+der)\s+", "", words)


def canonical_title(value):
    """Comparable form of a programme title: degree token(s) split off, case, brackets,
    punctuation, "Degree Programme in"/"Studiengang" and the degree's position ignored.
    Returns (words, degree levels).

    'Computer Science (M.Sc.)', 'M.Sc. Computer Science', "Master's Degree Programme in
    Computer Science" and 'computer science, MSc' agree; 'Computer Science B.Sc.' differs
    from them by level, and 'Data Science (M.Sc.)' by subject.
    """
    text = normal(value or "").casefold()
    levels = {
        "bachelor" if m.group("b") else "master" for m in _DEGREE_TOKEN.finditer(text)
    }
    text = _DEGREE_TOKEN.sub(" ", text)
    return _title_words(text.replace("/", " ")), frozenset(levels)


def title_alternatives(value):
    """Words of every name a title offers: 'Informatik/Computer Science' is the pair
    (German/English) and matches either side or the joined form. (alternatives, levels)."""
    words, levels = canonical_title(value)
    text = normal(value or "").casefold()
    text = _DEGREE_TOKEN.sub(" ", text)
    parts = [p for p in (_title_words(x) for x in re.split(r"\s*/\s*", text)) if p]
    return frozenset({words, *parts}), levels


_NUMBER_WORDS = {
    1: ("one", "ein", "eins", "eine", "einem"),
    2: ("two", "zwei"),
    3: ("three", "drei"),
    4: ("four", "vier"),
    5: ("five", "fünf", "fuenf"),
    6: ("six", "sechs"),
    7: ("seven", "sieben"),
    8: ("eight", "acht"),
    9: ("nine", "neun"),
    10: ("ten", "zehn"),
    11: ("eleven", "elf"),
    12: ("twelve", "zwölf", "zwoelf"),
}


_MONEY_FIELDS = ("tuition", "semester_contribution")
_AMOUNT_VALUE = re.compile(
    r"(?:€|EUR(?![A-Za-z])|Euro(?![A-Za-z]))?\s*(\d[\d.,]*)\s*(?:€|EUR(?![A-Za-z])|Euros?(?![A-Za-z]))?",
    re.I,
)
_AMOUNT_IN_TEXT = re.compile(
    r"(?<![\d.,])(?:\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)(?!\d)"
)


def _amounts(text):
    result = set()
    for token in _AMOUNT_IN_TEXT.findall(text):
        try:
            result.add(parse_amount(token))
        except ArithmeticError:
            pass
    return result


def _money_in_quote(value, quote):
    """A bare amount equals an amount of the quote across decimal comma/point and
    thousand separators: 412.30 = 412,30 = 412.3; 1500 = 1.500 = 1,500 (EUR context)."""
    m = _AMOUNT_VALUE.fullmatch(value.strip())
    if not m:
        return False
    try:
        wanted = parse_amount(m.group(1))
    except ArithmeticError:
        return False
    return wanted in _amounts(quote)


def value_in_quote(field, value, quote):
    """Is the value literally in the quote? A digit duration may also be a number word
    directly before 'semester(s)' (EN: 'six semesters', DE: 'sechs Semester'); a money
    amount may differ in decimal/thousand separator ('412.30' vs '412,30')."""
    v, q = normal(value).casefold(), normal(quote).casefold()
    if v in q:
        return True
    if field in _MONEY_FIELDS and _money_in_quote(normal(value), normal(quote)):
        return True
    if field == "duration_semesters" and v.isdecimal() and int(v) in _NUMBER_WORDS:
        words = "|".join(_NUMBER_WORDS[int(v)])
        return bool(re.search(rf"\b(?:{words})[\s-]+(?:semesters?|semestern?)\b", q))
    return False


_SEMESTER_FEE_TERMS = re.compile(
    r"Studierendenwerk|administrative|student\s+council|semester\s+fee|Semesterbeitrag"
    r"|Verwaltungs(?:geb[uü]hr|kosten)|Sozialbeitrag",
    re.I,
)
_TUITION_TERM = re.compile(r"tuition|Studiengeb[uü]hr|Studienbeitr", re.I)


def tuition_is_semester_fee(value, quote):
    """True for a ``tuition`` value that is only the Studierendenwerk / administrative /
    semester-fee text: it names those fees, never tuition itself, and no tuition label
    sits just before it in the quote. (A value that follows 'tuition fees' is kept.)"""
    if not _SEMESTER_FEE_TERMS.search(value) or _TUITION_TERM.search(value):
        return False
    start = normal(quote).casefold().find(normal(value).casefold())
    before = normal(quote)[max(0, start - 40) : max(0, start)] if start >= 0 else ""
    return not _TUITION_TERM.search(before)


def validate(claim, document):
    if not normal(claim.value) or not normal(claim.quote):
        return "EMPTY_CLAIM"
    if is_placeholder(claim.value, claim.field):
        return "NOT_A_FACT"
    block = next((b for b in document["blocks"] if b["id"] == claim.location_id), None)
    if not block or normal(claim.quote) not in normal(block["text"]):
        return "EVIDENCE_NOT_FOUND"
    if not value_in_quote(claim.field, claim.value, claim.quote):
        return "VALUE_NOT_GROUNDED"
    if claim.field == "tuition" and tuition_is_semester_fee(claim.value, claim.quote):
        # Fee text filed under the wrong field: it would otherwise "conflict" with the
        # real tuition (or with the same text under semester_contribution).
        return "NOT_A_FACT"
    if claim.field != "programme_title":
        if block.get("location", {}).get("tag") in HEADING_TAGS or (
            normal(block.get("heading", ""))
            and normal(claim.value).casefold() == normal(block["heading"]).casefold()
        ):
            return "NOT_A_FACT"
        if claim.field == "requirement" and (
            len(block["text"].strip()) < 40 or is_question(block["text"])
        ):
            return "NOT_A_FACT"
        if claim.field == "requirement":
            # Curriculum/exam/thesis/fee clauses are not admission facts; subsection
            # fragments are incomplete (admission) or noise (everything else).
            held = requirement_hold(block["text"])
            if held != "NOT_A_FACT" and requirement_hold(claim.quote) == "NOT_A_FACT":
                # A regulation clause quoted from inside a larger block (e.g. a whole
                # PDF page) is judged on its own text, not on the page around it.
                held = "NOT_A_FACT"
            if held:
                return held
    if (
        claim.field != "programme_title"
        and " ".join(claim.applicant_group.split()).casefold()
        == GENERAL_SCOPE.casefold()
        and detect_applicant_scope(_scope_context(document, block)) != GENERAL_SCOPE
    ):
        return "APPLICANT_SCOPE_CONFLICT"
    if claim.field == "requirement" and (
        normal(claim.value) != normal(block["text"])
        or normal(claim.quote) != normal(block["text"])
    ):
        return "INCOMPLETE_REQUIREMENT"
    if claim.field in ("duration_semesters", "ects") and (
        not claim.value.isdecimal() or not 1 <= int(claim.value) <= 1000
    ):
        return "INVALID_NUMERIC_VALUE"
    if claim.field == "deadline":
        intake = " ".join((claim.intake or "").split()).casefold()
        context = _context(block)
        years = re.findall(r"\b(?:19|20|21)\d{2}\b", claim.intake or "")
        if intake in RECURRING_INTAKES:
            season = intake.split()[0]
            present = _seasons(context)
            if (
                season not in present
                or not DATE_RE.search(claim.quote)
                or YEAR_RE.search(context)
            ):
                return "INTAKE_NOT_GROUNDED"
            if len(present) > 1 and _seasons(claim.quote) != {season}:
                return "INTAKE_NOT_GROUNDED"
        elif not scope_known(claim.intake) or not years:
            return "MISSING_INTAKE_SCOPE"
        elif any(year not in context for year in years):
            return "INTAKE_NOT_GROUNDED"
    if claim.field in (
        "tuition",
        "semester_contribution",
        "requirement",
    ) and not scope_known(claim.applicant_group):
        return "MISSING_APPLICANT_SCOPE"
    return "valid"


def quality(claim, status):
    scope = (
        scope_known(claim.applicant_group)
        and (
            claim.field != "deadline"
            or status not in ("MISSING_INTAKE_SCOPE", "INTAKE_NOT_GROUNDED")
        )
        and status not in ("NOT_A_FACT", "APPLICANT_SCOPE_CONFLICT")
    )
    components = {
        "authority": 30,
        "grounding": 25
        if status != "EVIDENCE_NOT_FOUND" and status != "VALUE_NOT_GROUNDED"
        else 0,
        "applicability": 20 if scope else 0,
        "freshness": 0,
        "verification": 0,
    }
    return {
        "score": sum(components.values()),
        "components": components,
        "rubric": "poc-v1",
        "meaning": "heuristic, not a probability",
        "reasons": [
            "Official registered source",
            "Exact evidence checked",
            "Effective intake/freshness not established",
            "Human review pending",
            status,
        ],
    }
