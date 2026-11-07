"""Deterministic (regex) normaliser: verbatim claim quotes -> StructuredFact.

Design rules (documented choices):

* Only ``claim.quote`` is read. ``claim.field`` gates *which* extractors run
  (fees: tuition/semester_contribution/requirement; degrees, grades and ECTS:
  requirement) but language, route, APS, restriction and windows can come from
  any claim. ``claim.intake`` / ``claim.value`` are never used.
* Never invent. Ambiguous text emits nothing (ranges of CEFR levels, mixed
  "first semester admission-free / higher semesters restricted", plain "TOEFL"
  without iBT, TOEFL "5.0 according to the new scale", negated APS, ...).
* "should provide proof ... level B2" stays ``required``; only an explicit
  "recommended"/"empfohlen" marker yields ``recommended``.
* Test names without a score are emitted with ``min_score=None`` (they are
  accepted tests). Tests we cannot name in the enum (TOEIC, OOPT, ...) are
  skipped rather than emitted as ``OTHER`` because the model has no name field.
* Fee components (Studierendenwerk 103 EUR, administrative 80 EUR, ...) are not
  emitted in v1; tuition, semester contribution and totals are. A component
  amount inherits the period of its section total only when the section's
  components add up exactly to that total (arithmetic evidence).
* An explicit "no tuition fees" yields tuition "0" with period None.
  Negations are never turned into zero otherwise.
* Windows: deadlines labelled interview/early/optional/extended/... are skipped
  (no track field on the model); "start of semester" dates are skipped.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Iterable, Protocol

from pydantic import ValidationError

from .contracts import Claim
from .structured import (
    NORMALIZER_VERSION,
    ApplicationRoute,
    ApplicationWindow,
    ApsRequired,
    FeeAmount,
    LanguageLevel,
    LanguageTest,
    MinGrade,
    RequiredDegree,
    RestrictedAdmission,
    StructuredFact,
    SubjectEcts,
    format_amount,
    parse_amount,
)

I = re.I  # noqa: E741

Raw = tuple[str, object, str]  # (kind, data model, evidence_text)


class Normalizer(Protocol):
    """Plug-in point: an LLM normaliser later implements the same interface."""

    name: str

    def normalize(self, claim_id: str, claim: Claim) -> list[StructuredFact]: ...


# ---------------------------------------------------------------- helpers

_SENT_SPLIT = re.compile(r"(?<!\d)(?<!e\.V)(?<!M\.Sc)(?<!B\.Sc)\.\s+(?=[A-ZÄÖÜ])")


def _sentences(text: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    for m in _SENT_SPLIT.finditer(text):
        spans.append((start, m.start() + 1))
        start = m.end()
    spans.append((start, len(text)))
    return spans


def _sentence_of(spans: list[tuple[int, int]], pos: int) -> tuple[int, int]:
    for a, b in spans:
        if a <= pos < b or pos == b:
            return a, b
    return spans[-1]


def _ev(text: str, a: int, b: int) -> str:
    return text[a:b].strip()


# Shared negation / exemption guard. A clause is a sentence cut at ; ( ) and
# contrastive "but"; it is negated when a negator sits near a requirement word, or
# when it states an exemption. Conservative: negated clauses emit nothing.
_REQ_WORD = (
    r"(?:required|requires?|necessary|needed|accepted|acceptable|recognised|recognized|"
    r"sufficient|mandatory|erforderlich|nötig|notwendig|verlangt|gefordert|anerkannt|"
    r"akzeptiert|verpflichtend|vorgeschrieben)"
)
_NEGATED = re.compile(
    r"\b(?:not|no\s+longer|nicht|kein\w*|never|nie|neither|nor)\b(?:\W+[\w-]+){0,6}?\W+"
    + _REQ_WORD
    + r"\b"
    r"|\b" + _REQ_WORD + r"\b\W+(?:is|are|ist|sind)?\W*(?:not|nicht)\b"
    r"|\bexempt\w*|\bbefreit\w*|\bbefreiung\b|\b(?:does|do)\s+not\s+need\b|\bneed\s+not\b"
    r"|\bno\s+need\b|\bnicht\s+(?:benötigt|brauchen)\b|\bbrauch\w*\s+(?:kein\w*|nicht)\b",
    I,
)
_CLAUSE_CUT = re.compile(r"[;()]|\b(?:but|however|aber|jedoch|sondern)\b", I)


def _clause_of(text: str, a: int, b: int, pos: int) -> tuple[int, int]:
    """Clause bounds inside sentence [a, b) around ``pos``."""
    lo, hi = a, b
    for m in _CLAUSE_CUT.finditer(text, a, b):
        if m.end() <= pos:
            lo = m.end()
        elif m.start() >= pos:
            hi = m.start()
            break
    return lo, hi


def _negated_at(text: str, spans: list[tuple[int, int]], pos: int) -> bool:
    a, b = _sentence_of(spans, pos)
    lo, hi = _clause_of(text, a, b, pos)
    return bool(_NEGATED.search(text[lo:hi]))


# ---------------------------------------------------------------- language tests

_TEST_TOKENS = [
    ("TOEFL_ESSENTIALS", re.compile(r"TOEFL\s+Essentials", I)),
    ("TOEFL_IBT", re.compile(r"TOEFL[\s-]*\(?\s*iBT\s*\)?|\biBT\b", I)),
    ("IELTS", re.compile(r"\bIELTS\b", I)),
    ("PTE", re.compile(r"\bPearson\s+PTE(?:\s+Academic)?|\bPTE(?:\s+Academic)?\b", I)),
    (
        "CAMBRIDGE",
        re.compile(
            r"\bCambridge(?:\s+(?:English:?\s*)?(?:C1\s+Advanced|C2\s+Proficiency|"
            r"Advanced|Proficiency|First|CAE|CPE|FCE))?|\bCAE\b|\bCPE\b"
        ),
    ),
    ("TESTDAF", re.compile(r"\bTestDaF\b", I)),
    ("DSH", re.compile(r"\bDSH(?:[-\s]?([123]))?(?!\w)")),
    (
        "TELC",
        re.compile(
            r"\btelc(?:\s+(?:University|Hochschule|Deutsch|English|Englisch))?\b", I
        ),
    ),
]
_TEST_LANG = {
    "TOEFL_ESSENTIALS": "english",
    "TOEFL_IBT": "english",
    "IELTS": "english",
    "PTE": "english",
    "CAMBRIDGE": "english",
    "TESTDAF": "german",
    "DSH": "german",
}
_SCORE = r"[345]\s*[x×]\s*[345]|\d{1,3}(?:[.,]\d)?"
_SCORE_IMMEDIATE = re.compile(rf"^\s*[:(\-–]?\s*(?:TDN\s*)?({_SCORE})(?![\d])", I)
_SCORE_CUE = re.compile(
    r"(?:minimum|min\.?|at\s+least|mindestens|score|band|overall|TDN)"
    r"(?:\s+(?:overall|band|score|of|ibt|total|result|von|at|least))*\s*[:\-]?\s*"
    rf"({_SCORE})(?![\d])",
    I,
)


def _score_ok(test: str, score: str) -> bool:
    s = re.sub(r"\s+", "", score.replace(",", ".").lower())
    try:
        if test == "TESTDAF":
            return bool(re.fullmatch(r"[345](?:[x×][345])?", s))
        v = float(s)
    except ValueError:
        return False
    if test == "IELTS":
        return 4 <= v <= 9 and (v * 2).is_integer()
    if test == "TOEFL_IBT":
        return 30 <= v <= 120 and v.is_integer()
    if test == "PTE":
        return 10 <= v <= 90 and v.is_integer()
    if test == "TOEFL_ESSENTIALS":
        return 1 <= v <= 12
    if test == "DSH":
        return v in (1, 2, 3)
    return False


def _language_tests(claim: Claim) -> list[Raw]:
    q = claim.quote
    spans = _sentences(q)
    tokens = []
    for test, rx in _TEST_TOKENS:
        for m in rx.finditer(q):
            tokens.append(
                [m.start(), m.end(), test, m.group(1) if m.groups() else None]
            )
    tokens.sort()
    kept: list[list] = []
    for t in tokens:
        if kept and t[0] < kept[-1][1]:
            continue
        if (
            kept
            and kept[-1][2] == t[2]
            and t[0] - kept[-1][1] <= 80
            and not kept[-1][3]
        ):
            kept[-1][1] = t[1]  # merge "IELTS, including IELTS Online Academic"
            kept[-1][3] = t[3]
            continue
        kept.append(t)
    out: list[tuple[str, str | None, str, str]] = []
    for i, (start, end, test, inline) in enumerate(kept):
        if _negated_at(q, spans, start):
            continue
        limit = min(
            kept[i + 1][0] if i + 1 < len(kept) else len(q),
            end + 120,
            _sentence_of(spans, end)[1],
        )
        seg = q[end:limit]
        score, score_end = None, end
        if inline and _score_ok(test, inline):
            score, score_end = inline, end
        else:
            m = _SCORE_IMMEDIATE.match(seg) or _SCORE_CUE.search(seg)
            if m and _score_ok(test, m.group(1)):
                score, score_end = m.group(1).replace(",", "."), end + m.end(1)
                if score.replace(".", ",") in q[end : end + m.end(1)]:
                    score = m.group(1).replace(",", ".")
        language = _TEST_LANG.get(test)
        if test == "TELC":
            tok = q[start:end].lower()
            has_en = bool(re.search(r"english|englisch", q, I))
            has_de = bool(re.search(r"german|deutsch", q, I))
            if "deutsch" in tok:
                language = "german"
            elif "english" in tok or "englisch" in tok:
                language = "english"
            elif has_en != has_de:
                language = "english" if has_en else "german"
            else:
                continue
        out.append((test, score, language, _ev(q, start, score_end)))
    # an unscored mention is dropped when the same test also has a scored mention
    scored = {t for t, sc, _, _ in out if sc}
    result: dict[tuple, Raw] = {}
    for test, score, language, evidence in out:
        if score is None and test in scored:
            continue
        result.setdefault(
            (test, score),
            (
                "language_test",
                LanguageTest(test=test, min_score=score, language=language),
                evidence,
            ),
        )
    return list(result.values())


# ---------------------------------------------------------------- CEFR levels

_LANG_WORD = re.compile(r"\b(german|deutsch\w*|english|englisch\w*)\b", I)
_CEFR_CUE = re.compile(
    r"(?i:\blevel|\bCEFR|\bCEF\b|\bGER\b|\bGeR\b|\bNiveau(?:stufe)?|\bStufe)\s*[:\-]?\s*"
    r"(?i:of\s+|von\s+)?(?i:at\s+least\s+|mindestens\s+)?([ABC][12])\b"
)
_CEFR_REV = re.compile(r"\b([ABC][12])\b(?=\s*\(?(?i:CEFR|GER)\b)")
_RECOMMENDED = re.compile(
    r"\(?\s*(?:recommended|empfohlen|empfehlenswert|desirable|wünschenswert|preferred)\s*\)?",
    I,
)


def _language_levels(claim: Claim) -> list[Raw]:
    q = claim.quote
    spans = _sentences(q)
    matches = []
    for rx in (_CEFR_CUE, _CEFR_REV):
        for m in rx.finditer(q):
            matches.append((m.start(), m.end(), m.group(1), m.start(1), m.end(1)))
    matches.sort()
    out: list[Raw] = []
    last_end = -1
    for start, end, level, ls, le in matches:
        if start < last_end:
            continue
        last_end = end
        if re.match(r"\s*(?:-|–|/|or\s|oder\s|to\s|bis\s)\s*[ABC][12]\b", q[le:]):
            continue
        if re.search(
            r"[ABC][12]\s*(?:-|–|/|or|oder|to|bis)\s*(?:level\s*)?$",
            q[max(0, start - 15) : ls],
            I,
        ):
            continue
        if _negated_at(q, spans, ls):
            continue
        sa, sb = _sentence_of(spans, ls)
        before = [m for m in _LANG_WORD.finditer(q, sa, ls) if ls - m.end() <= 150]
        lang_m = before[-1] if before else None
        if lang_m is None:
            after = _LANG_WORD.search(q, le, min(sb, le + 30))
            lang_m = after
        if lang_m is None:
            continue
        language = (
            "german"
            if lang_m.group(1).lower().startswith(("german", "deutsch"))
            else "english"
        )
        tail = q[le : min(sb, le + 40)]
        rec = _RECOMMENDED.search(tail)
        strength = "recommended" if rec else "required"
        if not rec and re.search(
            r"(?:recommended|empfohlen)\W*$", q[max(sa, start - 25) : start], I
        ):
            strength = "recommended"
        ev_start = min(lang_m.start(), start)
        ev_end = le + rec.end() if rec else le
        out.append(
            (
                "language_level",
                LanguageLevel(language=language, cefr=level, strength=strength),
                _ev(q, ev_start, ev_end),
            )
        )
    return out


# ---------------------------------------------------------------- grade

_GRADE_WORD = re.compile(
    r"\b(?:grades?|GPA|Noten?|Abschlussnote|Durchschnittsnote|Gesamtnote|Notendurchschnitt)\b",
    I,
)
_GRADE_NUM = re.compile(r"(?<![\d.,])([1-4][.,]\d{1,2})(?!\d)")
_GRADE_PRE = re.compile(
    r"(?:minimum|mindestens|at\s+least|min\.?|better\s+than|besser\s+als|grade\s+of|Note\s+von|Note)\W*(?:of\s+)?$",
    I,
)
_GRADE_POST = re.compile(
    r"^\s*(?:or\s+better|or\s+higher|or\s+above|oder\s+besser|or\s+less|at\s+best)", I
)
_GERMAN_SCALE = re.compile(
    r"German\s+(?:grading|grade)|German\s+(?:grading\s+)?scale|deutsche[nrm]?\s+Noten|Notenskala|deutschen\s+Notensystem",
    I,
)
_RANK = re.compile(
    r"(?:ranked\s+(?:among|in)\s+the\s+)?(?:top|best)\s+\d{1,3}\s*%[^,;.()]*?(?=\s+(?:or|oder)\b|[,;.()]|$)|"
    r"zu\s+den\s+besten\s+\d{1,3}\s*%[^,;.()]*?(?=\s+(?:or|oder)\b|[,;.()]|$)",
    I,
)


def _min_grade(claim: Claim) -> list[Raw]:
    if claim.field != "requirement":
        return []
    q = claim.quote
    for sa, sb in _sentences(q):
        sent = q[sa:sb]
        if not _GRADE_WORD.search(sent):
            continue
        for m in _GRADE_NUM.finditer(q, sa, sb):
            raw = m.group(1)
            value = float(raw.replace(",", "."))
            if not 1.0 <= value <= 4.0:
                continue
            pre = q[max(sa, m.start() - 30) : m.start()]
            post = _GRADE_POST.match(q[m.end() : sb])
            if not (_GRADE_PRE.search(pre) or post):
                continue
            german = bool(_GERMAN_SCALE.search(sent))
            foreign = bool(re.search(r"\bGPA\b|\bout\s+of\b|/\s*4\b|percent", sent, I))
            higher = bool(
                post and re.match(r"\s*or\s+(?:higher|above)", post.group(0), I)
            )
            scale = "DE_1_TO_4" if german or not (foreign or higher) else "UNKNOWN"
            end = m.end() + (post.end() if post else 0)
            gw = [g for g in _GRADE_WORD.finditer(q, sa, m.start())]
            start = gw[-1].start() if gw else m.start()
            alt = None
            for r in _RANK.finditer(q, sa, sb):
                if r.end() <= start or r.start() >= end:
                    alt = r.group(0).strip()
                    start, end = (min(start, r.start()), max(end, r.end()))
                    break
            return [
                (
                    "min_grade",
                    MinGrade(value=raw.replace(",", "."), scale=scale, alternative=alt),
                    _ev(q, start, end),
                )
            ]
    return []


# ---------------------------------------------------------------- ECTS and degree

_ECTS_UNIT = (
    r"(?:ECTS(?:[- ]?(?:credits?|points?|Leistungspunkte))?|credit\s+points|credits|"
    r"Leistungspunkte[n]?|\bLP\b|\bCP\b)"
)
_ECTS_MIN = (
    r"(?:at\s+least|minimum(?:\s+of)?|min\.?|mindestens|no\s+fewer\s+than)\s+(\d{1,3})\s*"
    + _ECTS_UNIT
)
_ECTS_A = re.compile(
    r"(?:with\s+)?(?:an?\s+|the\s+|mit\s+(?:einem\s+)?)?"
    r"([A-Za-z][A-Za-z-]*(?:\s+[A-Za-z][A-Za-z-]*){0,3}?)\s+"
    r"(?:component|content|courses?|modules?|part|share|Anteil|credits)\s+(?:of\s+|von\s+)?"
    + _ECTS_MIN,
    I,
)
_ECTS_B = re.compile(
    _ECTS_MIN
    + r"\s+(?:in|of|from|im\s+Bereich|aus\s+dem\s+Bereich|im\s+Fach|in\s+den\s+Fächern)\s+"
    r"([A-Za-z][A-Za-z-]*(?:\s+[A-Za-z][A-Za-z-]*){0,3}?)"
    r"(?=\s*(?:[.,;)(]|$)|\s+(?:or|and|und|oder|with|mit)\b)",
    I,
)
_STOP_SUBJECT = {
    "total",
    "overall",
    "the",
    "a",
    "an",
    "these",
    "those",
    "your",
    "credits",
}


def _strip_lead(text: str) -> str:
    return re.sub(
        r"^(?:(?:in|a|an|the|with|of|and|or|closely|im|der|des|einem|einer|eine|mit)\s+)+",
        "",
        text.strip(),
        flags=I,
    )


def _subject_ects(claim: Claim) -> list[Raw]:
    if claim.field != "requirement":
        return []
    q = claim.quote
    out: list[Raw] = []
    used: set[int] = set()
    for rx, subj_group in ((_ECTS_A, 1), (_ECTS_B, 2)):
        for m in rx.finditer(q):
            number = m.group(2 if rx is _ECTS_A else 1)
            subject = _strip_lead(m.group(subj_group))
            if m.start() in used or not subject or subject.casefold() in _STOP_SUBJECT:
                continue
            used.add(m.start())
            out.append(
                (
                    "subject_ects_min",
                    SubjectEcts(min_ects=int(number), subject=subject),
                    _ev(q, m.start(), m.end()),
                )
            )
            break
    return out[:1]


_DEGREE = re.compile(
    r"undergraduate(?:\s+university)?\s+degree|bachelor(?:'s|s|’s)?\s+degree|bachelor(?:'s|s|’s)?|"
    r"Bachelorabschluss|Bachelor-?studium|\bB\.\s?Sc\.|\bB\.\s?A\.",
    I,
)
_DEGREE_SUBJECTS = re.compile(
    r"^\s*(?:in|of|from|im\s+Fach|im\s+Bereich|im\s+Studiengang|in\s+dem\s+Fach|aus\s+dem\s+Bereich)\s+"
    r"([^.;()]{3,100}?)(?=\s+(?:with|where|that|which|who|including|mit|sowie|and\s+(?:a|an|at|have|good|very|proof))\b|[.;(]|$)",
    I,
)
_SCHOOL = re.compile(
    r"(?:proof\s+of\s+(?:an?\s+)?)?\b(?:university\s+entrance\s+qualification|Hochschulzugangsberechtigung|"
    r"Hochschulreife|Abitur|(?:school[- ]leaving|secondary\s+school|high\s+school)\s+"
    r"(?:certificate|diploma|qualification))\b",
    I,
)
_NOT_SUBJECT = re.compile(
    r"(?:one\s+of|these|those|this|that|any|countries|a\s+country)\b", I
)
_EXEMPT_CTX = re.compile(r"(?:completed|completing|obtained|graduated|exempt\w*)\W", I)
_REQ_CUE = re.compile(
    r"\b(?:need|require\w*|must|prerequisite|proof|Voraussetzung|Nachweis|erforderlich)\b",
    I,
)


def _required_degree(claim: Claim) -> list[Raw]:
    if claim.field != "requirement":
        return []
    q = claim.quote
    spans = _sentences(q)
    out: list[Raw] = []
    for m in _DEGREE.finditer(q):
        tail = q[m.end() :]
        if re.match(
            r"(?:'s|s|’s)?\s+(?:programme|program|course|studies|study|Studiengang)",
            tail,
            I,
        ):
            continue
        subj = _DEGREE_SUBJECTS.match(tail)
        subjects: list[str] = []
        end = m.end()
        if subj:
            parts = re.split(
                r",|\s+or\s+|\s+and\s+|\s+oder\s+|\s+und\s+|/", subj.group(1), flags=I
            )
            subjects = [p for p in (_strip_lead(x) for x in parts) if p]
            if any(_NOT_SUBJECT.match(x) for x in subjects) or _EXEMPT_CTX.search(
                q[max(0, m.start() - 60) : m.start()]
            ):
                continue
            end = m.end() + subj.end(1)
        else:
            sa, sb = _sentence_of(spans, m.start())
            if not _REQ_CUE.search(q[sa:sb]):
                continue
        out.append(
            (
                "required_degree",
                RequiredDegree(level="bachelor", subjects=subjects),
                _ev(q, m.start(), end),
            )
        )
        break
    sm = _SCHOOL.search(q)
    if sm:
        out.append(
            (
                "required_degree",
                RequiredDegree(level="school_leaving", subjects=[]),
                _ev(q, sm.start(), sm.end()),
            )
        )
    return out


# ---------------------------------------------------------------- route / APS / restriction

_NEGATION_BEFORE = re.compile(
    r"\b(?:not|no|without|nicht|kein\w*|ohne|instead\s+of|rather\s+than|statt)\b[^.]{0,25}$",
    I,
)
_UNI_ASSIST = re.compile(
    r"(?:(?:via|through|using|über|per)\s+)?\buni[-‐‑]?assist\b", I
)
_VPD = re.compile(
    r"\bVPD\b|Vorprüfungsdokumentation|Preliminary\s+Review\s+Documentation", I
)
_PORTAL = re.compile(
    r"(?:via|through|using|über|per)\s+(?:the\s+|our\s+|its\s+|den\s+|das\s+)?(?:[A-Za-z][\w-]*\s+){0,3}?"
    r"(?:application\s+portal|online\s+portal|campus\s+portal|application\s+platform|"
    r"Bewerbungsportal|Online-Bewerbungsportal|Bewerbungsplattform)",
    I,
)
_DIRECT = re.compile(
    r"direct(?:ly)?\s+enrol{1,2}ment|Direkteinschreibung|Einschreibung\s+ohne\s+Bewerbung",
    I,
)


def _routes(claim: Claim) -> list[Raw]:
    q = claim.quote
    out: list[Raw] = []
    for route, rx in (
        ("uni_assist", _UNI_ASSIST),
        ("vpd", _VPD),
        ("university_portal", _PORTAL),
        ("direct_enrolment", _DIRECT),
    ):
        for m in rx.finditer(q):
            if _NEGATION_BEFORE.search(q[max(0, m.start() - 40) : m.start()]):
                continue
            out.append(
                (
                    "application_route",
                    ApplicationRoute(route=route),
                    _ev(q, m.start(), m.end()),
                )
            )
            break
    return out


_APS = re.compile(r"\bAPS\b(?:[- ](?:certificate|Zertifikat|Bescheinigung))?")
_APS_CUE = re.compile(
    r"certificate|Zertifikat|Bescheinigung|required|erforderlich|Pflicht|Prüfstelle|needed|must|submit|vorlegen|nachweis",
    I,
)
_COUNTRY_LIST = re.compile(
    r"(?:studied|graduated|obtained|from|in|aus|für)\s+"
    r"((?:[A-ZÄÖÜ][A-Za-zäöüß]+)(?:\s*(?:,|and|or|und|oder|&)\s*[A-ZÄÖÜ][A-Za-zäöüß]+)*)"
)


_COUNTRY_BEFORE = re.compile(
    r"(?i:applicants?|students?|graduates?|degrees?)\s+(?i:from|in|aus)\s+"
    r"((?:[A-ZÄÖÜ][A-Za-zäöüß]+)(?:\s*(?:,|and|or|und|oder|&)\s*[A-ZÄÖÜ][A-Za-zäöüß]+)*)"
    r"(?=[^.;]*\bAPS\b)"
)


def _aps(claim: Claim) -> list[Raw]:
    q = claim.quote
    spans = _sentences(q)
    for m in _APS.finditer(q):
        if _NEGATION_BEFORE.search(q[max(0, m.start() - 30) : m.start()]):
            continue
        sa, sb = _sentence_of(spans, m.start())
        if not _APS_CUE.search(q[sa:sb]) or _negated_at(q, spans, m.start()):
            continue
        countries: list[str] = []
        end = m.end()
        cm = _COUNTRY_LIST.search(q, m.end(), sb)
        if cm:
            countries = [
                c for c in re.split(r"\s*(?:,|and|or|und|oder|&)\s*", cm.group(1)) if c
            ]
            end = cm.end(1)
            if q[end : end + 1] == ")":
                end += 1
        start = m.start()
        if not countries:
            # "Applicants from India must submit the APS certificate"
            bm = _COUNTRY_BEFORE.search(q, sa, sb)
            if bm and bm.end(1) <= m.start():
                countries = [
                    c
                    for c in re.split(r"\s*(?:,|and|or|und|oder|&)\s*", bm.group(1))
                    if c
                ]
                start = bm.start()
        return [
            (
                "aps_required",
                ApsRequired(required=True, countries=countries),
                _ev(q, start, end),
            )
        ]
    return []


_RESTRICT_NEG = re.compile(
    r"no\s+admission\s+restriction|not\s+subject\s+to\s+(?:an?\s+)?admission\s+restriction|"
    r"without\s+(?:an?\s+)?admission\s+restriction|zulassungsfrei|keine\s+Zulassungsbeschränkung|"
    r"nicht\s+zulassungsbeschränkt|ohne\s+Zulassungsbeschränkung|no\s+numerus\s+clausus",
    I,
)
_RESTRICT_POS = re.compile(
    r"subject\s+to\s+(?:an?\s+)?admission\s+restriction|admission[- ]restricted|restricted\s+admission|"
    r"admission\s+restriction|numerus\s+clausus|zulassungsbeschränk(?:t|ung)(?:\s*\(NC\))?",
    I,
)


def _restricted(claim: Claim) -> list[Raw]:
    q = claim.quote
    neg_spans = [(m.start(), m.end()) for m in _RESTRICT_NEG.finditer(q)]
    out: list[Raw] = []
    if neg_spans:
        a, b = neg_spans[0]
        out.append(
            (
                "restricted_admission",
                RestrictedAdmission(restricted=False, basis=q[a:b]),
                _ev(q, a, b),
            )
        )
    for m in _RESTRICT_POS.finditer(q):
        if any(a <= m.start() < b for a, b in neg_spans):
            continue
        if _NEGATION_BEFORE.search(q[max(0, m.start() - 25) : m.start()]):
            continue
        out.append(
            (
                "restricted_admission",
                RestrictedAdmission(restricted=True, basis=m.group(0)),
                _ev(q, m.start(), m.end()),
            )
        )
        break
    return out


# ---------------------------------------------------------------- fees

_GROUP_CORE = (
    r"(?:(?:German|EU|EEA|EU/EEA|Non-EU|international|domestic)"
    r"(?:\s*(?:,|and|or|&|/)\s*(?:German|EU|EEA|EU/EEA|Non-EU|international|domestic))*"
    r"\s+(?:nationals|students|applicants|citizens|residents)|"
    r"(?:Nicht-EU|EU|deutsche|ausländische|internationale)[- ]?"
    r"(?:Studierende|Bürger\w*|Staatsangehörige|Bewerber\w*))\b"
)
_GRP = re.compile(r"\b" + _GROUP_CORE, I)
_GRP_FOR = re.compile(r"\s+(?:for|für)\s+(?P<g>" + _GROUP_CORE + ")", I)
_NUM = r"\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_MONEY = re.compile(
    rf"(?:(?:€|EUR(?![A-Za-z]))\s*({_NUM})|({_NUM})\s*(?:€|EUR(?![A-Za-z])|Euro(?![A-Za-z])))"
)
_CONN = r"\s*[:\-–]?\s*(?:of\s+|is\s+|are\s+|von\s+|ist\s+|sind\s+|beträgt\s+)?(?:[A-Za-z]\s+)?$"
_TOTAL_L = re.compile(
    r"(?:altogether|in\s+total|total(?:\s+(?:fees?|cost|amount))?|insgesamt|gesamt(?:betrag|summe|kosten)?|summe|zusammen|all\s+in\s+all)"
    + _CONN,
    I,
)
_TOTAL_R = re.compile(r"^\s*(?:in\s+total|total|insgesamt|gesamt)\b", I)
_TUI_L = re.compile(
    r"(?:(?:annual\s+|semester\s+)?tuition(?:\s+fees?)?|Studiengebühr(?:en)?)" + _CONN,
    I,
)
_TUI_R = re.compile(
    r"^\s*(?:of\s+)?(?:annual\s+|semester\s+)?tuition\b(?:\s+fees?)?|^\s*Studiengebühr(?:en)?",
    I,
)
_SEM_TERM = r"(?:semester\s+(?:fees?|contribution)|Semesterbeitrag|Semestergebühr|Sozialbeitrag|Studierendenschaftsbeitrag)"
_SEM_L = re.compile(_SEM_TERM + _CONN, I)
_SEM_R = re.compile(r"^\s*(?:of\s+)?" + _SEM_TERM, I)
_PER_SEM = re.compile(
    r"(?:per|each|every|pro|je|/)\s*(?:academic\s+)?semester|semesterly|jedes\s+Semester",
    I,
)
_PER_YEAR = re.compile(
    r"(?:per|each|every|pro|je|/)\s*(?:academic\s+|study\s+)?(?:year|annum|Studienjahr|Jahr)\b|annually|jährlich|\bp\.a\.",
    I,
)
_ONE_OFF = re.compile(r"one[- ]?(?:time|off)\b|einmalig|\bonce\b", I)
_OTHER_FEE = re.compile(
    r"application|Bewerbung|deposit|Kaution|visa|rent\b|housing|accommodation|Miete|uni-assist|insurance|Versicherung|admin",
    I,
)
_PERIODS = (("per_semester", _PER_SEM), ("per_year", _PER_YEAR), ("one_off", _ONE_OFF))


def _period_in(text: str, rx_list=_PERIODS):
    best = None
    for name, rx in rx_list:
        m = rx.search(text)
        if m and (best is None or m.start() < best[1]):
            best = (name, m.start(), m.end())
    return best


def _fees(claim: Claim) -> list[Raw]:
    if claim.field not in {"tuition", "semester_contribution", "requirement"}:
        return []
    q = claim.quote
    heads = list(_GRP.finditer(q))
    head_starts = [h.start() for h in heads]
    sections: list[tuple[int, int, str]] = []
    if not heads:
        sections.append((0, len(q), claim.applicant_group))
    else:
        if heads[0].start() > 0:
            sections.append((0, heads[0].start(), claim.applicant_group))
        for i, h in enumerate(heads):
            sections.append(
                (
                    h.start(),
                    heads[i + 1].start() if i + 1 < len(heads) else len(q),
                    h.group(0),
                )
            )

    def section_of(pos: int) -> int:
        for i, (a, b, _) in enumerate(sections):
            if a <= pos < b:
                return i
        return len(sections) - 1

    money = []
    for m in _MONEY.finditer(q):
        money.append((m.start(), m.end(), parse_amount(m.group(1) or m.group(2))))
    items = []  # dict per classified money
    consumed = 0
    for i, (s, e, amt) in enumerate(money):
        prev_end = money[i - 1][1] if i else 0
        left = q[max(prev_end, consumed) : s]
        for hs in heads:
            if max(prev_end, consumed) <= hs.end() <= s:
                left = q[hs.end() : s]
        left = re.split(r"(?<!\d)\.\s", left)[-1][-45:]
        nxt = money[i + 1][0] if i + 1 < len(money) else len(q)
        nxt = min([nxt, e + 45] + [h for h in head_starts if h >= e])
        right = re.split(r"(?<!\d)\.\s", q[e:nxt])[0]
        kind = term = None
        ev_start, ev_end = s, e
        for k, lrx, rrx in (
            ("total", _TOTAL_L, _TOTAL_R),
            ("tuition", _TUI_L, _TUI_R),
            ("semester_contribution", _SEM_L, _SEM_R),
        ):
            rm = rrx.match(right)
            lm = lrx.search(left)
            if rm:
                kind, ev_end = k, e + rm.end()
                consumed = e + rm.end()
                term = rm.group(0)
                break
            if lm:
                kind = k
                ev_start = s - (len(left) - lm.start())
                term = lm.group(0)
                break
        period = None
        pr = _period_in(right[:40])
        if pr:
            period = pr[0]
            ev_end = max(ev_end, e + pr[2])
        else:
            pl = re.search(
                r"(?:"
                + _PER_SEM.pattern
                + r"|"
                + _PER_YEAR.pattern
                + r")\s*[:\-–]?\s*$",
                left,
                I,
            )
            if pl:
                period = _period_in(pl.group(0))[0]
                ev_start = min(ev_start, s - (len(left) - pl.start()))
        if (
            kind == "semester_contribution"
            and period is None
            and term
            and "semester" in term.lower()
        ):
            period = "per_semester"
        items.append(
            dict(
                i=i,
                start=s,
                end=e,
                amount=amt,
                kind=kind,
                period=period,
                ev=(ev_start, ev_end),
                sec=section_of(s),
            )
        )

    # single unlabeled amount: use the claim.field as a hint, conservatively
    if (
        len(items) == 1
        and items[0]["kind"] is None
        and items[0]["period"]
        and not _OTHER_FEE.search(q)
    ):
        if claim.field in {"tuition", "semester_contribution"}:
            items[0]["kind"] = claim.field

    # inherit period from a section total when components add up to it
    for sec_idx in range(len(sections)):
        sec_items = [it for it in items if it["sec"] == sec_idx]
        totals = [it for it in sec_items if it["kind"] == "total" and it["period"]]
        if len(totals) == 1:
            comps = [it for it in sec_items if it is not totals[0]]
            if (
                comps
                and sum((c["amount"] for c in comps), Decimal(0)) == totals[0]["amount"]
            ):
                for c in comps:
                    c["period"] = c["period"] or totals[0]["period"]

    out: list[Raw] = []
    for it in items:
        if it["kind"] is None or it["period"] is None:
            continue
        out.append(
            (
                "fee_amount",
                FeeAmount(
                    amount_eur=format_amount(it["amount"]),
                    period=it["period"],
                    fee_type=it["kind"],
                    applicant_group=sections[it["sec"]][2],
                ),
                _ev(q, *it["ev"]),
            )
        )
    # explicit "no tuition fees"
    from .structured import _NO_FEE_RE

    zm = _NO_FEE_RE.search(q)
    if zm:
        group = sections[section_of(zm.start())][2]
        end = zm.end()
        gm = _GRP_FOR.match(q, zm.end())
        if gm:
            group, end = gm.group("g"), gm.end()
        out.append(
            (
                "fee_amount",
                FeeAmount(
                    amount_eur="0",
                    period=None,
                    fee_type="tuition",
                    applicant_group=group,
                ),
                _ev(q, zm.start(), zm.end()),
            )
        )
        _ = end
    return out


# ---------------------------------------------------------------- application windows

_MONTHS = {
    **{n: i + 1 for i, n in enumerate(
        ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
    )},
    **{n: i + 1 for i, n in enumerate(
        ["januar", "februar", "märz", "april", "mai", "juni", "juli", "august", "september", "oktober", "november", "dezember"]
    )},
    "jänner": 1, "maerz": 3,
    "jan": 1, "feb": 2, "mar": 3, "mär": 3, "mrz": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "okt": 10, "nov": 11, "dec": 12, "dez": 12,
}  # fmt: skip
_MON = "|".join(sorted(_MONTHS, key=len, reverse=True))
_DM = re.compile(
    rf"(?<![\d.])(\d{{1,2}})(?:st|nd|rd|th)?\.?\s*(?:of\s+)?({_MON})\b\.?(?:\s+(\d{{4}}))?",
    I,
)
_MD = re.compile(
    rf"\b({_MON})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?!\d)(?!\s*(?:%|ECTS|€))(?:,?\s+(\d{{4}}))?",
    I,
)
_NUMDATE = re.compile(r"(?<![\d.,])(\d{1,2})\.(0?[1-9]|1[0-2])\.(?:(\d{4})|(?!\d))")
_RANGE_SEP = re.compile(r"\s*(?:-|–|—|to|bis|until|through|till|thru)\s*", I)
_SEASON = re.compile(
    r"\b(winter|summer|wintersemester|sommersemester|wise|sose)\b(?:\s+(?:semester|term|intake))?(?!\s+(?:school|break|holidays?))",
    I,
)
_DEADLINE_CUE = re.compile(
    r"\b(?:\w*frist\w*|deadlines?|apply|applications?|bewerbung\w*|bewerben|received|submit\w*|einreich\w*|"
    r"registration|until|by|bis|spätestens|closing|anmeld\w*|periods?|zeitraum|window)\b",
    I,
)
_EXCLUDE = re.compile(
    r"\b(?:start(?:s|ing)?|begin(?:s|ning)?|commence\w*|lectures?|classes|orientation|early|late|optional|"
    r"extended|extension|interview|track|scholarship|portfolio|notification|decision|results?|refund|"
    r"exmatriculation)\b|Vorlesungs\w*|Semesterbeginn|Semesterstart|Nachfrist|Frühbewerb\w*|Stipendi\w*|"
    r"Nachrück\w*|Bescheid|Zusage|Rückmeld\w*",
    I,
)
_GROUPISH = re.compile(
    r"\b(?:non-?EU|EU|Nicht-EU|international|domestic|German|nationals?|applicants?|students?|"
    r"Bewerber\w*|Studierende\w*|Staatsangeh\w*|Ausländ\w*|Inländ\w*)\b",
    I,
)
_CONNECTOR_GAP = re.compile(
    r"[\s,;]*(?:and|or|und|oder)?[\s,;]*(?:by|bis|until)?[\s,;]*", I
)


def _valid_dm(day: int, month: int) -> bool:
    days = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return 1 <= month <= 12 and 1 <= day <= days[month - 1]


def _find_dates(q: str) -> list[tuple[int, int, int, int, str | None]]:
    found = []
    for m in _DM.finditer(q):
        found.append(
            (m.start(), m.end(), int(m.group(1)), _MONTHS[m.group(2).lower()], m.group(3))
        )
    for m in _MD.finditer(q):
        found.append(
            (m.start(), m.end(), int(m.group(2)), _MONTHS[m.group(1).lower()], m.group(3))
        )
    for m in _NUMDATE.finditer(q):
        found.append((m.start(), m.end(), int(m.group(1)), int(m.group(2)), m.group(3)))
    found.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    out: list[tuple[int, int, int, int, str | None]] = []
    for d in found:
        if out and d[0] < out[-1][1]:
            continue
        if _valid_dm(d[2], d[3]):
            out.append(d)
    return out


def _windows(claim: Claim) -> list[Raw]:
    q = claim.quote
    dates = _find_dates(q)
    if not dates:
        return []
    spans = _sentences(q)
    quote_seasons = {s.group(1).lower()[0] for s in _SEASON.finditer(q)}
    # merge ranges
    items: list[dict] = []
    i = 0
    while i < len(dates):
        d = dates[i]
        item = dict(start=d[0], end=d[1], s=None, e=(d[2], d[3], d[4]))
        if i + 1 < len(dates):
            n = dates[i + 1]
            gap = q[d[1] : n[0]]
            ok = bool(_RANGE_SEP.fullmatch(gap))
            if not ok and re.fullmatch(r"\s*(?:and|und)\s*", gap, I):
                ok = bool(
                    re.search(
                        r"(?:between|zwischen)\s+(?:the\s+)?$",
                        q[max(0, d[0] - 15) : d[0]],
                        I,
                    )
                )
            if ok:
                item.update(end=n[1], s=(d[2], d[3], d[4]), e=(n[2], n[3], n[4]))
                i += 1
        items.append(item)
        i += 1
    out: list[Raw] = []
    prev_excluded = False
    prev_item = None
    for k, it in enumerate(items):
        sa, sb = _sentence_of(spans, it["start"])
        same_prev = prev_item is not None and _sentence_of(
            spans, prev_item["start"]
        ) == (sa, sb)
        gap_start = prev_item["end"] if same_prev else sa
        gap = q[gap_start : it["start"]]
        if same_prev and _CONNECTOR_GAP.fullmatch(gap):
            excluded = prev_excluded
        else:
            label = gap
            last_season = None
            for sm in _SEASON.finditer(gap):
                last_season = sm
            if last_season:
                label = gap[last_season.end() :]
            if ")" in label:
                label = label.split(")")[-1]
            excluded = bool(_EXCLUDE.search(label[-80:]))
        prev_excluded, prev_item = excluded, it
        sentence = q[sa:sb]
        if excluded or not (
            claim.field == "deadline" or _DEADLINE_CUE.search(sentence)
        ):
            continue
        # group from a directly following parenthetical
        pm = re.match(r"\s*\(([^)]{2,60})\)", q[it["end"] :])
        group = claim.applicant_group
        ev_end = it["end"]
        if pm and _GROUPISH.search(pm.group(1)):
            group = pm.group(1).strip()
            ev_end = it["end"] + pm.end()
        # season
        next_start = (
            items[k + 1]["start"]
            if k + 1 < len(items) and items[k + 1]["start"] < sb
            else sb
        )
        sent_kws = list(_SEASON.finditer(q, sa, sb))
        season = None
        kw = None
        for sm in sent_kws:
            if (
                gap_start <= sm.start()
                and sm.end() <= it["start"]
                and re.match(r"\s*[:\-–—(]", q[sm.end() : it["start"]])
            ):
                season, kw = sm, sm
        if kw is None:
            after = [sm for sm in sent_kws if it["end"] <= sm.start() < next_start]
            if after:
                kw = after[0]
        if kw is None:
            before = [sm for sm in sent_kws if sm.end() <= it["start"]]
            if before and not any(
                items[j]["end"] > before[-1].start()
                for j in range(k)
                if items[j]["start"] >= sa
            ):
                kw = before[-1]
        season_val = "unknown"
        if kw is not None:
            season_val = "winter" if kw.group(1).lower().startswith("w") else "summer"
        else:
            sent_seasons = {sm.group(1).lower()[0] for sm in sent_kws}
            pool = sent_seasons or quote_seasons
            if len(pool) == 1:
                season_val = "winter" if next(iter(pool)) == "w" else "summer"
            elif not sent_seasons and len(quote_seasons) == 1:
                season_val = "winter" if next(iter(quote_seasons)) == "w" else "summer"
        ev_start = it["start"]
        cue = None
        for cm in _DEADLINE_CUE.finditer(gap):
            cue = cm
        if cue is not None:
            ev_start = min(ev_start, gap_start + cue.start())
        if kw is not None:
            ev_start = min(ev_start, kw.start())
            ev_end = max(ev_end, kw.end())
        s, e = it["s"], it["e"]
        out.append(
            (
                "application_window",
                ApplicationWindow(
                    season=season_val,
                    start=f"{s[0]:02d}-{s[1]:02d}" if s else None,
                    end=f"{e[0]:02d}-{e[1]:02d}",
                    applicant_group=group,
                    year=int(e[2] or (s[2] if s else None) or 0) or None,
                ),
                _ev(q, ev_start, ev_end),
            )
        )
        _ = season
    return out


# ---------------------------------------------------------------- public API

_EXTRACTORS = (
    _language_tests,
    _language_levels,
    _min_grade,
    _subject_ects,
    _required_degree,
    _routes,
    _aps,
    _restricted,
    _fees,
    _windows,
)


class RegexNormalizer:
    name = NORMALIZER_VERSION

    def normalize(self, claim_id: str, claim: Claim) -> list[StructuredFact]:
        facts: list[StructuredFact] = []
        for extractor in _EXTRACTORS:
            for kind, data, evidence in extractor(claim):
                if not evidence or evidence not in claim.quote:
                    continue
                try:
                    facts.append(
                        StructuredFact(
                            kind=kind,
                            data=data,
                            evidence_claim_ids=[claim_id],
                            evidence_text=evidence,
                            method=self.name,
                            applicant_group=claim.applicant_group,
                        )
                    )
                except ValidationError:
                    continue  # unverifiable against its own evidence: never emit
        return _dedupe(facts)


def _dedupe(facts: Iterable[StructuredFact]) -> list[StructuredFact]:
    merged: dict[tuple, StructuredFact] = {}
    for fact in facts:
        key = fact.key()
        if key in merged:
            ids = merged[key].evidence_claim_ids
            ids.extend(i for i in fact.evidence_claim_ids if i not in ids)
        else:
            merged[key] = fact.model_copy(deep=True)
    return list(merged.values())


def merge_facts(facts: Iterable[StructuredFact]) -> list[StructuredFact]:
    """Public dedupe: one fact per (kind, canonical data, scope); evidence ids merged."""
    return _dedupe(facts)


def superseded_windows(facts: Iterable[StructuredFact]) -> set[tuple]:
    """Keys of dated application windows replaced by a later year of the same window.

    Windows that differ only by year (same season, start, end, group) are one
    recurring cycle; the latest stated year is current, older ones are superseded so
    an expired deadline is never presented as current. Windows without a year are
    explicitly recurring and never superseded.
    """
    groups: dict[tuple, list[StructuredFact]] = {}
    for fact in facts:
        d = fact.data
        if fact.kind == "application_window" and d.year is not None:
            groups.setdefault(
                (d.season, d.start, d.end, d.applicant_group, fact.applicant_group), []
            ).append(fact)
    old: set[tuple] = set()
    for members in groups.values():
        latest = max(f.data.year for f in members)
        old.update(f.key() for f in members if f.data.year < latest)
    return old


DEFAULT_NORMALIZERS: tuple[Normalizer, ...] = (RegexNormalizer(),)


def normalize_claim(
    claim_id: str, claim: Claim, normalizers: Iterable[Normalizer] | None = None
) -> list[StructuredFact]:
    facts: list[StructuredFact] = []
    for normalizer in normalizers or DEFAULT_NORMALIZERS:
        facts.extend(normalizer.normalize(claim_id, claim))
    return _dedupe(facts)


def normalize_claims(
    pairs: Iterable[tuple[str, Claim]], normalizers: Iterable[Normalizer] | None = None
) -> list[StructuredFact]:
    """Normalise (claim_id, claim) pairs; identical facts merge their claim ids."""
    normalizers = tuple(normalizers or DEFAULT_NORMALIZERS)
    facts: list[StructuredFact] = []
    for claim_id, claim in pairs:
        facts.extend(normalize_claim(claim_id, claim, normalizers))
    return _dedupe(facts)
