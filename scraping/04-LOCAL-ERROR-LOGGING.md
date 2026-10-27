# Local pipeline logs and failure replay

**Status:** Required POC implementation contract; the collection engine and these commands are not implemented yet.
**Updated:** 2026-10-27
**Scope:** Capture failures locally, explain missing coverage, and reproduce failed extraction steps so the team can improve the engine.

## Local outputs

Use Python's standard logging library with a JSON formatter, a local JSONL file handler, and a concise console handler. No hosted logging service or telemetry is required.

```text
data/
  poc.db                              # ops_runs, ops_jobs, ops_errors
  logs/<run_id>/
    events.jsonl                      # One structured event per line, appended as work happens
    run_summary.json                  # Counts, coverage gaps, spend, unresolved errors
    diagnostics/<error_id>.json        # Sanitized traceback, validation details and artifact references
  raw/DE/<source_id>/<content_hash>.*  # Original source snapshots
  parsed/<snapshot_id>/document.json  # Parsed text, tables and location IDs
```

JSONL records operational events; `ops_errors` indexes failures for filtering and review. Link errors to snapshots and parsed inputs rather than copying entire documents into every log line. All runtime logs, diagnostic files, databases and source captures stay local and outside Git and the hosted planning site. Repository fixtures must be deliberately selected and sanitized.

Record stage start, success, skip, retry, failure and cancellation events across discovery, fetching, parsing, classification, extraction, validation and publication. A field that is explicitly not stated is an unknown, not an exception. A page legitimately classified as irrelevant is a skip. Both outcomes remain visible in coverage reports.

## Required event context

| Group | Fields |
| --- | --- |
| Identity | Event ID, UTC timestamp, level, event name, run ID, job ID, error ID when applicable |
| Source | Country, source/entity IDs where known, sanitized URL, snapshot ID and content hash when a snapshot exists |
| Processing | Stage, component, attempt/max attempts, duration, parser/classifier/extractor versions |
| Failure | Stable error code, exception type, sanitized message, retry eligibility, diagnostic path |
| Model work | Provider/model ID, prompt/schema versions, provider request ID if available, reported token usage and billing uncertainty |
| Lineage | Original run/error IDs for replays; input fingerprint and artifact references |

Some fields are unavailable before their stage succeeds. A fetch timeout must still be logged without a snapshot; record null and an explicit reason instead of inventing one. Define error codes centrally so the review UI can group failures without depending on wording in exception messages.

Illustrative event, not an actual extraction result:

```json
{
  "event_id": "example-event-001",
  "timestamp": "2026-10-27T10:00:00Z",
  "level": "ERROR",
  "event": "stage.failed",
  "run_id": "example-run-001",
  "job_id": "example-job-007",
  "error_id": "example-error-004",
  "stage": "validate",
  "source": {
    "country": "DE",
    "source_id": "example-source",
    "url": "https://university.example/admissions",
    "snapshot_id": "example-snapshot",
    "content_hash": "<sha256>"
  },
  "error": {
    "code": "EVIDENCE_NOT_FOUND",
    "type": "EvidenceValidationError",
    "message": "Candidate requirement quote could not be located in the parsed source.",
    "retryable": false,
    "diagnostic_path": "data/logs/example-run-001/diagnostics/example-error-004.json"
  },
  "attempt": 1,
  "max_attempts": 3,
  "versions": {
    "parser": "<version>",
    "extractor": "<version>",
    "model": "<pinned-model-id>",
    "prompt": "<version>",
    "schema": "<version>"
  },
  "outcome": "held_for_review"
}
```

The diagnostic artifact holds the sanitized traceback or validation paths and references to the relevant saved input and candidate output. Store only the minimum diagnostic content needed to reproduce the problem. Do not put API keys, authorization headers, cookies, signed URL tokens, personal student data or unrestricted prompts/responses in logs. Redact exception messages, tracebacks and provider errors before writing either output.

## Failure handling

