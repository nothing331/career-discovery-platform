# Local programme data engine

A separate Python product for collecting official programme information into an evidence-backed SQLite knowledge base. A normal student search reads published data; it does not start collection. Runtime files and secrets stay local.

## Initial dataset and models

The founder chose Computer Science across bachelor's and master's levels, and delegated university/model selection. The initial registry contains **six core programmes across three universities**, rather than claiming complete Germany coverage or padding the programme count with specialisations:

- Saarland University: [English B.Sc.](https://www.uni-saarland.de/en/study/programmes/bachelor/computer-science.html), [M.Sc.](https://www.uni-saarland.de/en/study/programmes/master/informatics.html).
- University of Passau: [B.Sc.](https://www.uni-passau.de/en/bsc-computer-science), [M.Sc.](https://www.uni-passau.de/en/msc-computer-science/).
- University of Freiburg: [B.Sc.](https://www.tf.uni-freiburg.de/en/study-programs/computer-science/b-sc-computer-science), [M.Sc.](https://www.tf.uni-freiburg.de/en/study-programs/computer-science/m-sc-computer-science).

These are collection test cases, not recommendations that a student should apply. The sources exercise English/German instruction, different page layouts and applicant-specific fees/requirements. A named intake has not been selected; the engine does not invent a future year from a recurring deadline.

Generative extraction defaults to **OpenRouter**, with **Groq available for the initial one-programme pilot**. OpenRouter candidates are `qwen/qwen3.5-flash-02-23` and fallback `google/gemini-2.5-flash-lite`. Both advertised `structured_outputs` in [OpenRouter's public model catalogue](https://openrouter.ai/api/v1/models) when selected. Its `models` command prints current pricing/capabilities without a key. The Groq pilot uses `openai/gpt-oss-20b`; Groq documents [strict structured output](https://console.groq.com/docs/structured-outputs) for GPT-OSS 20B/120B. Each provider still needs a live smoke test: mock tests do not establish provider compatibility or extraction accuracy.

## Setup

Python 3.12+ and [uv](https://docs.astral.sh/uv/) are required. The local worker currently supports macOS/Linux because it uses a process file lock.

```sh
cd data-engine
uv sync --extra review
cp -n .env.example .env
uv run python -m kb_pipeline init
uv run python -m kb_pipeline models
```

`.env` is the product-level, ignored environment file. `.env.example` is the committed template. Paths resolve from this product folder, even when commands run from the repository root. Do not overwrite a populated `.env`. Set `LLM_PROVIDER=openrouter` or `LLM_PROVIDER=groq`; only the selected provider's key/model/rates are read. Keys can also come from the process environment and are never committed or printed by `init`. Live requests always require an explicit `--llm`.

## Collect without a model key

```sh
uv run python -m kb_pipeline run --budget-usd 5
# Or collect just one registered programme:
uv run python -m kb_pipeline run --target saarland-bsc --budget-usd 5
```

This fetches the approved seed pages, checks robots policy, follows only same-host HTTPS redirects, archives original bytes, parses HTML/PDF, classifies relevant blocks with local rules, and stages grounded candidate facts. Generic PDF parsing is implemented; the six initial seed documents are HTML. Oversized/poorly parsed sections are held, not silently truncated into facts.

Source bytes have size limits; PDFs have a page limit. Host requests are sequential and delayed, with bounded transient retries. Cross-host redirects and blocked/unsupported sources require source review. The programme registry is intentionally curated: automatic name-to-domain search, broad crawling, JavaScript browser fallback and Jev classification are later adapters, not implemented capabilities of this version.

Jobs and checkpoints persist in SQLite. For separate execution:

```sh
uv run python -m kb_pipeline run --enqueue-only
uv run python -m kb_pipeline work RUN_ID
uv run python -m kb_pipeline status RUN_ID
```

Only one local collection worker runs at a time. After interruption, the next worker can recover abandoned jobs and use saved snapshots. Calling `run` again starts a refresh/review run; it does not rewrite an already published release. Parsed inputs and compatible model results are cached by content/configuration. Conditional HTTP fetch optimisation and automatic scheduling are not implemented yet; a local worker needs the machine to remain on.

## Opt into OpenRouter extraction

After securely configuring the key:

```sh
uv run python -m kb_pipeline run --target saarland-bsc --llm --budget-usd 1
```

No model calls occur without `--llm`. Model/provider prices are bounded through OpenRouter routing preferences, and the application reserves a conservative cost before every paid request. Retries/fallbacks share the run budget. Timeouts and missing usage keep a reservation and pause paid work rather than treating an uncertain charge as free. Account funding/fees and provider billing settings are separate from the application's cap.

Model inputs are archived locally without authorization headers. Responses must pass the JSON schema, exact evidence-location checks and value grounding. Rules and model outputs remain candidates. `requirement` candidates preserve source text and conditions; this version does not compile them into executable admissions/eligibility rules. There is no student matching engine or personal-profile ingestion.

## Test one programme with Groq

In the ignored `data-engine/.env`, set these values and enter your key locally:

```dotenv
LLM_PROVIDER=groq
GROQ_API_KEY=
GROQ_MODEL=openai/gpt-oss-20b
GROQ_INPUT_PER_MILLION=0.075
GROQ_OUTPUT_PER_MILLION=0.30
GROQ_MAX_OUTPUT_TOKENS=4096
```

The existing development machine's `.env` has been prepared for Groq with a blank key. `init` confirms the selected provider/model and whether a key is configured without exposing it. The committed template continues to default to OpenRouter.

From `data-engine/`:

```sh
# Portable synthetic classifier evaluation; no source or model requests:
uv run python -m kb_pipeline evaluate-classifier
# Evaluate every section of the retained Passau master's page:
uv run python -m kb_pipeline evaluate-classifier --dataset evaluation/passau-msc-v1.json
# Rehearse collection from that snapshot, using local rules only:
uv run python -m kb_pipeline pilot
# After adding the Groq key, run the same programme through the LLM layer:
uv run python -m kb_pipeline pilot --llm --budget-usd 0.05
# Re-evaluate an existing pilot's model claims without another provider call:
uv run python -m kb_pipeline evaluate-extraction RUN_ID
```

The pilot is pinned to the official Passau M.Sc. Computer Science HTML snapshot captured on 2026-10-28. It verifies the source SHA-256 and parser version before any model request, checks classifier thresholds, and enqueues only that programme using the retained snapshot. It never refetches the page. This still allows provider requests when `--llm` is supplied; it is not an offline model run. All facts stay pending human review. Local rules alone do **not** count as successful LLM evaluation.

The snapshot itself stays in ignored `data/`; Git contains labels/provenance and 13 selected expected facts, not the full captured page. **A fresh clone needs the exact retained source artifact and its database snapshot entry for this pilot.** A newly fetched or changed page cannot silently substitute for it: retain the original artifact or create and manually review a new version of the evaluation manifest. The portable synthetic classifier evaluation needs neither snapshots nor a key. A normal `run --target passau-msc --llm --budget-usd 0.05` can test a newly fetched page, but cannot reuse this manifest as accuracy evidence when its hash differs.

Groq requests use its native OpenAI-compatible endpoint, strict JSON schema and a capped completion length, with low reasoning effort. There is no automatic cross-provider fallback; OpenRouter credits are not needed for a Groq run. Model inputs, results, errors and reservations retain the normal local audit trail. Provider, model, prompt, schema and rate settings separate caches; changing them requires a new run/replay. HTTP 429, timeouts, uncertain token usage, changed response models and ambiguous HTTP 400 generation/schema failures pause model work without a retry loop. Successful token usage is accounted even if returned JSON is invalid.

Groq's API returns token counts rather than OpenRouter's `usage.cost`. Reports therefore distinguish `estimated_cost_usd` / `cost_basis=token_rate_estimate` from `known_cost_usd` (null for Groq). The internal run ledger's `spent` field is the token-rate estimate for Groq; it is not an invoice. [Groq's model prices](https://console.groq.com/docs/models), checked 2026-10-31, listed GPT-OSS 20B at $0.075/M input and $0.30/M output. Verify/update the configured rates when pricing/model changes; GPT-OSS 120B needs its own rates. Free-tier availability, reasoning tokens, retries and billing adjustments can affect the account bill. The $0.05 pilot cap bounds requests using configured estimates and conservative reservations, not a provider-enforced dollar ceiling. Provider spend settings remain separate. `models` under Groq prints configured estimates/documentation without calling the provider or claiming live prices.

## Classifier and extraction evaluation

The implemented classifier is a local binary relevance filter (`keyword-v2`), not Jev or a trained model. `evaluation/classifier-smoke-v1.json` contains 34 manually written English/German examples. `evaluation/passau-msc-v1.json` independently labels all 164 parsed sections of the retained programme, including titles, qualification/language alternatives, deadlines, fees, navigation and marketing. Labels were assigned by reading the source, not by accepting classifier predictions.

Reports include the confusion matrix, precision, recall, critical misses and every mismatch. The pilot requires recall >=95%, precision >=70%, and zero critical misses. The precision threshold deliberately tolerates extra text to avoid dropping admission conditions; it is a development gate, not a product accuracy target. Source review and these examples exposed missed titles/degree rows, examination-regulation pointers and unheaded `must`/`required` conditions, which were added to the rules. The retained real-page evaluation reports 100% recall (28/28), 75.7% precision (28/37), and no critical misses. Nine irrelevant blocks still pass the filter and remain visible in the report. These are development fixtures used during tuning, **not held-out validation or country-wide accuracy estimates**.

Extraction evaluation considers only claims marked with the selected LLM provider, not rule-generated candidates. It checks the exact source snapshot, 13 expected facts/condition phrases, verbatim grounding, validation holds/conflicts and job completion. A missed expected fact or ungrounded model claim fails the pilot. Missing applicant/intake scope remains a hold rather than an invented value; a passing regression does not approve those facts or verify every additional claim semantically. The same fixture can be rerun after setting `LLM_PROVIDER=openrouter` and adding that key. It measures provider/model changes without changing the underlying source.

Evaluation JSON reports are written under ignored `data/evaluations/`. CLI diagnostics go to stderr so a single pilot/evaluation report on stdout remains machine-readable. Exit code 1 means evaluation failed, source provenance mismatched, or execution failed; inspect the JSON report and normal local error logs. Without `--llm`, the extraction evaluation is explicitly `not_run`.

## Inspect and review

```sh
uv run --extra review streamlit run review/app.py
uv run python -m kb_pipeline claims RUN_ID
uv run python -m kb_pipeline errors RUN_ID --stage validate
```

The local review UI has Claims & evidence, Errors and Published catalogue views. Check the official source, quote, applicant group, intake and exceptions. Unsupported values, missing scope and conflicting candidates cannot be approved. Rejecting a candidate requires a reason; missing information remains unknown.

```sh
uv run python -m kb_pipeline review CLAIM_ID "Reviewer name" --approve --confirm-evidence
uv run python -m kb_pipeline review HELD_CLAIM_ID "Reviewer name" --reject --note "Scope not established"
uv run python -m kb_pipeline publish RUN_ID
```

Every candidate in a run needs an explicit review decision. Every published programme needs an approved title. Publication is atomic, and published review history is immutable. The human reviewer is responsible for checking semantic applicability; a heuristic quality score is not a probability or an admissions guarantee. No real source facts were automatically approved during implementation.

## Local errors, replay and improvements

```text
data/
  poc.db
  raw/DE/<target>/<content-hash>.html
  parsed/<content-hash>/<parser-version>/document.json
  model_inputs/<request-fingerprint>.json
  model_cache/<request-fingerprint>.json
  evaluations/<evaluation-id>.json
  logs/<run-id>/events.jsonl
  logs/<run-id>/run_summary.json
  logs/<run-id>/diagnostics/<error-id>.json
  exports/catalogue.json
```

Events include run/job/source/stage context. Diagnostics retain sanitized tracebacks. The SQLite error index supports investigation in the Errors view. Successful retries remain in the timeline; reports distinguish error events from affected jobs. Local log-write/disk-limit failures stop the run.

```sh
uv run python -m kb_pipeline replay ERROR_ID --from-snapshot --offline
uv run python -m kb_pipeline replay ERROR_ID --from-snapshot --allow-paid-models --budget-usd 1
uv run python -m kb_pipeline resolve-error ERROR_ID REPLAY_RUN_ID "Developer name" "Fix and verification details"
```

Offline replay never calls sources or providers. It fails when required snapshots/cache entries are unavailable; changing a prompt/schema/model does not make old model output compatible. Pre-snapshot failures need an explicit new collection run. Replays retain the original error link; resolving an error requires a successful linked replay that no longer reports that error code/stage. Error resolution does not approve facts. Keep original logs and add a small sanitized regression fixture for verified bugs.

Event files rotate within a bounded per-run limit; the engine stops instead of deleting older segments at the limit. Runtime artifacts are retained locally with a disk-space guard. Automatic retention cleanup is not implemented: do not delete evidence referenced by open errors or published facts without a deliberate retention decision.

`data/`, `.env` and `.venv/` are ignored by this product's Git rules. The workspace export builder also excludes `data-engine/data/`, so source captures, model inputs, diagnostics and cost reports cannot enter hosted HTML through the reference-library scan. Deliberately sanitized test fixtures are the exception, kept under `tests/`.

## Application access

```sh
uv run python -m kb_pipeline serve
uv run python -m kb_pipeline export
```

The read-only API binds to `127.0.0.1:8000`:

- `GET /health`
- `GET /v1/programmes?country=DE&level=master`
- `GET /v1/programmes/{id}`
- `GET /v1/programmes/{id}/evidence`

It returns approved, versioned facts and evidence only; before manual publication the catalogue is empty. Collection/review/publication stay in the local CLI/UI. Do not expose the review UI publicly. A hosted multi-user admin API needs authentication, authorisation, durable hosting and database/storage deployment as a separate milestone. The existing Sites planning portal does not execute this Python worker or host the local database.

## Verification

```sh
uv run pytest -q
# From the repository root, with the workspace build dependency installed:
python3 -m unittest discover -s product-workspace/tests
```

Tests cover extraction/evidence holds, publication gates, API visibility, bounded retries, robots policy, redirects, restarts, offline replay, redaction, log-write failures, model billing uncertainty/cache behaviour and synthetic PDF parsing. `uv.lock` records the dependency versions. Database schema changes use Alembic migrations; revision 001 is frozen, not generated dynamically at startup.


### First real run

The no-key implementation check completed all six registered HTML sources and staged 38 candidate facts: 19 passed deterministic checks and 19 were held for missing applicant/intake scope. All remain pending human review. A Freiburg layout-table failure from the earlier run was reproduced and fixed using a saved snapshot; the original failure remains in local history with a linked resolution. No paid model calls occurred because the secure key request expired. Live OpenRouter schema compatibility, model accuracy and actual costs remain unverified.
