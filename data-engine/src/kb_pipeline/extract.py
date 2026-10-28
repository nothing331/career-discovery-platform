"""Conservative rules and exact-evidence checks. No admissions decisions."""

import re
from .contracts import Claim
from .acquire import normal

EXTRACTOR_VERSION = "rules-v2"
SCHEMA_VERSION = "claims-v1"
PROMPT_VERSION = "grounded-v1"


def classify(block):
    text = (block.get("heading", "") + " " + block["text"]).lower()
    return (
        "relevant"
        if re.search(
            r"admission|requirement|prerequis|fee|tuition|duration|semester|ects|language|deadline|zulassung|bewerbung|gebühr|sprach",
            text,
        )
        else "other"
    )


def rule_claims(document, target):
    result = []

    def add(field, value, block, conditions=None):
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
                applicant_group=target.applicant_group,
                intake=target.intake,
                conditions=conditions,
                method=EXTRACTOR_VERSION,
            )
        )

    title = next(
        (b for b in document["blocks"] if b["location"].get("tag") == "h1"), None
    )
    if title:
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
                )
        if (
            classify(b) == "relevant"
            and b["location"].get("tag") in ("p", "li")
            and re.search(
                r"must|required|requirement|prerequisite|voraussetzung|nachweis",
                text,
                re.I,
            )
            and len(text) <= 3000
        ):
            add(
                "requirement",
                text,
                b,
                conditions="Verbatim requirement text; not an executable eligibility rule",
            )
    return result


def validate(claim, document):
    block = next((b for b in document["blocks"] if b["id"] == claim.location_id), None)
    if not block or normal(claim.quote) not in normal(block["text"]):
        return "EVIDENCE_NOT_FOUND"
    if normal(claim.value).casefold() not in normal(claim.quote).casefold():
        return "VALUE_NOT_GROUNDED"
    if claim.field in ("duration_semesters", "ects") and (
        not claim.value.isdecimal() or not 1 <= int(claim.value) <= 1000
    ):
        return "INVALID_NUMERIC_VALUE"
    if claim.field == "deadline" and not claim.intake:
        return "MISSING_INTAKE_SCOPE"
    if claim.field in (
        "tuition",
        "semester_contribution",
        "requirement",
    ) and claim.applicant_group in ("", "not established", "unknown"):
        return "MISSING_APPLICANT_SCOPE"
    return "valid"


def quality(claim, status):
    scope = claim.applicant_group not in ("", "unknown", "not established") and (
        claim.field != "deadline" or claim.intake is not None
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