| Failure | Initial action |
| --- | --- |
| Network timeout, HTTP 429 or transient 5xx | Retry only when classified as transient; exponential backoff with jitter, respect Retry-After, maximum two retries after the first attempt |
| HTTP 401/403, blocked source or missing page | Stop that target, record status and route for source/access review; no blind retry loop |
| PDF parse failure, empty parsed text or broken table | Keep the snapshot; try the configured parser fallback at most once and then hold for review |
| Model truncation, refusal, malformed JSON or schema mismatch | Save a sanitized diagnostic; allow only a configured, bounded repair/fallback. Repeating the same deterministic failure is not a general retry policy |
| Missing evidence, missing critical scope or contradictory claims | Hold the affected claims for review; do not publish or silently replace them with defaults |
| Run budget exhausted or uncertain provider billing | Stop new paid work, preserve progress and reservations, report the reason and unresolved usage |
| Unhandled code error | Save the sanitized traceback; fail the job or stop the run if shared state may be unreliable |
| Disk full, failed log write or database failure | Surface a console error and fail the run; do not continue publishing without a reliable audit trail |

Retries and fallbacks share the existing per-run budget. A timed-out model request may already have been billed; retain its reservation until reconciled or conservatively accounted for. Log each attempt and its final outcome separately, and distinguish unique failed jobs from failed attempts in summary counts.

Persist a stage checkpoint and the associated error reference after failure. On restart, identify interrupted jobs, expire abandoned leases and resume only eligible work. An interrupted run must remain identifiable even if the normal final-summary step never ran; reconstruct its report from persisted events and operations tables.

## Review interface

The local Streamlit review application gets an **Errors** view with filters for run, source, stage, error code, retry exhaustion and resolution status. Each row opens its timeline, sanitized diagnostic, saved input and any candidate claims. The run summary reports attempted/successful/failed/skipped documents, unresolved coverage gaps, retry/fallback counts, latency and model usage/spend.

For example, if 40 of 50 attempted documents succeeded and 10 failed, the report must show both counts and the missing coverage. Failed extraction is never presented as “no requirements found,” zero tuition, or an automatically approved programme.

An error's review state is `open`, `investigating`, `resolved` or `accepted_gap`. A retry that later succeeds remains in the timeline with a recovered outcome. An accepted gap records a decision and reason; it does not establish the missing fact. Resolving an error requires a linked fix/replay and a recorded verification outcome; it never grants publication approval by itself.

## Improve the engine from saved failures

1. Group failures by code/stage to identify recurring problems.
2. Open the source snapshot, parsed input and sanitized diagnostic for a representative error.
3. Fix the adapter, parser, model instructions, schema or validation rule and advance its version.
4. Replay the failed stage into a new run referencing the original error; keep the original log unchanged.
5. Compare old and new candidates, evidence support, validation results and cost. Review critical outputs before publication.
6. Add a small, sanitized regression fixture for a confirmed bug so future changes cannot silently reintroduce it.

Proposed CLI contract; these commands do not exist yet:

```sh
uv run python -m kb_pipeline errors --run-id <run_id> --stage extract
uv run python -m kb_pipeline replay --error-id <error_id> --from-snapshot --offline
uv run python -m kb_pipeline replay --error-id <error_id> --from-snapshot --allow-paid-models --budget-usd 1
```

Offline replay uses saved artifacts and matching cached model outputs, with no HTTP or provider calls. If a required artifact or compatible cached output is missing, stop and report the missing dependency. A changed prompt/schema/model configuration invalidates its model cache entry; offline replay must not relabel old output as a new-model result. A new model request requires the explicit paid-model mode and its budget, even when the source document comes from a saved snapshot. Errors before a snapshot exists require a separate explicit refetch action, not snapshot replay.

## Retention and verification

Keep each run in its own directory and cap/rotate event-file segments so disk use is bounded. Configure the diagnostic size limit, available-disk threshold and retention policy. Do not silently delete evidence still referenced by an open error or retained published fact; mark unavailable artifacts explicitly when retention removes them. Logs are local troubleshooting data, not automatically uploaded training data.

Logging is required in **M1**, rather than deferred to the final handover. Before calling that milestone complete, inject a timeout, a parser failure, a schema failure, missing evidence and a log-write failure. Check that errors are captured with stage/source context, retries stop at their configured limits, affected claims stay unpublished and the run report explains the gap. Restart an interrupted job and demonstrate a saved-input replay. Verify redaction with synthetic secrets, including URL tokens and exception messages. Confirm that a replayed fix is traceable to the original error and can become a regression test.
