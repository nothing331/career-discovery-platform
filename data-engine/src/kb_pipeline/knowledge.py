import json
from sqlalchemy import select
from .db import (
    claims,
    facts,
    releases,
    jobs,
    runs,
    errors,
    structured,
    kb_structured,
    uid,
    now,
)
from .contracts import PipelineError
from .extract import EXTRACTOR_VERSION, SCHEMA_VERSION
from .grounding import GROUNDING_VERSION


def check_review_version(run):
    config = json.loads(run["config"])
    if (
        config.get("extractor") != EXTRACTOR_VERSION
        or config.get("schema") != SCHEMA_VERSION
        or config.get("grounder") != GROUNDING_VERSION
    ):
        raise PipelineError(
            "REVIEW_VERSION_CHANGED",
            "Create a new extraction/replay under the current checks before approving or publishing older candidates",
        )


def _newer_run(c, run, entity_ids):
    """Newest-first search for a later reviewable run that re-collected an entity."""
    newer = c.execute(
        select(runs)
        .where(
            runs.c.created_at > run["created_at"],
            runs.c.status.in_(("awaiting_review", "published")),
        )
        .order_by(runs.c.created_at.desc())
    ).mappings()
    for later in list(newer):
        for job in c.execute(
            select(jobs).where(jobs.c.run_id == later["id"], jobs.c.status == "done")
        ).mappings():
            if json.loads(job["target"])["id"] in entity_ids:
                return later["id"]
    return None


def superseding_run(store, run_id):
    """ID of a newer completed run covering any entity of this run, else None."""
    with store.engine.connect() as c:
        run = c.execute(select(runs).where(runs.c.id == run_id)).mappings().one()
        entities = {
            r[0]
            for r in c.execute(
                select(claims.c.entity_id).where(claims.c.run_id == run_id)
            )
        }
        return _newer_run(c, run, entities)


def review(store, claim_id, reviewer, decision, note=""):
    if not reviewer.strip() or decision not in ("approved", "rejected"):
        raise PipelineError(
            "REVIEW_INVALID", "Reviewer and approved/rejected decision required"
        )
    with store.engine.begin() as c:
        row = (
            c.execute(select(claims).where(claims.c.id == claim_id))
            .mappings()
            .one_or_none()
        )
        if not row:
            raise PipelineError("NOT_FOUND", "Claim not found")
        run = c.execute(select(runs).where(runs.c.id == row["run_id"])).mappings().one()
        if run["status"] != "awaiting_review":
            raise PipelineError(
                "RUN_NOT_REVIEWABLE", "Wait for collection to finish before reviewing"
            )
        if decision == "approved":
            check_review_version(run)
            if _newer_run(c, run, {row["entity_id"]}):
                raise PipelineError(
                    "RUN_SUPERSEDED",
                    "A newer completed run exists for this programme; review that run instead",
                )
        if c.execute(
            select(releases).where(releases.c.run_id == row["run_id"])
        ).first():
            raise PipelineError(
                "RELEASE_IMMUTABLE",
                "Published review history cannot be edited; collect a new version",
            )
        if decision == "approved" and row["validation"] != "valid":
            raise PipelineError(
                "CLAIM_HELD",
                "Resolve evidence/scope problems in a new extraction before approval",
            )
        if decision == "rejected" and not note.strip():
            raise PipelineError(
                "REVIEW_NOTE_REQUIRED",
                "Explain rejected claims and accepted coverage gaps",
            )
        c.execute(
            claims.update()
            .where(claims.c.id == claim_id)
            .values(
                review=decision,
                reviewer=reviewer.strip(),
                review_note=note,
                reviewed_at=now(),
            )
        )


