from typing import Literal
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    model_validator,
    field_validator,
)

UNKNOWN_SCOPE = {
    "",
    "unknown",
    "not established",
    "not specified",
    "not provided",
    "unspecified",
    "null",
    "none",
    "n/a",
}

GENERAL_SCOPE = "general (no specific applicant group stated)"
RECURRING_INTAKES = {"winter semester (recurring)", "summer semester (recurring)"}


def scope_known(value):
    return (
        isinstance(value, str)
        and " ".join(value.split()).casefold() not in UNKNOWN_SCOPE
    )


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    institution: str
    programme: str
    level: Literal["bachelor", "master"]
    country: Literal["DE"] = "DE"
    url: HttpUrl
    allowed_hosts: list[str]
    applicant_group: str = "not established"
    intake: str | None = None
    # Depth-1 crawl of admissions-relevant same-host links from the programme page.
    follow_links: bool = True


class Registry(BaseModel):
    country: str
    subject: str
    institutions: list[str]
    targets: list[Target]

    @model_validator(mode="after")
    def unique(self):
        if len({t.id for t in self.targets}) != len(self.targets):
            raise ValueError("Duplicate target IDs")
        return self


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: Literal[
        "programme_title",
        "duration_semesters",
        "ects",
        "teaching_language",
        "tuition",
        "semester_contribution",
        "deadline",
        "requirement",
    ]
    value: str = Field(
        min_length=1,
        max_length=3000,
        description="Copy source text. duration_semesters and ects contain digits only, e.g. '4', '120'. For requirement copy the entire block text, preserving alternatives and exceptions.",
    )
    quote: str = Field(
        min_length=4,
        max_length=4000,
        description="Verbatim supporting block text, including its conditions and exceptions.",
    )
    location_id: str
    # Unknown applicability is explicit, never inferred from an institution-wide label.
    applicant_group: str = Field(
        description="The explicitly stated applicant group; or exactly 'general (no specific applicant group stated)' when the block states no group at all; or exactly 'not established' when the block mentions applicant groups ambiguously. Never infer nationality."
    )
    intake: str | None = Field(
        description="Explicit source-backed intake including a year; or, for a recurring day+month date tied to a semester with no year, exactly 'winter semester (recurring)' or 'summer semester (recurring)'; otherwise actual JSON null. Never invent a year. Never the string 'null', 'unknown' or 'not established'."
    )
    conditions: str | None = Field(
        description="Copy applicability, alternatives and exceptions from the source, or actual JSON null when none are stated."
    )
    method: str = "rules"

    @field_validator("intake", "conditions", mode="before")
    @classmethod
    def canonical_null(cls, value):
        return (
            None
            if value is None or isinstance(value, str) and not scope_known(value)
            else value
        )

    @field_validator("applicant_group", mode="before")
    @classmethod
    def canonical_applicants(cls, value):
        return value if scope_known(value) else "not established"


class Batch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[Claim] = Field(max_length=50)


class PipelineError(Exception):
    def __init__(self, code, message, *, retryable=False):
        super().__init__(message)
        self.code, self.retryable = code, retryable
