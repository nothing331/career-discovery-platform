# Local programme data engine

A separate Python product for collecting official programme information into an evidence-backed SQLite knowledge base. A normal student search reads published data; it does not start collection. Runtime files and secrets stay local.

## Initial dataset and models

The founder chose Computer Science across bachelor's and master's levels, and delegated university/model selection. The initial registry contains **six core programmes across three universities**, rather than claiming complete Germany coverage or padding the programme count with specialisations:

- Saarland University: [English B.Sc.](https://www.uni-saarland.de/en/study/programmes/bachelor/computer-science.html), [M.Sc.](https://www.uni-saarland.de/en/study/programmes/master/informatics.html).
- University of Passau: [B.Sc.](https://www.uni-passau.de/en/bsc-computer-science), [M.Sc.](https://www.uni-passau.de/en/msc-computer-science/).
- University of Freiburg: [B.Sc.](https://www.tf.uni-freiburg.de/en/study-programs/computer-science/b-sc-computer-science), [M.Sc.](https://www.tf.uni-freiburg.de/en/study-programs/computer-science/m-sc-computer-science).

These are collection test cases, not recommendations that a student should apply. The sources exercise English/German instruction, different page layouts and applicant-specific fees/requirements. A named intake has not been selected; the engine does not invent a future year from a recurring deadline.

Generative extraction defaults to **OpenRouter**, with **Groq available for the initial one-programme pilot**. OpenRouter candidates are `qwen/qwen3.5-flash-02-23` and fallback `google/gemini-2.5-flash-lite`. Both advertised `structured_outputs` in [OpenRouter's public model catalogue](https://openrouter.ai/api/v1/models) when selected. Its `models` command prints current pricing/capabilities without a key. The Groq pilot uses `openai/gpt-oss-20b`; Groq documents [strict structured output](https://console.groq.com/docs/structured-outputs) for GPT-OSS 20B/120B. Two live Groq calls verified transport and structured output on 2026-10-31 and exposed extraction errors; the corrected, exact-source replay now passes the selected regression. OpenRouter remains untested live. Neither one-page regression nor mock tests establish general extraction accuracy.

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

## Pipeline stages (rules-v5 / claims-v3 / grounded-v4)

1. Fetch and parse the registered programme page.
2. **Follow-ups (depth 1).** `links.select_followups` (`roles-v2`) picks up to `ENGINE_FOLLOWUP_LIMIT` (default 6, 0 disables, max 12) same-host admissions/fees/regulation/language/deadline links, HTML or PDF. Set `follow_links: false` on a registry target to opt out. Pages are fetched through the normal robots/host/delay-checked fetcher; a URL shared by several programmes is fetched once per run. Offline, replay and pilot runs never use the network: they reuse the newest saved snapshot of a URL or record the page as `skipped`. Each page is audited in `ops_pages` (`done|failed|skipped`). A failing follow-up is logged as a warning and does not fail the job (budget/model stop codes still pause the run). Links naming only the other degree level are skipped. Claims from follow-up pages of role `regulations` whose text never names the programme subject are held as `FOLLOWUP_PROGRAMME_UNVERIFIED`. Model size/shape failures (`MODEL_DOCUMENT_LIMIT`, `SECTION_TOO_LARGE`, `MODEL_TRUNCATED_OR_REFUSED`, `MODEL_SCHEMA_INVALID`, `MODEL_REQUEST_REJECTED`) log `extract.model_skipped` and keep rule candidates. Replays prefer the parent job's recorded follow-up snapshots. Follow-up pages emit no `programme_title`; each claim is validated against, and stored with the snapshot of, its own page.
3. Rule (+ optional LLM) extraction, grounding and validation. New hold codes: `NOT_A_FACT` (heading or question text) and `APPLICANT_SCOPE_CONFLICT` (general scope claimed but the block names an applicant group). Unqualified blocks get the scope `general (no specific applicant group stated)`; day+month deadlines tied to one semester get the intake `winter semester (recurring)` / `summer semester (recurring)`.
4. **Dedupe.** Identical claims (same programme, source hash and body, ignoring method) are stored once; `agreeing_methods` lists every method that produced it.
5. **Structured facts** (`regex-v2`): typed facts (language tests, grades, fees, windows, ...) derived only from `valid` claims into `structured_facts`, each with a verbatim `evidence_text` and its evidence claim ids. On publish, only facts whose evidence claims are all approved are copied to `kb_structured_facts`; the catalogue and `GET /v1/programmes/{id}/structured` expose them.
6. **Latest run only.** Approving or publishing an older run fails with `RUN_SUPERSEDED` when a newer run holding a completed job for the same programme is awaiting review or published (rejections remain possible). `status` and the review UI show `superseded`.

Link selector, normalizer versions and the follow-up limit are frozen into each run; changing them requires a new run (`RUN_CONFIG_CHANGED`). New tables come from Alembic revision 002 (`ops_pages`, `structured_facts`, `kb_structured_facts`, `staging_claims.claim_key/agreeing_methods`); existing claims keep NULL keys. Inspect with `uv run python -m kb_pipeline structured RUN_ID [--kind language_test]`.

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

`init` confirms the selected provider/model and whether a key is configured without exposing it. The committed template continues to default to OpenRouter. The development machine is configured for Groq; its user-provided key remains only in the ignored `.env`.

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

Groq requests use its native OpenAI-compatible endpoint, strict JSON schema and a capped completion length, with low reasoning effort. There is no automatic cross-provider fallback; OpenRouter credits are not needed for a Groq run. Model inputs, results, errors and reservations retain the normal local audit trail. Provider, model, prompt, schema and rate settings separate caches; changing them requires a new run/replay. HTTP 429, timeouts, uncertain token usage and changed response models pause model work without a retry loop. A Groq HTTP 400 does not pause the run: the whole reservation is charged as spent (`model.charged_reservation`, usage is unknown) and the request fails as `MODEL_SCHEMA_INVALID` (Groq `json_validate_failed`/schema errors) or `MODEL_REQUEST_REJECTED` (anything else), both non-stop codes; the model pass for that chunk is skipped and rule claims are kept. Every HTTP >= 400 writes a redacted, 1000-character response body and provider error code/type to the `model.http_error` event and the failure diagnostics. In a multi-chunk document, a skipped chunk keeps the claims of the other chunks. Successful token usage is accounted even if returned JSON is invalid.

Groq's API returns token counts rather than OpenRouter's `usage.cost`. Reports therefore distinguish `estimated_cost_usd` / `cost_basis=token_rate_estimate` from `known_cost_usd` (null for Groq). The internal run ledger's `spent` field is the token-rate estimate for Groq; it is not an invoice. [Groq's model prices](https://console.groq.com/docs/models), checked 2026-10-31, listed GPT-OSS 20B at $0.075/M input and $0.30/M output. Verify/update the configured rates when pricing/model changes; GPT-OSS 120B needs its own rates. Free-tier availability, reasoning tokens, retries and billing adjustments can affect the account bill. The $0.05 pilot cap bounds requests using configured estimates and conservative reservations, not a provider-enforced dollar ceiling. Provider spend settings remain separate. `models` under Groq prints configured estimates/documentation without calling the provider or claiming live prices.

### Rate limits

Model calls are paced by a rolling 60-second window using actual response token usage (`prompt_tokens + completion_tokens`) plus request counts, so back-to-back chunks wait instead of tripping provider limits. Defaults: Groq `GROQ_TPM_LIMIT=8000` / `GROQ_RPM_LIMIT=30` (free-tier base limits), OpenRouter `OPENROUTER_TPM_LIMIT=0` / `OPENROUTER_RPM_LIMIT=0` (disabled); `0` disables a limit. Waits over 1 s are logged as `model.paced`. An HTTP 429 releases its reservation, waits for `retry-after` (or Groq's `x-ratelimit-reset-*` headers, else 5 s doubling), capped by `LLM_RATE_LIMIT_MAX_WAIT` (60 s), and retries up to `LLM_RATE_LIMIT_RETRIES` (4) times, emitting `model.rate_limited`. If retries are exhausted the run still pauses with `MODEL_RATE_LIMIT`. These settings do not affect caches or run configs. The Groq Developer tier has far higher limits; raise the TPM/RPM values to run faster.

## Classifier and extraction evaluation

The implemented classifier is a local binary relevance filter (`keyword-v2`), not Jev or a trained model. `evaluation/classifier-smoke-v1.json` contains 34 manually written English/German examples. `evaluation/passau-msc-v1.json` independently labels all 164 parsed sections of the retained programme, including titles, qualification/language alternatives, deadlines, fees, navigation and marketing. Labels were assigned by reading the source, not by accepting classifier predictions.

Reports include the confusion matrix, precision, recall, critical misses and every mismatch. The pilot requires recall >=95%, precision >=70%, and zero critical misses. The precision threshold deliberately tolerates extra text to avoid dropping admission conditions; it is a development gate, not a product accuracy target. Source review and these examples exposed missed titles/degree rows, examination-regulation pointers and unheaded `must`/`required` conditions, which were added to the rules. The retained real-page evaluation reports 100% recall (28/28), 75.7% precision (28/37), and no critical misses. Nine irrelevant blocks still pass the filter and remain visible in the report. These are development fixtures used during tuning, **not held-out validation or country-wide accuracy estimates**.

Extraction evaluation considers only claims derived from the selected LLM provider, not rule-generated candidates. It checks the exact source snapshot, 13 expected facts/condition phrases, verbatim grounding, validation holds/conflicts and job completion. A missed expected fact or ungrounded model claim fails the pilot. Missing applicant/intake scope remains a hold rather than an invented value; a passing regression does not approve those facts or verify every additional claim semantically. The same fixture can be rerun after setting `LLM_PROVIDER=openrouter` and adding that key. It measures provider/model changes without changing the underlying source.

The deterministic `exact-blocks-v1` grounding stage runs on both fresh and compatibly cached model candidates. It can restore a wrong location only when the quote has a unique verbatim match among the blocks supplied to the model. A merged requirement can expand only into one uniquely matching consecutive sequence of complete blocks in the original document; its full quoted context is retained with every resulting candidate. Partial requirement/fee selections retain the full source paragraph, including waivers and semester charges. A known language-table label is removed consistently with local extraction. Ambiguous matches, fabricated text, missing blocks and oversized paragraphs stay invalid/held; there is no fuzzy correction or creation of candidates from unselected sections. Grounding actions and raw candidate counts are logged; the original structured response stays intact in the model cache. `model_claim_count` counts staged model-derived candidates after this step, so a verified multi-block expansion can exceed the raw response item count.

Unknown strings such as `"null"` and `"not established"` are canonicalised rather than treated as established scope. Deadline intake needs a year explicitly backed by the source block/heading; a recurring season alone stays held. Requirement candidates must retain the full paragraph. Runs record grounding/schema/extractor versions, and older pending candidates cannot be approved or published under outdated checks. Re-extract/replay them; published history is not rewritten. A new deterministic grounding version can replay a compatible raw model response without another provider call; changing the actual prompt/schema/model still requires a matching model cache entry.

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

### First live Groq check — 2026-10-31

After the user configured the key, the first call (`6f6123f04bf04c4aa89b4c853729c224`) returned valid structured JSON but covered only 7/13 selected expectations, emitted numeric units instead of digits and used an unknown string for intake. Its token-rate estimate was $0.0004872. The tightened prompt/schema and scope gates produced 10/13 coverage on the second call (`2f26493429974404a03cd5635f308af4`), estimated at $0.000822975. That response merged four language blocks and attached wrong IDs; source checks caught it. A teaching-language label also caused a false string conflict with local extraction.

Fixed exact-source grounding and added sanitized synthetic regressions. Linked offline replay `b3f74209cc7b4bb195a4338d301f7ac2` used that same second response with both network clients explicitly blocked. It passed all 13 selected expectations with zero invalid model-derived candidates and zero new provider cost. There are 30 pending candidates: eight deterministic-valid, 19 held for applicant scope and three held for intake scope. The 16 raw model items became 19 source-grounded candidates; 11 additional local-rule candidates are excluded from LLM accuracy checks. The raw response, initial failures and grounding actions remain local. The report is `data/evaluations/f9b5aa50db414e72bd55941ea00c20b7.json`.

The two live requests total **$0.001310175 in configured token-rate estimates**, not an account invoice. No third live request, human approval or publication occurred. **70 tests pass**, covering these regressions as well as the original engine checks. This is a development regression on one saved page, not evidence that every admission condition was captured or verified. Actual account charges, held applicability/effective intake, additional claim semantics, new sources and OpenRouter compatibility still need their respective checks.