def publish(store, run_id):
    # One atomic release. Readers never observe a partially published run.
    with store.engine.connect() as c:
        c.exec_driver_sql("BEGIN IMMEDIATE")
        run = (
            c.execute(select(runs).where(runs.c.id == run_id)).mappings().one_or_none()
        )
        if not run or run["status"] != "awaiting_review":
            raise PipelineError(
                "RUN_NOT_REVIEWABLE", "Only completed collection runs can be published"
            )
        check_review_version(run)
        rows = list(
            c.execute(select(claims).where(claims.c.run_id == run_id)).mappings()
        )
        # Only programmes being published can be superseded; a run with nothing
        # approved cannot publish, so report supersession for all its entities.
        scope = {r["entity_id"] for r in rows if r["review"] == "approved"} or {
            r["entity_id"] for r in rows
        }
        if _newer_run(c, run, scope):
            raise PipelineError(
                "RUN_SUPERSEDED",
                "A newer completed run exists for this programme; publish that run instead",
            )
        if not rows or any(r["review"] == "pending" for r in rows):
            raise PipelineError(
                "REVIEW_INCOMPLETE",
                "Every candidate requires an explicit review decision",
            )
        approved = [r for r in rows if r["review"] == "approved"]
        if not approved or any(
            r["validation"] != "valid" or not r["reviewer"] for r in approved
        ):
            raise PipelineError("CLAIM_HELD", "No valid approved claims to publish")
        entities = {r["entity_id"] for r in approved}
        for entity in entities:
            if not any(
                r["entity_id"] == entity
                and json.loads(r["body"])["field"] == "programme_title"
                for r in approved
            ):
                raise PipelineError(
                    "IDENTITY_NOT_REVIEWED",
                    "Each published programme needs a reviewed title",
                )
        release = uid()
        c.execute(releases.insert().values(id=release, run_id=run_id, created_at=now()))
        from .db import snapshots

        evidence_by_claim = {}
        for row in approved:
            job = (
                c.execute(select(jobs).where(jobs.c.id == row["job_id"]))
                .mappings()
                .one()
            )
            snapshot = (
                c.execute(select(snapshots).where(snapshots.c.id == row["snapshot_id"]))
                .mappings()
                .one()
            )
            body = json.loads(row["body"])
            q = json.loads(row["quality"])
            q["components"]["verification"] = 10
            q["score"] = sum(q["components"].values())
            q["reasons"] = [x for x in q["reasons"] if x != "Human review pending"]
            evidence = {
                "snapshot_id": snapshot["id"],
                "source_url": snapshot["url"],
                "observed_at": snapshot["observed_at"],
                "source_hash": snapshot["hash"],
                "quote": body["quote"],
                "location_id": body["location_id"],
                "reviewer": row["reviewer"],
                "reviewed_at": row["reviewed_at"],
                "quality": q,
            }
            evidence_by_claim[row["id"]] = evidence
            c.execute(
                facts.insert().values(
                    id=uid(),
                    release_id=release,
                    claim_id=row["id"],
                    entity_id=row["entity_id"],
                    target=job["target"],
                    body=row["body"],
                    evidence=json.dumps(evidence, ensure_ascii=False),
                )
            )
        # Structured facts publish only when every claim they rest on was approved.
        for sf in c.execute(
            select(structured).where(structured.c.run_id == run_id)
        ).mappings():
            ids = json.loads(sf["evidence_claim_ids"])
            if sf["review"] == "superseded":
                continue  # an older year of the same window; never published as current
            if not ids or any(i not in evidence_by_claim for i in ids):
                continue
            c.execute(
                kb_structured.insert().values(
                    id=uid(),
                    release_id=release,
                    entity_id=sf["entity_id"],
                    kind=sf["kind"],
                    data=sf["data"],
                    evidence=json.dumps(
                        {
                            "claim_ids": ids,
                            "evidence_text": sf["evidence_text"],
                            "applicant_group": sf["applicant_group"],
                            "claims": [evidence_by_claim[i] for i in ids],
                        },
                        ensure_ascii=False,
                    ),
                    method=sf["method"],
                )
            )
        c.execute(runs.update().where(runs.c.id == run_id).values(status="published"))
        c.commit()
    return release


