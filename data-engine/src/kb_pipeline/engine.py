import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import time
from sqlalchemy import select
from .config import Settings
from .contracts import Target, Registry, Claim, PipelineError
from .db import (
    Store,
    runs,
    jobs,
    snapshots,
    errors,
    claims,
    releases,
    facts,
    uid,
    now,
    fingerprint,
)
from .logging import RunLog
from .acquire import Fetcher, parse, PARSER_VERSION
from .extract import (
    rule_claims,
    classify,
    validate,
    quality,
    EXTRACTOR_VERSION,
    SCHEMA_VERSION,
)
from .openrouter import OpenRouter

STOP_CODES = {
    "BUDGET_EXHAUSTED",
    "MODEL_KEY_MISSING",
    "MODEL_BILLING_UNCERTAIN",
    "MODEL_TRANSPORT",
    "MODEL_RATE_LIMIT",
    "MODEL_PRICE_OVERRUN",
    "MODEL_AUTH_FAILED",
    "MODEL_CREDITS_MISSING",
}


class Engine:
    def __init__(
        self,
        settings=None,
        *,
        store=None,
        fetch_client=None,
        model_client=None,
        sleep=time.sleep,
    ):
        self.settings = settings or Settings.load()
        self.store = store or Store(self.settings.data_dir)
        self.fetch_client, self.model_client, self.sleep = (
            fetch_client,
            model_client,
            sleep,
        )

    def registry(self):
        return Registry.model_validate_json(self.settings.registry.read_text())

    def enqueue(
        self,
        *,
        targets=None,
        llm=False,
        budget=None,
        parent_error=None,
        snapshot_id=None,
        offline=False,
    ):
        targets = targets if targets is not None else self.registry().targets
        if not targets or len(targets) > self.settings.max_documents:
            raise PipelineError(
                "DOCUMENT_LIMIT",
                "Choose at least one target within the configured document cap",
            )
        budget = Decimal(str(budget if budget is not None else self.settings.budget))
        if not budget.is_finite() or budget <= 0 or budget > self.settings.budget:
            raise PipelineError(
                "INVALID_BUDGET",
                "Run budget must be positive and within ENGINE_RUN_BUDGET_USD",
            )
        run_id = uid()
        config = {
            "llm": llm,
            "offline": offline,
            "parser": PARSER_VERSION,
            "extractor": EXTRACTOR_VERSION,
            "schema": SCHEMA_VERSION,
            "models": [self.settings.model, self.settings.fallback_model],
        }
        self.store.insert(
            runs,
            id=run_id,
            status="queued",
            created_at=now(),
            config=json.dumps(config),
            budget=str(budget),
            spent="0",
            reserved="0",
            parent_error_id=parent_error,
        )
        for target in targets:
            self.store.insert(
                jobs,
                id=uid(),
                run_id=run_id,
                target=target.model_dump_json(),
                status="queued",
                stage="queued",
                attempt=0,
                snapshot_id=snapshot_id,
            )
        return run_id

    def claim(self, run_id):
        with self.store.engine.connect() as c:
            c.exec_driver_sql("BEGIN IMMEDIATE")
            # Persisted leases make abandoned jobs recoverable after a restart.
            c.execute(
                jobs.update()
                .where(
                    jobs.c.run_id == run_id,
                    jobs.c.status == "running",
                    jobs.c.lease_until < now(),
                )
                .values(status="queued", lease=None, lease_until=None)
            )
            row = (
                c.execute(
                    select(jobs)
                    .where(jobs.c.run_id == run_id, jobs.c.status == "queued")
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if not row:
                c.commit()
                return None
            token = uid()
            until = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            c.execute(
                jobs.update()
                .where(jobs.c.id == row["id"])
                .values(status="running", lease=token, lease_until=until)
            )
            c.commit()
            return self.store.one(jobs, id=row["id"])

    def checkpoint(self, job, stage, **values):
        with self.store.engine.begin() as c:
            updated = c.execute(
                jobs.update()
                .where(
                    jobs.c.id == job["id"],
                    jobs.c.lease == job["lease"],
                    jobs.c.status == "running",
                    jobs.c.lease_until >= now(),
                )
                .values(
                    **{
                        "stage": stage,
                        "lease_until": (
                            datetime.now(timezone.utc) + timedelta(hours=1)
                        ).isoformat(),
                        **values,
                    }
                )
            )
            if updated.rowcount != 1:
                raise PipelineError(
                    "LEASE_LOST", "Job ownership expired or changed; stop work"
                )
        job.update(stage=stage, **values)

    def work(self, run_id):
        import fcntl

        with (self.store.directory / ".worker.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise PipelineError(
                    "WORKER_BUSY", "Another local collection worker is active"
                ) from exc
            try:
                run = self.store.one(runs, id=run_id)
                if run["status"] in ("paused", "published"):
                    raise PipelineError(
                        "RUN_NOT_RUNNABLE",
                        "Use a new replay for paused work; published runs are immutable",
                    )
                abandoned = self.store.rows(jobs, run_id=run_id, status="running")
                # The process lock proves there is no surviving local worker.
                for job in abandoned:
                    self.store.update(
                        jobs, job["id"], status="queued", lease=None, lease_until=None
                    )
                return self._work(run_id, recovered=len(abandoned))
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _work(self, run_id, recovered=0):
        run = self.store.one(runs, id=run_id)
        if run["status"] in ("paused", "published"):
            raise PipelineError(
                "RUN_NOT_RUNNABLE",
                "Use a new bounded replay for paused work; published runs are immutable",
            )
        config = json.loads(run["config"])
        if (
            config["models"] != [self.settings.model, self.settings.fallback_model]
            or config["parser"] != PARSER_VERSION
            or config["extractor"] != EXTRACTOR_VERSION
        ):
            raise PipelineError(
                "RUN_CONFIG_CHANGED",
                "Create a new run/replay after changing extraction versions or models",
            )
        log = RunLog(self.store, run_id, [self.settings.api_key])
        fetcher = Fetcher(self.settings, self.store, self.fetch_client, self.sleep)
        model = OpenRouter(self.settings, self.store, run_id, log, self.model_client)
        self.store.update(runs, run_id, status="running", finished_at=None)
        try:
            log.emit(
                "run.started",
                config=config,
                parent_error_id=run["parent_error_id"],
                recovered_jobs=recovered,
            )
            while job := self.claim(run_id):
                target = Target.model_validate_json(job["target"])
                try:
                    self.process(job, target, config, fetcher, model, log)
                except Exception as exc:
                    if getattr(exc, "code", "").startswith("LOG_") or isinstance(
                        exc, OSError
                    ):
                        raise
                    err = log.failure(
                        job["id"],
                        job["stage"],
                        exc,
                        source_url=str(target.url),
                        snapshot_id=job["snapshot_id"],
                        attempt=job["attempt"],
                    )
                    if getattr(exc, "code", "") != "LEASE_LOST":
                        self.store.update(
                            jobs,
                            job["id"],
                            status="failed",
                            error_id=err,
                            lease=None,
                            lease_until=None,
                        )
                    if getattr(exc, "code", "") in STOP_CODES:
                        self.store.update(runs, run_id, status="paused")
                        break
            current = self.store.one(runs, id=run_id)
            if current["status"] != "paused":
                counts = Counter(
                    j["status"] for j in self.store.rows(jobs, run_id=run_id)
                )
                state = (
                    "running"
                    if counts["running"]
                    else "awaiting_review"
                    if self.store.rows(claims, run_id=run_id)
                    else "failed"
                )
                self.store.update(
                    runs,
                    run_id,
                    status=state,
                    finished_at=None if state == "running" else now(),
                )
            report = self.report(run_id)
            log.emit(
                "run.finished", status=report["status"], counts=report["documents"]
            )
            log.summary(report)
            return report
        except BaseException as exc:
            self.store.update(
                runs,
                run_id,
                status="interrupted"
                if isinstance(exc, KeyboardInterrupt)
                else "failed",
                finished_at=now(),
            )
            raise
        finally:
            fetcher.close()
            model.close()
            log.close()

    def process(self, job, target, config, fetcher, model, log):
        self.checkpoint(job, "fetch")
        log.emit(
            "stage.started", job_id=job["id"], stage="fetch", source_url=str(target.url)
        )
        if job["snapshot_id"]:
            snapshot = self.store.one(snapshots, id=job["snapshot_id"])
            log.emit(
                "fetch.snapshot_reused",
                job_id=job["id"],
                snapshot_id=snapshot["id"],
                observed_at=snapshot["observed_at"],
            )
        elif config["offline"]:
            raise PipelineError(
                "OFFLINE_SNAPSHOT_MISSING",
                "Offline run needs a saved snapshot; use replay",
            )
        else:
            for attempt in range(1, self.settings.retries + 2):
                self.checkpoint(job, "fetch", attempt=attempt)
                try:
                    snapshot = fetcher.fetch(target)
                    break
                except PipelineError as exc:
                    err = log.failure(
                        job["id"],
                        "fetch",
                        exc,
                        attempt=attempt,
                        source_url=str(target.url),
                    )
                    if not exc.retryable or attempt > self.settings.retries:
                        self.store.update(jobs, job["id"], error_id=err)
                        raise PipelineError(
                            "FETCH_RETRIES_EXHAUSTED" if exc.retryable else exc.code,
                            "Fetch stopped; see recorded attempt diagnostics",
                        ) from exc
                    log.emit(
                        "stage.retry",
                        "WARNING",
                        job_id=job["id"],
                        stage="fetch",
                        attempt=attempt,
                        error_id=err,
                    )
                    self.sleep(
                        min(300, max(getattr(exc, "retry_after", 0), 2**attempt))
                    )
        self.checkpoint(job, "parse", snapshot_id=snapshot["id"])
        raw = self.store.directory / snapshot["path"]
        if not raw.exists():
            raise PipelineError(
                "SNAPSHOT_MISSING", "Retained source artifact is unavailable"
            )
        if (
            __import__("hashlib").sha256(raw.read_bytes()).hexdigest()
            != snapshot["hash"]
        ):
            raise PipelineError(
                "SNAPSHOT_HASH_MISMATCH", "Source artifact integrity check failed"
            )
        parsed_path = (
            self.store.directory
            / "parsed"
            / snapshot["hash"]
            / PARSER_VERSION
            / "document.json"
        )
        parsed_path.parent.mkdir(parents=True, exist_ok=True)
        if parsed_path.exists():
            document = json.loads(parsed_path.read_text())
            log.emit("parse.cache_hit", job_id=job["id"], parser=PARSER_VERSION)
        else:
            document = parse(
                raw.read_bytes(), snapshot["content_type"], snapshot["url"]
            )
            parsed_path.write_text(json.dumps(document, ensure_ascii=False, indent=2))
        self.checkpoint(
            job,
            "extract",
            parsed_path=str(parsed_path.relative_to(self.store.directory)),
        )
        classified = Counter(classify(b) for b in document["blocks"])
        log.emit(
            "document.classified",
            job_id=job["id"],
            counts=dict(classified),
            classifier="keyword-v1",
        )
        candidate = rule_claims(document, target)
        for skipped in document.get("rule_skips", []):
            log.emit("extract.skipped", "WARNING", job_id=job["id"], **skipped)
        if config["llm"]:
            model.job_id = job["id"]
            relevant = [b for b in document["blocks"] if classify(b) == "relevant"]
            candidate += model.extract(relevant, target, offline=config["offline"])
        log.emit(
            "stage.succeeded",
            job_id=job["id"],
            stage="extract",
            candidate_count=len(candidate),
            parser=PARSER_VERSION,
            extractor=EXTRACTOR_VERSION,
        )
        self.checkpoint(job, "validate")
        if not candidate:
            raise PipelineError(
                "NO_CANDIDATES",
                "No supported fields found; source adapter needs review",
            )
        for candidate_claim in candidate:
            body = candidate_claim.model_dump()
            cid = fingerprint({"run": job["run_id"], "job": job["id"], "claim": body})
            if self.store.rows(claims, id=cid):
                continue
            status = validate(candidate_claim, document)
            self.store.insert(
                claims,
                id=cid,
                run_id=job["run_id"],
                job_id=job["id"],
                entity_id=target.id,
                snapshot_id=snapshot["id"],
                body=json.dumps(body, ensure_ascii=False),
                validation=status,
                quality=json.dumps(quality(candidate_claim, status)),
                review="pending",
            )
            if status != "valid":
                log.failure(
                    job["id"],
                    "validate",
                    PipelineError(
                        status, "Candidate held; inspect saved evidence and scope"
                    ),
                    claim_id=cid,
                    snapshot_id=snapshot["id"],
                    source_url=str(target.url),
                )
        # Candidate conflicts need review, including disagreements between extractors.
        grouped = {}
        for row in self.store.rows(claims, job_id=job["id"]):
            body = json.loads(row["body"])
            if body["field"] in ("requirement", "deadline"):
                continue
            key = (
                body["field"],
                body["applicant_group"],
                body["intake"],
                body["conditions"],
            )
            grouped.setdefault(key, []).append((row, body))
        for members in grouped.values():
            if len({b["value"].casefold() for _, b in members}) > 1:
                for row, body in members:
                    self.store.update(
                        claims,
                        row["id"],
                        validation="CONFLICTING_VALUES",
                        quality=json.dumps(
                            quality(Claim.model_validate(body), "CONFLICTING_VALUES")
                        ),
                    )
                    log.failure(
                        job["id"],
                        "validate",
                        PipelineError(
                            "CONFLICTING_VALUES", "Same-scope candidates disagree"
                        ),
                        claim_id=row["id"],
                        snapshot_id=snapshot["id"],
                    )
        self.checkpoint(job, "complete", status="done", lease_until=None, lease=None)
        log.emit(
            "document.completed",
            job_id=job["id"],
            snapshot_id=snapshot["id"],
            candidate_count=len(candidate),
        )

    def report(self, run_id):
        run = self.store.one(runs, id=run_id)
        js = self.store.rows(jobs, run_id=run_id)
        cs = self.store.rows(claims, run_id=run_id)
        es = self.store.rows(errors, run_id=run_id)
        return {
            "run_id": run_id,
            "status": run["status"],
            "documents": dict(Counter(j["status"] for j in js)),
            "attempted_documents": len(js),
            "claims": dict(Counter(c["validation"] for c in cs)),
            "review": dict(Counter(c["review"] for c in cs)),
            "errors_by_stage": dict(Counter(e["stage"] for e in es)),
            "error_events": len(es),
            "error_jobs": len({e["job_id"] for e in es}),
            "budget_usd": run["budget"],
            "known_cost_usd": run["spent"],
            "reserved_or_uncertain_usd": run["reserved"],
            "parent_error_id": run["parent_error_id"],
            "publication": "No automatic publication; human review required",
        }

    def replay(self, error_id, *, allow_paid=False, budget=None):
        error = self.store.one(errors, id=error_id)
        job = self.store.one(jobs, id=error["job_id"])
        old = self.store.one(runs, id=error["run_id"])
        if not job["snapshot_id"]:
            raise PipelineError(
                "REPLAY_INPUT_MISSING",
                "Failure happened before a snapshot existed; explicitly refetch the source in a new run",
            )
        return self.enqueue(
            targets=[Target.model_validate_json(job["target"])],
            llm=json.loads(old["config"])["llm"],
            budget=budget,
            parent_error=error_id,
            snapshot_id=job["snapshot_id"],
            offline=not allow_paid,
        )
