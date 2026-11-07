"""Offline, manually annotated development evaluations; never approve source facts."""

import hashlib
import json
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .acquire import parse, normal, PARSER_VERSION, MAX_BYTES
from .contracts import Claim, PipelineError
from .db import claims, jobs, runs, snapshots, now, uid
from .extract import classify, validate, CLASSIFIER_VERSION


class Label(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    expected: Literal["relevant", "other"]
    critical: bool = False
    reason: str
    block: dict | None = None


class ExpectedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    field: str
    location_id: str
    contains: list[str] = Field(min_length=1)
    critical: bool = True


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_id: str
    url: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    raw_path: str
    content_type: str
    observed_at: str
    parser: str


class Dataset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["evaluation-v1"]
    name: str = Field(pattern=r"^[a-z0-9-]+$")
    annotation: str
    source: Source | None = None
    cases: list[Label] = Field(min_length=2)
    expected_facts: list[ExpectedFact] = Field(default_factory=list)
    minimum_recall: float = Field(default=0.95, ge=0, le=1)
    minimum_precision: float = Field(default=0.70, ge=0, le=1)

    @model_validator(mode="after")
    def check_labels(self):
        if len({c.id for c in self.cases}) != len(self.cases):
            raise ValueError("Evaluation IDs must be unique")
        if {c.expected for c in self.cases} != {"relevant", "other"}:
            raise ValueError("Evaluation needs positive and negative examples")
        if any(c.critical and c.expected != "relevant" for c in self.cases):
            raise ValueError("Critical examples must be relevant")
        if len({f.id for f in self.expected_facts}) != len(self.expected_facts):
            raise ValueError("Expected fact IDs must be unique")
        return self


def load_dataset(path, directory):
    dataset = Dataset.model_validate_json(Path(path).read_text())
    if dataset.source:
        source = dataset.source
        if source.parser != PARSER_VERSION:
            raise PipelineError(
                "EVALUATION_VERSION_CHANGED",
                "Relabel the source after changing the parser",
            )
        root = Path(directory).resolve()
        raw = (root / source.raw_path).resolve()
        if not raw.is_relative_to(root) or not raw.is_file():
            raise PipelineError(
                "EVALUATION_SNAPSHOT_MISSING",
                "Retain the annotated snapshot under the local data directory; do not substitute a changed live page",
            )
        if raw.stat().st_size > MAX_BYTES:
            raise PipelineError(
                "EVALUATION_INPUT_TOO_LARGE",
                "Evaluation snapshot exceeds the source size limit",
            )
        content = raw.read_bytes()
        if hashlib.sha256(content).hexdigest() != source.sha256:
            raise PipelineError(
                "EVALUATION_SOURCE_CHANGED",
                "Snapshot hash differs from the manually annotated source",
            )
        document = parse(content, source.content_type, source.url)
    else:
        document = {"blocks": [c.block for c in dataset.cases if c.block is not None]}
    blocks = document["blocks"]
    if len(blocks) != len(dataset.cases) or {b["id"] for b in blocks} != {
        c.id for c in dataset.cases
    }:
        raise PipelineError(
            "EVALUATION_LABELS_MISMATCH",
            "Every parsed section needs exactly one manual label",
        )
    for block in blocks:
        if not isinstance(block.get("text"), str):
            raise PipelineError(
                "EVALUATION_BLOCK_INVALID", "Evaluation sections require text"
            )
    if any(
        f.location_id not in {b["id"] for b in blocks} for f in dataset.expected_facts
    ):
        raise PipelineError(
            "EVALUATION_LABELS_MISMATCH",
            "Expected fact locations must exist in the annotated document",
        )
    return dataset, document


def classifier_report(dataset, document):
    labels = {c.id: c for c in dataset.cases}
    counts = {
        "true_positive": 0,
        "false_positive": 0,
        "true_negative": 0,
        "false_negative": 0,
    }
    mismatches = []
    for block in document["blocks"]:
        label = labels[block["id"]]
        predicted = classify(block)
        positive = label.expected == "relevant"
        key = ("true_" if predicted == label.expected else "false_") + (
            "positive" if predicted == "relevant" else "negative"
        )
        counts[key] += 1
        if predicted != label.expected:
            mismatches.append(
                {
                    "id": label.id,
                    "expected": label.expected,
                    "predicted": predicted,
                    "critical": label.critical and positive,
                    "reason": label.reason,
                }
            )
    recall = counts["true_positive"] / (
        counts["true_positive"] + counts["false_negative"]
    )
    selected = counts["true_positive"] + counts["false_positive"]
    precision = counts["true_positive"] / selected if selected else 0
    critical_misses = [m["id"] for m in mismatches if m["critical"]]
    return {
        "kind": "classifier",
        "dataset": dataset.name,
        "classifier": CLASSIFIER_VERSION,
        "created_at": now(),
        "annotation": dataset.annotation,
        "sample_count": len(labels),
        "counts": counts,
        "precision": precision,
        "recall": recall,
        "critical_misses": critical_misses,
        "mismatches": mismatches,
        "thresholds": {
            "recall": dataset.minimum_recall,
            "precision": dataset.minimum_precision,
            "critical_misses": 0,
        },
        "passed": recall >= dataset.minimum_recall
        and precision >= dataset.minimum_precision
        and not critical_misses,
        "interpretation": "Manually annotated development regression; not a held-out estimate of country-wide accuracy",
    }


def extraction_report(store, run_id, dataset, document):
    if not dataset.source or not dataset.expected_facts:
        raise PipelineError(
            "EVALUATION_GOLD_MISSING",
            "Extraction evaluation requires snapshot provenance and expected facts",
        )
    source = dataset.source
    run = store.one(runs, id=run_id)
    config = json.loads(run["config"])
    source_jobs = store.rows(jobs, run_id=run_id)
    if (
        len(source_jobs) != 1
        or json.loads(source_jobs[0]["target"])["id"] != source.target_id
    ):
        raise PipelineError(
            "EVALUATION_RUN_MISMATCH",
            "Evaluate a run containing only the annotated programme",
        )
    job = source_jobs[0]
    if (
        not job["snapshot_id"]
        or store.one(snapshots, id=job["snapshot_id"])["hash"] != source.sha256
    ):
        raise PipelineError(
            "EVALUATION_SOURCE_CHANGED", "Run must use the exact annotated snapshot"
        )
    provider = config.get("model_config", {}).get("provider", "openrouter")
    rows = [
        r
        for r in store.rows(claims, run_id=run_id)
        # Follow-up pages carry their own snapshots and location ids.
        if r["snapshot_id"] == job["snapshot_id"]
        and json.loads(r["body"])["method"].startswith(provider + ":")
    ]
    parsed = [(r, Claim.model_validate_json(r["body"])) for r in rows]
    matches = []
    missing = []
    for expected in dataset.expected_facts:
        matched = []
        for row, claim in parsed:
            content = normal(claim.value + " " + (claim.conditions or "")).casefold()
            if (
                claim.field == expected.field
                and claim.location_id == expected.location_id
                and all(normal(s).casefold() in content for s in expected.contains)
            ):
                matched.append(row["id"])
        if matched:
            matches.append({"expected": expected.id, "claim_ids": matched})
        else:
            missing.append({"expected": expected.id, "critical": expected.critical})
    # Scope/semantic holds are not grounding failures; they stay held for review.
    allowed = {
        "valid",
        "MISSING_APPLICANT_SCOPE",
        "MISSING_INTAKE_SCOPE",
        "NOT_A_FACT",
        "APPLICANT_SCOPE_CONFLICT",
        "FOLLOWUP_PROGRAMME_UNVERIFIED",
    }
    invalid = [
        {
            "claim_id": r["id"],
            "validation": validate(c, document),
            "staged_validation": r["validation"],
        }
        for r, c in parsed
        if validate(c, document) not in allowed or r["validation"] not in allowed
    ]
    return {
        "kind": "extraction",
        "dataset": dataset.name,
        "created_at": now(),
        "run_id": run_id,
        "provider": provider,
        "model_claim_count": len(parsed),
        "expected_fact_coverage": len(matches) / len(dataset.expected_facts),
        "matches": matches,
        "missing": missing,
        "invalid_claims": invalid,
        "scope_held_claims": sum(
            r["validation"] in allowed - {"valid"} for r, _ in parsed
        ),
        "passed": bool(
            config["llm"]
            and parsed
            and job["status"] == "done"
            and run["status"] == "awaiting_review"
            and not missing
            and not invalid
        ),
        "interpretation": "Selected expected facts and verbatim grounding only; additional claims and semantic applicability still require human review. No publication or approval.",
    }


def save_report(directory, report):
    path = Path(directory) / "evaluations" / (uid() + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return str(path)
