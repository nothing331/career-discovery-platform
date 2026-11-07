import hashlib
import json
import re
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
    pages,
    structured,
    uid,
    now,
    fingerprint,
)
from .logging import RunLog
from .acquire import Fetcher, parse, normal, PARSER_VERSION
from .links import select_followups, LINK_SELECTOR_VERSION
from .normalize import normalize_claims
from .structured import NORMALIZER_VERSION
from .extract import (
    rule_claims,
    classify,
    validate,
    quality,
    EXTRACTOR_VERSION,
    SCHEMA_VERSION,
    PROMPT_VERSION,
    CLASSIFIER_VERSION,
)
from .knowledge import superseding_run
from .providers import extractor
from .grounding import ground, GROUNDING_VERSION

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
# Never swallowed as a follow-up page failure: they end or invalidate the whole job.
_DEGREE_WORDS = re.compile(
    r"\(.*?\)|\b(?:bachelor|master|b\.?\s?sc\.?|m\.?\s?sc\.?|b\.?\s?a\.?|m\.?\s?a\.?"
    r"|of\s+science|of\s+arts|degree|programme|program|studiengang)(?![a-z])",
    re.I,
)


def _squash(text):
    return re.sub(r"[\s\-_]+", " ", text or "").strip().casefold()


def _mentions_programme(document, target):
    """Does a regulations page name this programme (subject minus degree suffix)?"""
    subject = _squash(_DEGREE_WORDS.sub(" ", target.programme)).strip(" ,.-")
    if not subject:
        return True
    text = _squash(
        " ".join(b.get("heading", "") + " " + b["text"] for b in document["blocks"])
    )
    return subject in text


