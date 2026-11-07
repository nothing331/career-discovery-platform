"""Clause-type heuristics for ``requirement`` claims.

A ``requirement`` is only worth keeping as a candidate fact when it states an
*admission* condition (degree, language, grade, documents, tests such as APS/GRE,
aptitude, deadlines for applying). Verbatim examination-regulation clauses
(thesis, credits, modules, re-sits, fee payment at enrolment, ...) are true
statements about the programme but not admission facts, so they are held as
``NOT_A_FACT``. Anything that matches neither side stays valid (conservative).
"""

import re

CLAUSE_VERSION = "clauses-v1"
_I = re.I

# Strong admission-eligibility vocabulary; these win over regulation vocabulary.
_ELIGIBILITY = re.compile(
    r"\b(?:IELTS|TOEFL|TestDaF|DSH|telc|Cambridge|PTE|APS|GRE|GMAT|CEFR|aptitude|Eignung\w*|"
    r"Abitur|Hochschulreife|Hochschulzugang\w*|Zulassungsvoraussetzung\w*|Zugangsvoraussetzung\w*|"
    r"entrance\s+(?:qualification|examination|exam|test)|"
    r"admission\s+(?:requirements?|criteria|restriction|test|application|prerequisites?)|"
    r"language\s+(?:proficiency|certificates?|skills|requirements?|tests?)|"
    r"(?:German|English)[- ]language(?!\s+courses?)|your\s+(?:bachelor\W?s\s+|undergraduate\s+)?degree|degree\s+(?:must|should)|"
    r"(?:provisionally\s+admitted|provisional\s+admission|(?:admitted|admission)\s+to\s+(?:the\s+)?(?:relevant\s+)?(?:master|bachelor|programme|program|degree|university)|applicants?\s+(?:who|shall|must|may|should)|an?\s+applicant|"
    r"formal\s+admission)|command\s+of\s+(?:German|English)|"
    r"average\s+grade|final\s+grade\s+(?:of|for)\s+your|GPA|grade\s+point|"
    r"motivation\w*\s+letter|letter\s+of\s+motivation|curriculum\s+vitae|"
    r"letters?\s+of\s+recommendation|transcripts?|uni-?assist|passport|"
    r"documents?\s+required|proof\s+of|qualify\s+for\s+a\s+place|seeking\s+admission|"
    r"(?:part\s+of|time\s+of)\s+(?:the\s+|your\s+)?application|when\s+applying|"
    r"Bewerb\w*|Sprachkenntnisse|Sprachnachweis|Studienbewerber\w*)\b",
    _I,
)
# Admission-ish but weak: applicants/degree words also occur inside regulations.
_WEAK_ADMISSION = re.compile(
    r"\b(?:applicants?|admitted|admission|(?:bachelor|undergraduate|first)(?:'s|’s)?\s+degree|"
    r"university\s+degree)\b",
    _I,
)
# Regulation vocabulary: curriculum, examinations, credits, thesis, fee payment.
_REGULATION = re.compile(
    r"\b(?:thesis|dissertation\s+phase|examination\s+(?:board|office|regulations?)|Prüfungs\w+|"
    r"final\s+assessment|assessments?|fail\s+grade|re-?sits?|repeat\s+attempts?|"
    r"modules?|module\s+group|compulsory|mandatory\s+elective|ungraded|course\s+tutors?|tutors?|"
    r"curricul\w+|credits?\s+(?:shall|must|are|will|may)|\d+\s*(?:CP|LP)\b|"
    r"academic\s+(?:record|progress)|programme\s+requirements|study\s+regulations|"
    r"semester\s+fee|Semesterbeitrag|re-?regist\w+|exmatricul\w+|deregist\w+|"
    r"supervis\w+|grades?\s+(?:awarded|shall)|recognition\s+of|"
    r"Leistungspunkte\w*|Modulhandbuch|Studienplan)\b",
    _I,
)
# "Subsection 4", "paragraph 2", "Section 23(6)", "Absatz 3" ...
SUBSECTION_REF = re.compile(
    r"\b(?:sub-?sections?|paragraphs?|sections?|clauses?|items?|Absatz|Abs\.|Satz)\s+\d+",
    _I,
)
_NUMBERED = re.compile(r"^\s*(?:\(\d{1,2}\)|\d{1,2}[.)])\s+")


def clause_kind(text):
    """'admission' | 'regulation' | 'unknown' for a requirement block's text."""
    if _ELIGIBILITY.search(text):
        return "admission"
    if _REGULATION.search(text):
        return "regulation"
    if _WEAK_ADMISSION.search(text):
        return "admission"
    return "unknown"


def is_numbered_clause(text):
    return bool(_NUMBERED.match(text))


def refers_to_subsection(text):
    return bool(SUBSECTION_REF.search(text))


def requirement_hold(text):
    """Validation code a requirement block must be held with, or None.

    NOT_A_FACT: curriculum/exam/credit/thesis/fee-payment clause.
    INCOMPLETE_REQUIREMENT: admission-related numbered clause that depends on
    another subsection that is not part of the quote.
    """
    kind = clause_kind(text)
    if kind == "regulation":
        return "NOT_A_FACT"
    if is_numbered_clause(text) and refers_to_subsection(text):
        return "INCOMPLETE_REQUIREMENT" if kind == "admission" else "NOT_A_FACT"
    return None
