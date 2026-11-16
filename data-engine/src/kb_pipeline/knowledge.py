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
    snapshots,
    fingerprint,
    uid,
    now,
)
from .acquire import PARSER_VERSION, core_blocks
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


CARRIED = "carried-over"


def _evidence_hash(store, snapshot_hash, cache):
    """Hash of the parsed page text (headings + block text), or the raw-bytes hash
    when no parse is retained. Markup-only changes (tokens, timestamps) keep it.

    Only the blocks-v4 core counts: blocks-v5 adds key-fact blocks under new ids and
    never changes core blocks, so a decision on a core claim still holds - and an
    older v4 parse of an earlier snapshot compares equal to the new core."""
    if snapshot_hash not in cache:
        root = store.directory / "parsed" / snapshot_hash
        paths = [root / PARSER_VERSION / "document.json"] + [
            root / v / "document.json" for v in ("blocks-v4",) if v != PARSER_VERSION
        ]
        path = next((p for p in paths if p.exists()), None)
        if path is not None:
            blocks = core_blocks(json.loads(path.read_text())["blocks"])
            cache[snapshot_hash] = "text:" + fingerprint(
                [[b.get("heading", ""), b["text"]] for b in blocks]
            )
        else:
            cache[snapshot_hash] = "raw:" + snapshot_hash
    return cache[snapshot_hash]


def _versions_current(run):
    try:
        check_review_version(run)
        return True
    except PipelineError:
        return False


def carry_reviews(store, run_id):
    """Copy the latest human decision onto identical claims in a completed run.

    A claim matches only with the same programme, source URL, claim body (ignoring
    which extractor produced it), validation outcome, and identical parsed page text.
    Decisions come only from runs checked under the current extraction versions.
    Re-running is idempotent: carried decisions that no longer match go back to
    pending; decisions a human made in this run are never touched.
    """
    run = store.one(runs, id=run_id)
    if run["status"] != "awaiting_review" or store.rows(releases, run_id=run_id):
        return {"run_id": run_id, "carried": 0, "reset": 0}
    snaps = {s["id"]: s for s in store.rows(snapshots)}
    run_ok = {r["id"]: _versions_current(r) for r in store.rows(runs)}
    cache = {}

    def key(row):
        snap = snaps[row["snapshot_id"]]
        body = {k: v for k, v in json.loads(row["body"]).items() if k != "method"}
        return (
            row["entity_id"],
            snap["url"],
            json.dumps(body, sort_keys=True, ensure_ascii=False),
            row["validation"],
            _evidence_hash(store, snap["hash"], cache),
        )

    current = store.rows(claims, run_id=run_id)
    entities = {r["entity_id"] for r in current}
    priors = {}
    for entity in entities:
        for r in store.rows(claims, entity_id=entity):
            if (
                r["run_id"] == run_id
                or r["review"] not in ("approved", "rejected")
                or r["reviewer"] == CARRIED
                or not run_ok.get(r["run_id"])
            ):
                continue
            k = key(r)
            if k not in priors or (r["reviewed_at"] or "") > (
                priors[k]["reviewed_at"] or ""
            ):
                priors[k] = r
    carried = reset = 0
    for row in current:
        if row["review"] != "pending" and row["reviewer"] != CARRIED:
            continue
        prior = priors.get(key(row))
        if prior:
            if row["reviewer"] == CARRIED and row["review"] == prior["review"]:
                continue
            store.update(
                claims,
                row["id"],
                review=prior["review"],
                reviewer=CARRIED,
                review_note=(
                    f"Same page text and claim as {prior['id']} in run "
                    f"{prior['run_id']} ({prior['review']} by {prior['reviewer']})"
                    + (f": {prior['review_note']}" if prior["review_note"] else "")
                ),
                reviewed_at=now(),
            )
            carried += 1
        elif row["reviewer"] == CARRIED:
            store.update(
                claims,
                row["id"],
                review="pending",
                reviewer=None,
                review_note=None,
                reviewed_at=None,
            )
            reset += 1
    return {"run_id": run_id, "carried": carried, "reset": reset}


def bulk_review(store, run_id, reviewer, mode, note=""):
    """Apply review() to every pending claim of one kind in a run.

    mode "valid": approve pending claims whose validation is ``valid``.
    mode "held":  reject pending claims whose validation is not ``valid`` (note required).
    Each claim goes through the normal review() checks and is recorded individually.
    """
    if mode not in ("valid", "held"):
        raise PipelineError("REVIEW_INVALID", "mode must be 'valid' or 'held'")
    decision = "approved" if mode == "valid" else "rejected"
    with store.engine.connect() as c:
        pending = [
            r
            for r in c.execute(select(claims).where(claims.c.run_id == run_id)).mappings()
            if r["review"] == "pending" and (r["validation"] == "valid") == (mode == "valid")
        ]
    for r in pending:
        review(store, r["id"], reviewer, decision, note)
    return {"run_id": run_id, "decision": decision, "count": len(pending)}


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
