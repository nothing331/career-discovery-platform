from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


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
    value: str = Field(min_length=1, max_length=3000)
    quote: str = Field(min_length=4, max_length=4000)
    location_id: str
    # Unknown applicability is explicit, never inferred from an institution-wide label.
    applicant_group: str
    intake: str | None
    conditions: str | None
    method: str = "rules"


class Batch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[Claim] = Field(max_length=50)


class PipelineError(Exception):
    def __init__(self, code, message, *, retryable=False):
        super().__init__(message)
        self.code, self.retryable = code, retryable
