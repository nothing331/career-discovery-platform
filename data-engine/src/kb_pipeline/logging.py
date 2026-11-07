"""Append-only local diagnostics. Never put raw provider bodies in operational logs."""

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import shutil
import traceback
from urllib.parse import urlsplit, urlunsplit
from .db import uid, now, errors
from .contracts import PipelineError


class Redactor:
    def __init__(self, secrets=()):
        self.secrets = [s for s in secrets if s]

    def text(self, text):
        text = str(text)
        for value in self.secrets:
            text = text.replace(value, "[REDACTED]")
        text = re.sub(r"(?i)\bBearer\s+[^\s\"']+", "Bearer [REDACTED]", text)
        text = re.sub(
            r"(?i)(api[_-]?key|authorization|cookie|token|password)([\s\"']*[:=][\s\"']*)[^\s,\"';]+",
            r"\1\2[REDACTED]",
            text,
        )

        def url(m):
            try:
                p = urlsplit(m[0])
                return urlunsplit(
                    (
                        p.scheme,
                        p.hostname or "",
                        p.path,
                        "[REDACTED]" if p.query else "",
                        "",
                    )
                )
            except ValueError:
                return "[REDACTED_URL]"

        return re.sub(r"https?://[^\s<>\"']+", url, text)

    def clean(self, obj):
        if isinstance(obj, dict):
            return {
                str(k): "[REDACTED]"
                if re.fullmatch(
                    r"(?i)(api[_-]?key|authorization|cookie|password|access_token|secret)",
                    str(k),
                )
                else self.clean(v)
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [self.clean(x) for x in obj]
        return self.text(obj) if isinstance(obj, str) else obj


class RetainingHandler(RotatingFileHandler):
    def doRollover(self):
        if Path(self.baseFilename + "." + str(self.backupCount)).exists():
            raise PipelineError(
                "LOG_RETENTION_LIMIT",
                "Event-file limit reached; archive the run before continuing",
            )
        super().doRollover()


class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps(record.payload, ensure_ascii=False)


class RunLog:
    def __init__(self, store, run_id, secrets=()):
        self.store, self.run_id, self.redactor = store, run_id, Redactor(secrets)
        self.directory = store.directory / "logs" / run_id
        (self.directory / "diagnostics").mkdir(parents=True, exist_ok=True)
        self.logger = logging.Logger("pipeline." + run_id)
        handler = RetainingHandler(
            self.directory / "events.jsonl",
            maxBytes=2_000_000,
            backupCount=20,
            encoding="utf-8",
        )

        # Fail closed rather than logging's default stderr-only handleError behavior.
        def fail(record):
            raise PipelineError("LOG_WRITE_FAILED", "Local event log write failed")

        handler.handleError = fail
        handler.setFormatter(JSONFormatter())
        self.logger.addHandler(handler)

    def emit(self, event, level="INFO", **context):
        if shutil.disk_usage(self.directory).free < 10_000_000:
            raise PipelineError(
                "LOG_DISK_LIMIT", "Insufficient disk space for audit trail"
            )
        payload = self.redactor.clean(
            {
                "event_id": uid(),
                "timestamp": now(),
                "run_id": self.run_id,
                "event": event,
                "level": level,
                **context,
            }
        )
        self.logger.log(getattr(logging, level), event, extra={"payload": payload})
        for h in self.logger.handlers:
            h.flush()

    def failure(self, job_id, stage, exc, **context):
        error_id = uid()
        code = getattr(exc, "code", type(exc).__name__)
        detail = self.redactor.clean(
            {
                "error_id": error_id,
                "run_id": self.run_id,
                "job_id": job_id,
                "stage": stage,
                "code": code,
                "message": str(exc),
                "traceback": "".join(traceback.format_exception(exc)),
                **context,
            }
        )
        path = self.directory / "diagnostics" / (error_id + ".json")
        path.write_text(
            json.dumps(
                {**detail, "traceback": detail["traceback"][:20000]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self.emit(
            "stage.failed",
            "ERROR",
            job_id=job_id,
            stage=stage,
            error_id=error_id,
            error_code=code,
            message=str(exc),
            retryable=getattr(exc, "retryable", False),
            **context,
        )
        self.store.insert(
            errors,
            id=error_id,
            run_id=self.run_id,
            job_id=job_id,
            stage=stage,
            code=code,
            message=self.redactor.text(exc),
            diagnostic_path=str(path.relative_to(self.store.directory)),
            status="open",
            created_at=now(),
            retryable=int(getattr(exc, "retryable", False)),
        )
        print(f"{stage}: {code} (error {error_id})")
        return error_id

    def summary(self, value):
        path = self.directory / "run_summary.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self.redactor.clean(value), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(path)

    def close(self):
        for h in self.logger.handlers[:]:
            h.close()
            self.logger.removeHandler(h)