def catalogue(store, *, country=None, level=None, entity=None):
    with store.engine.connect() as c:
        rows = c.execute(
            select(
                facts, releases.c.created_at, releases.c.run_id.label("release_run_id")
            )
            .join(releases, facts.c.release_id == releases.c.id)
            .order_by(releases.c.created_at.desc())
        ).mappings()
        programmes = {}
        for row in rows:
            target = json.loads(row["target"])
            if (
                country
                and target["country"] != country
                or level
                and target["level"] != level
                or entity
                and row["entity_id"] != entity
            ):
                continue
            existing = programmes.get(row["entity_id"])
            if existing and existing["release_id"] != row["release_id"]:
                continue
            if not existing:
                existing = programmes[row["entity_id"]] = {
                    "id": row["entity_id"],
                    "institution": target["institution"],
                    "level": target["level"],
                    "country": target["country"],
                    "release_id": row["release_id"],
                    "collection_run_id": row["release_run_id"],
                    "freshness_status": "effective_dates_unverified",
                    "facts": [],
                    "structured": [],
                    "unknown_fields": [],
                    "eligibility_assessment": "not implemented",
                }
            body = json.loads(row["body"])
            existing["facts"].append(
                {
                    "claim_id": row["claim_id"],
                    **body,
                    "evidence": json.loads(row["evidence"]),
                }
            )
        for p in programmes.values():
            for sf in c.execute(
                select(kb_structured).where(
                    kb_structured.c.release_id == p["release_id"],
                    kb_structured.c.entity_id == p["id"],
                )
            ).mappings():
                p["structured"].append(
                    {
                        "id": sf["id"],
                        "kind": sf["kind"],
                        "data": json.loads(sf["data"]),
                        "method": sf["method"],
                        "evidence": json.loads(sf["evidence"]),
                    }
                )
            present = {f["field"] for f in p["facts"]}
            p["unknown_fields"] = sorted(
                {
                    "duration_semesters",
                    "ects",
                    "teaching_language",
                    "tuition",
                    "semester_contribution",
                    "deadline",
                    "requirement",
                }
                - present
            )
        return list(programmes.values())


def list_structured(store, run_id):
    """Staged structured facts of a run with whether all their evidence is approved."""
    review_by_claim = {c["id"]: c["review"] for c in store.rows(claims, run_id=run_id)}
    out = []
    for r in store.rows(structured, run_id=run_id):
        ids = json.loads(r["evidence_claim_ids"])
        out.append(
            {
                "id": r["id"],
                "entity_id": r["entity_id"],
                "kind": r["kind"],
                "data": json.loads(r["data"]),
                "applicant_group": r["applicant_group"],
                "review": r["review"],
                "evidence_text": r["evidence_text"],
                "evidence_claim_ids": ids,
                "method": r["method"],
                "all_evidence_approved": bool(ids)
                and all(review_by_claim.get(i) == "approved" for i in ids),
            }
        )
    return out


def resolve_error(store, error_id, replay_run_id, actor, note):
    """Resolve an engine bug only after a successful linked replay, never approve facts."""
    from .logging import RunLog

    error = store.one(errors, id=error_id)
    run = store.one(runs, id=replay_run_id)
    if not actor.strip() or not note.strip():
        raise PipelineError(
            "RESOLUTION_NOTE_REQUIRED", "Actor and verification note required"
        )
    replay_jobs = store.rows(jobs, run_id=replay_run_id)
    if (
        run["parent_error_id"] != error_id
        or not replay_jobs
        or any(j["status"] != "done" for j in replay_jobs)
    ):
        raise PipelineError(
            "REPLAY_NOT_VERIFIED",
            "Resolution requires a completed replay linked to this error",
        )
    if any(
        e["stage"] == error["stage"] and e["code"] == error["code"]
        for e in store.rows(errors, run_id=replay_run_id)
    ):
        raise PipelineError(
            "ERROR_STILL_PRESENT", "The replay still reports the original failure"
        )
    log = RunLog(store, replay_run_id)
    try:
        log.emit(
            "error.resolved",
            error_id=error_id,
            original_run_id=error["run_id"],
            actor=actor,
            note=note,
        )
    finally:
        log.close()
    store.update(errors, error_id, status="resolved")