PROPAGATE_PREFIXES = ("LOG_",)
MODEL_SKIP_CODES = {
    "MODEL_DOCUMENT_LIMIT",
    "SECTION_TOO_LARGE",
    "MODEL_TRUNCATED_OR_REFUSED",
    "MODEL_SCHEMA_INVALID",
    "MODEL_REQUEST_REJECTED",
}
PROPAGATE_CODES = STOP_CODES | {"LEASE_LOST"}


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
            "prompt": PROMPT_VERSION,
            "classifier": CLASSIFIER_VERSION,
            "grounder": GROUNDING_VERSION,
            "link_selector": LINK_SELECTOR_VERSION,
            "normalizer": NORMALIZER_VERSION,
            "followup_limit": self.settings.followup_limit,
            # Snapshot-pinned runs (replay/pilot) must never reach the network.
            "pinned": bool(snapshot_id),
            "models": [self.settings.model, self.settings.fallback_model],
            "model_config": self.settings.model_config(),
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
            or config.get("classifier", "keyword-v1") != CLASSIFIER_VERSION
            or config.get("schema") != SCHEMA_VERSION
            or config.get("prompt", "grounded-v1") != PROMPT_VERSION
            or config.get("grounder") != GROUNDING_VERSION
            or config.get("link_selector") != LINK_SELECTOR_VERSION
            or config.get("normalizer") != NORMALIZER_VERSION
            or config.get("followup_limit") != self.settings.followup_limit
            or (
                config["llm"]
                and config.get("model_config") != self.settings.model_config()
            )
        ):
            raise PipelineError(
                "RUN_CONFIG_CHANGED",
                "Create a new run/replay after changing extraction versions or models",
            )
        log = RunLog(self.store, run_id, [self.settings.api_key])
        fetcher = Fetcher(self.settings, self.store, self.fetch_client, self.sleep)
        model = extractor(
            self.settings, self.store, run_id, log, self.model_client, self.sleep
        )
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
        document, parsed_path = self._load_document(snapshot, job, log)
        self.checkpoint(
            job,
            "extract",
            parsed_path=str(parsed_path.relative_to(self.store.directory)),
        )
        candidate = self._candidates(job, target, document, config, model, log)
        log.emit(
            "stage.succeeded",
            job_id=job["id"],
            stage="extract",
            candidate_count=len(candidate),
            parser=PARSER_VERSION,
            extractor=EXTRACTOR_VERSION,
        )
        self.checkpoint(job, "validate")
        total = len(candidate)
        self._stage(job, target, snapshot, document, candidate, log, primary=True)
        # Depth-1 follow-ups. Their failures are recorded but never fail the job.
        total += self._followups(job, target, document, config, fetcher, model, log)
        if not total:
            raise PipelineError(
                "NO_CANDIDATES",
                "No supported fields found; source adapter needs review",
            )
        self._flag_conflicts(job, snapshot, log)
        self._structure(job, target, log)
        self.checkpoint(job, "complete", status="done", lease_until=None, lease=None)
        log.emit(
            "document.completed",
            job_id=job["id"],
            snapshot_id=snapshot["id"],
            candidate_count=total,
        )

    def _load_document(self, snapshot, job, log):
        """Integrity-check a retained artifact and return its (cached) parsed document."""
        raw = self.store.directory / snapshot["path"]
        if not raw.exists():
            raise PipelineError(
                "SNAPSHOT_MISSING", "Retained source artifact is unavailable"
            )
        if hashlib.sha256(raw.read_bytes()).hexdigest() != snapshot["hash"]:
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
        return document, parsed_path

    def _candidates(self, job, target, document, config, model, log, *, primary=True):
        """Rule + optional LLM candidates for one page, grounded against that page."""
        ctx = {} if primary else {"page_url": str(target.url)}
        classified = Counter(classify(b) for b in document["blocks"])
        log.emit(
            "document.classified",
            job_id=job["id"],
            counts=dict(classified),
            classifier=CLASSIFIER_VERSION,
            **ctx,
        )
        candidate = rule_claims(document, target, primary=primary)
        for skipped in document.get("rule_skips", []):
            log.emit("extract.skipped", "WARNING", job_id=job["id"], **skipped, **ctx)
        if config["llm"]:
            model.job_id = job["id"]
            relevant = [b for b in document["blocks"] if classify(b) == "relevant"]
            try:
                raw_candidates = model.extract(
                    relevant, target, offline=config["offline"]
                )
            except PipelineError as exc:
                if exc.code not in MODEL_SKIP_CODES:
                    raise
                # Size/shape failures only lose the optional LLM pass; rule candidates stay.
                log.failure(
                    job["id"],
                    "extract",
                    exc,
                    source_url=str(target.url),
                    action="model_skipped",
                )
                log.emit(
                    "extract.model_skipped",
                    "WARNING",
                    job_id=job["id"],
                    code=exc.code,
                    **ctx,
                )
                return candidate
            log.emit(
                "model.candidates_received",
                job_id=job["id"],
                count=len(raw_candidates),
                grounder=GROUNDING_VERSION,
                **ctx,
            )
            for raw_claim in raw_candidates:
                grounded, action = ground(
                    raw_claim, relevant, source_blocks=document["blocks"]
                )
                if action:
                    log.emit("claim.grounded", job_id=job["id"], **action)
                candidate.extend(grounded)
        return candidate

    def _stage(
        self, job, target, snapshot, document, candidate, log, *, primary, hold=None
    ):
        """Validate against the claim's own page and insert; identical claims merge methods."""
        for candidate_claim in candidate:
            body = candidate_claim.model_dump()
            ident = {"run": job["run_id"], "job": job["id"], "claim": body}
            if not primary:
                ident["snapshot"] = snapshot["id"]
            cid = fingerprint(ident)
            if self.store.rows(claims, id=cid):
                continue
            claim_key = fingerprint(
                {
                    "entity": target.id,
                    "source": snapshot["hash"],
                    "claim": {k: v for k, v in body.items() if k != "method"},
                }
            )
            twins = self.store.rows(claims, run_id=job["run_id"], claim_key=claim_key)
            if twins:
                methods = json.loads(twins[0]["agreeing_methods"] or "[]")
                if body["method"] not in methods:
                    self.store.update(
                        claims,
                        twins[0]["id"],
                        agreeing_methods=json.dumps(methods + [body["method"]]),
                    )
                continue
            status = validate(candidate_claim, document)
            if hold and status == "valid":
                status = hold
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
                claim_key=claim_key,
                agreeing_methods=json.dumps([body["method"]]),
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
                    source_url=snapshot["url"],
                )

    def _flag_conflicts(self, job, snapshot, log):
        # Candidate conflicts need review, including disagreements between extractors
        # and between pages. Identical values (any case/whitespace) never conflict.
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
            if len({normal(b["value"]).casefold() for _, b in members}) > 1:
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
                        snapshot_id=row["snapshot_id"],
                    )

    def _structure(self, job, target, log):
        """Typed facts from valid claims only; each stays tied to its evidence claims."""
        pairs = [
            (r["id"], Claim.model_validate_json(r["body"]))
            for r in self.store.rows(claims, job_id=job["id"])
            if r["validation"] == "valid"
        ]
        for fact in normalize_claims(pairs):
            # entity is part of the key: identical wording on two programmes is two facts
            fact_key = fingerprint([target.id, *fact.key()])
            if self.store.rows(structured, run_id=job["run_id"], fact_key=fact_key):
                continue
            self.store.insert(
                structured,
                id=uid(),
                run_id=job["run_id"],
                job_id=job["id"],
                entity_id=target.id,
                kind=fact.kind,
                data=fact.data.model_dump_json(),
                evidence_claim_ids=json.dumps(fact.evidence_claim_ids),
                evidence_text=fact.evidence_text,
                method=fact.method,
                applicant_group=fact.applicant_group,
                fact_key=fact_key,
                review="pending",
                created_at=now(),
            )
        log.emit("structured.created", job_id=job["id"], normalizer=NORMALIZER_VERSION)

    # ---- depth-1 follow-up pages -------------------------------------------------

    def _page_row(self, job_id, url):
        rows = [r for r in self.store.rows(pages, job_id=job_id) if r["url"] == url]
        return rows[0] if rows else None

    def _record_page(self, job, link, status, snapshot_id=None, error_code=None):
        values = dict(
            roles=json.dumps(link["roles"]),
            link_text=link["text"],
            kind=link["kind"],
            snapshot_id=snapshot_id,
            status=status,
            error_code=error_code,
        )
        existing = self._page_row(job["id"], link["url"])
        if existing:
            self.store.update(pages, existing["id"], **values)
        else:
            self.store.insert(
                pages,
                id=uid(),
                job_id=job["id"],
                url=link["url"],
                created_at=now(),
                **values,
            )

    def _run_page(self, run_id, url):
        """An earlier outcome for this URL in this run (shared university pages)."""
        with self.store.engine.connect() as c:
            rows = list(
                c.execute(
                    select(pages)
                    .join(jobs, pages.c.job_id == jobs.c.id)
                    .where(
                        jobs.c.run_id == run_id,
                        pages.c.url == url,
                        pages.c.status.in_(("done", "failed")),
                    )
                    .order_by(pages.c.created_at)
                ).mappings()
            )
        return next((r for r in rows if r["status"] == "done"), None) or (
            rows[0] if rows else None
        )

    def _parent_followup_snapshot(self, job, url):
        """Snapshot a replay's parent job recorded for this follow-up URL, if retained."""
        run = self.store.one(runs, id=job["run_id"])
        if not run["parent_error_id"]:
            return None
        error = self.store.one(errors, id=run["parent_error_id"])
        for row in self.store.rows(pages, job_id=error["job_id"]):
            if row["url"] == url and row["status"] == "done" and row["snapshot_id"]:
                snap = self.store.one(snapshots, id=row["snapshot_id"])
                if snap and (self.store.directory / snap["path"]).exists():
                    return snap
        return None

    def _followup_snapshot(self, job, target, link, config, fetcher):
        """Snapshot row for a link, reusing run-level results; offline never fetches."""
        known = self._run_page(job["run_id"], link["url"])
        if known and known["status"] == "done" and known["snapshot_id"]:
            return self.store.one(snapshots, id=known["snapshot_id"])
        if known and known["status"] == "failed":
            raise PipelineError(
                known["error_code"] or "FOLLOWUP_FAILED",
                "Page already failed in this run; not refetched",
            )
        if config["offline"] or config.get("pinned"):
            parent = (
                self._parent_followup_snapshot(job, link["url"])
                if config.get("pinned")
                else None
            )
            if parent:
                return parent
            saved = sorted(
                self.store.rows(snapshots, url=link["url"]),
                key=lambda r: r["observed_at"],
                reverse=True,
            )
            if saved and (self.store.directory / saved[0]["path"]).exists():
                return saved[0]
            raise PipelineError(
                "OFFLINE_SNAPSHOT_MISSING", "No saved snapshot for follow-up page"
            )
        derived = Target.model_validate(
            {**target.model_dump(mode="json"), "url": link["url"]}
        )
        for attempt in range(1, self.settings.retries + 2):
            try:
                return fetcher.fetch(derived)
            except PipelineError as exc:
                if not exc.retryable or attempt > self.settings.retries:
                    raise
                self.sleep(min(300, max(getattr(exc, "retry_after", 0), 2**attempt)))

    def _followups(self, job, target, document, config, fetcher, model, log):
        limit = self.settings.followup_limit
        if not limit or not target.follow_links:
            return 0
        links = select_followups(document, target, limit=limit)
        log.emit(
            "followups.selected",
            job_id=job["id"],
            count=len(links),
            selector=LINK_SELECTOR_VERSION,
            urls=[link["url"] for link in links],
        )
        total = 0
        for link in links:
            self.checkpoint(job, "followup")
            offline_mode = bool(config["offline"] or config.get("pinned"))
            try:
                snapshot = self._followup_snapshot(job, target, link, config, fetcher)
                page_doc, _ = self._load_document(snapshot, job, log)
                derived = Target.model_validate(
                    {**target.model_dump(mode="json"), "url": link["url"]}
                )
                candidate = self._candidates(
                    job, derived, page_doc, config, model, log, primary=False
                )
                hold = None
                if "regulations" in link["roles"] and not _mentions_programme(
                    page_doc, target
                ):
                    hold = "FOLLOWUP_PROGRAMME_UNVERIFIED"
                    log.emit(
                        "followup.programme_unverified",
                        "WARNING",
                        job_id=job["id"],
                        source_url=link["url"],
                    )
                self._stage(
                    job,
                    target,
                    snapshot,
                    page_doc,
                    candidate,
                    log,
                    primary=False,
                    hold=hold,
                )
                total += len(candidate)
                self._record_page(job, link, "done", snapshot["id"])
            except Exception as exc:
                code = getattr(exc, "code", "")
                if (
                    code in PROPAGATE_CODES
                    or code.startswith(PROPAGATE_PREFIXES)
                    or isinstance(exc, OSError)
                ):
                    raise
                if code in ("OFFLINE_SNAPSHOT_MISSING", "OFFLINE_CACHE_MISSING") and (
                    offline_mode
                ):
                    log.emit(
                        "followup.skipped",
                        "WARNING",
                        job_id=job["id"],
                        source_url=link["url"],
                        code=code,
                    )
                    self._record_page(job, link, "skipped", error_code=code)
                    continue
                log.failure(
                    job["id"],
                    "followup",
                    exc,
                    source_url=link["url"],
                    attempt=job["attempt"],
                )
                log.emit(
                    "followup.failed",
                    "WARNING",
                    job_id=job["id"],
                    source_url=link["url"],
                    code=code or type(exc).__name__,
                )
                self._record_page(
                    job, link, "failed", error_code=code or type(exc).__name__
                )
        return total

    def report(self, run_id):
        run = self.store.one(runs, id=run_id)
        config = json.loads(run["config"])
        provider = config.get("model_config", {}).get("provider", "openrouter")
        estimated = config["llm"] and provider == "groq"
        js = self.store.rows(jobs, run_id=run_id)
        cs = self.store.rows(claims, run_id=run_id)
        es = self.store.rows(errors, run_id=run_id)
        sf = self.store.rows(structured, run_id=run_id)
        job_ids = {j["id"] for j in js}
        with self.store.engine.connect() as c:
            page_rows = [
                r
                for r in c.execute(select(pages.c.job_id, pages.c.status)).mappings()
                if r["job_id"] in job_ids
            ]
        return {
            "run_id": run_id,
            "status": run["status"],
            "validation_version_current": config.get("extractor") == EXTRACTOR_VERSION
            and config.get("schema") == SCHEMA_VERSION
            and config.get("grounder") == GROUNDING_VERSION,
            "documents": dict(Counter(j["status"] for j in js)),
            "attempted_documents": len(js),
            "superseded": superseding_run(self.store, run_id) is not None,
            "followup_pages": dict(Counter(r["status"] for r in page_rows)),
            "structured": dict(Counter(f["kind"] for f in sf)),
            "claims": dict(Counter(c["validation"] for c in cs)),
            "review": dict(Counter(c["review"] for c in cs)),
            "errors_by_stage": dict(Counter(e["stage"] for e in es)),
            "error_events": len(es),
            "error_jobs": len({e["job_id"] for e in es}),
            "budget_usd": run["budget"],
            "provider": provider,
            "cost_basis": "token_rate_estimate"
            if estimated
            else "provider_reported"
            if config["llm"]
            else "no_model_calls",
            "accounted_cost_usd": run["spent"],
            "known_cost_usd": None if estimated else run["spent"],
            "estimated_cost_usd": run["spent"] if estimated else None,
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
