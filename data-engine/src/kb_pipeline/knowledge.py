import json
from sqlalchemy import select
from .db import claims, facts, releases, jobs, runs, errors, uid, now
from .contracts import PipelineError


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
        rows = list(
            c.execute(select(claims).where(claims.c.run_id == run_id)).mappings()
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
