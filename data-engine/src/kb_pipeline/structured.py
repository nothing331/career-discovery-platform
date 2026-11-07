"""Typed second layer next to the verbatim claims.

Every StructuredFact is derived from exactly the verbatim quote of one or more
claims and carries ``evidence_text``: the exact substring of that quote which
supports it. Numeric/score values must literally appear inside that evidence.
The producing method is recorded so other normalisers (an LLM one later) can
plug in beside the regex one.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

NORMALIZER_VERSION = "regex-v3"

Language = Literal["english", "german"]
FactKind = Literal[
    "language_test",
    "language_level",
    "min_grade",
    "subject_ects_min",
    "required_degree",
    "application_route",
    "aps_required",
    "restricted_admission",
    "fee_amount",
    "application_window",
]

_NUM_RE = re.compile(r"\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?")
_NO_FEE_RE = re.compile(
    r"\bno\s+tuition\s+fees?\b|\bkeine\s+Studiengeb(?:ü|ue)hren\b|\bstudiengeb(?:ü|ue)hrenfrei\b",
    re.I,
)


def parse_amount(text: str) -> Decimal:
    """Parse '190', '1500', '1.500', '1,500', '158,50', '1.234,56' to Decimal."""
    if "." in text and "," in text:
        cut = max(text.rfind("."), text.rfind(","))
        return Decimal(re.sub(r"[.,]", "", text[:cut]) + "." + text[cut + 1 :])
    for sep in ".,":
        if sep in text:
            parts = text.split(sep)
            if len(parts) > 2 or len(parts[-1]) == 3:
                return Decimal("".join(parts))
            return Decimal(parts[0] + "." + parts[1])
    return Decimal(text)


def format_amount(value: Decimal) -> str:
    """Canonical Decimal-as-string: integers bare, otherwise two decimals."""
    return str(int(value)) if value == value.to_integral_value() else f"{value:.2f}"


def _appears(value: str, evidence: str) -> bool:
    return any(
        v in evidence for v in (value, value.replace(".", ","), value.replace(",", "."))
    )


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LanguageTest(_Model):
    test: Literal[
        "IELTS",
        "TOEFL_IBT",
        "TOEFL_ESSENTIALS",
        "PTE",
        "CAMBRIDGE",
        "TESTDAF",
        "DSH",
        "TELC",
        "OTHER",
    ]
    min_score: str | None = None
    language: Language


class LanguageLevel(_Model):
    language: Language
    cefr: Literal["A1", "A2", "B1", "B2", "C1", "C2"]
    strength: Literal["required", "recommended"]


class MinGrade(_Model):
    value: str
    scale: Literal["DE_1_TO_4", "UNKNOWN"]
    alternative: str | None = None


class SubjectEcts(_Model):
    min_ects: int = Field(gt=0)
    subject: str = Field(min_length=1)


class RequiredDegree(_Model):
    level: Literal["bachelor", "school_leaving", "other"]
    subjects: list[str] = Field(default_factory=list)


class ApplicationRoute(_Model):
    route: Literal["uni_assist", "university_portal", "direct_enrolment", "vpd"]


class ApsRequired(_Model):
    required: bool
    countries: list[str] = Field(default_factory=list)


class RestrictedAdmission(_Model):
    restricted: bool
    basis: str = Field(min_length=1)


class FeeAmount(_Model):
    amount_eur: str = Field(pattern=r"^\d+(\.\d{2})?$")
    # None is only legal for an explicit zero ("no tuition fees"), which has no period.
    period: Literal["per_semester", "per_year", "one_off"] | None
    fee_type: Literal["tuition", "semester_contribution", "total", "component"]
    applicant_group: str

    @model_validator(mode="after")
    def period_needed_unless_zero(self):
        if self.period is None and Decimal(self.amount_eur) != 0:
            raise ValueError("period is required for a non-zero fee")
        return self


class ApplicationWindow(_Model):
    season: Literal["winter", "summer", "unknown"]
    start: str | None = Field(
        default=None, pattern=r"^(0[1-9]|[12]\d|3[01])-(0[1-9]|1[0-2])$"
    )
    end: str = Field(pattern=r"^(0[1-9]|[12]\d|3[01])-(0[1-9]|1[0-2])$")
    applicant_group: str
    # Calendar year of the end date when the source states one ("by July 31, 2025").
    # None means an explicitly recurring window (day+month only).
    year: int | None = Field(default=None, ge=1990, le=2100)


FactData = Union[
    LanguageTest,
    LanguageLevel,
    MinGrade,
    SubjectEcts,
    RequiredDegree,
    ApplicationRoute,
    ApsRequired,
    RestrictedAdmission,
    FeeAmount,
    ApplicationWindow,
]

KIND_MODELS: dict[str, type[_Model]] = {
    "language_test": LanguageTest,
    "language_level": LanguageLevel,
    "min_grade": MinGrade,
    "subject_ects_min": SubjectEcts,
    "required_degree": RequiredDegree,
    "application_route": ApplicationRoute,
    "aps_required": ApsRequired,
    "restricted_admission": RestrictedAdmission,
    "fee_amount": FeeAmount,
    "application_window": ApplicationWindow,
}


def _day_in(day_month: str, evidence: str) -> bool:
    return bool(re.search(rf"(?<!\d)0?{int(day_month[:2])}(?!\d)", evidence))


class StructuredFact(_Model):
    kind: FactKind
    data: FactData
    evidence_claim_ids: list[str] = Field(min_length=1)
    evidence_text: str = Field(min_length=1)
    method: str = NORMALIZER_VERSION
    # The source claim's applicant_group (provenance); fee/window data carry their own.
    applicant_group: str | None = None

    @model_validator(mode="before")
    @classmethod
    def data_by_kind(cls, value):
        if isinstance(value, dict) and isinstance(value.get("data"), dict):
            model = KIND_MODELS.get(value.get("kind"))
            if model is not None:
                value = {**value, "data": model.model_validate(value["data"])}
        return value

    @model_validator(mode="after")
    def grounded_in_evidence(self):
        data, ev = self.data, self.evidence_text
        if not isinstance(data, KIND_MODELS[self.kind]):
            raise ValueError(f"data does not match kind {self.kind}")
        cf = ev.casefold()
        if isinstance(data, LanguageTest) and data.min_score:
            if not _appears(data.min_score, ev):
                raise ValueError(f"score {data.min_score!r} not in evidence_text")
        elif isinstance(data, LanguageLevel):
            if data.cefr not in ev.upper():
                raise ValueError(f"level {data.cefr!r} not in evidence_text")
        elif isinstance(data, MinGrade):
            if not _appears(data.value, ev):
                raise ValueError(f"grade {data.value!r} not in evidence_text")
            if data.alternative and data.alternative.casefold() not in cf:
                raise ValueError("alternative not in evidence_text")
        elif isinstance(data, SubjectEcts):
            if not re.search(rf"(?<!\d){data.min_ects}(?!\d)", ev):
                raise ValueError(f"{data.min_ects} not in evidence_text")
            if data.subject.casefold() not in cf:
                raise ValueError("subject not in evidence_text")
        elif isinstance(data, RequiredDegree):
            if any(s.casefold() not in cf for s in data.subjects):
                raise ValueError("subject not in evidence_text")
        elif isinstance(data, ApsRequired):
            if any(c.casefold() not in cf for c in data.countries):
                raise ValueError("country not in evidence_text")
        elif isinstance(data, RestrictedAdmission):
            if data.basis.casefold() not in cf:
                raise ValueError("basis not in evidence_text")
        elif isinstance(data, FeeAmount):
            amount = Decimal(data.amount_eur)
            if amount == 0 and _NO_FEE_RE.search(ev):
                pass
            else:
                found = set()
                for token in _NUM_RE.findall(ev):
                    try:
                        found.add(parse_amount(token))
                    except InvalidOperation:
                        pass
                if amount not in found:
                    raise ValueError(f"amount {data.amount_eur!r} not in evidence_text")
        elif isinstance(data, ApplicationWindow):
            for part in (data.start, data.end):
                if part and not _day_in(part, ev):
                    raise ValueError(f"day of {part!r} not in evidence_text")
            if data.year is not None and str(data.year) not in ev:
                raise ValueError(f"year {data.year} not in evidence_text")
        return self

    def grounded_in_quote(self, quote: str) -> bool:
        """True when evidence_text is a verbatim substring of the claim quote."""
        return self.evidence_text in quote

    def key(self) -> tuple:
        """Identity used for dedupe: (kind, canonical data, provenance scope).

        Different wordings of the same fact ("DSH -2" / "DSH -2 C1 CEFR ; DSH -2")
        collapse into one; their evidence claim ids are merged, not compared.
        """
        return (self.kind, self.data.model_dump_json(), self.applicant_group)
