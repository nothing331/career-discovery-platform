# Open-Source AI Scraping & Extraction Toolchain

**Version:** 1.0 · **Last reviewed:** 2026-07-29
**Scope:** How to acquire, extract, validate, and **store** the data defined in `01-DATA-MODEL.md` from the sources in `02-DATA-SOURCES.md` — using open-source and free-tier tools. This document ends where the knowledge base begins: with clean, provenance-tagged rows in Postgres. Graph and vector construction come *after*, and are deliberately out of scope.

---

## 0. The one architectural decision that matters

**Do not use an "AI scraper" as a general-purpose data acquisition strategy.** Sending an LLM to browse a site and figure it out is a demo, not a pipeline. It is slow, non-deterministic, expensive at scale, and impossible to debug when a number turns out wrong six months later.

The correct shape is a **layered pipeline where the LLM does exactly one job**: turning already-fetched, already-cleaned text into typed JSON with a verbatim quote attached.

```
 ┌──────────┐  ┌─────────┐  ┌────────┐  ┌───────────┐  ┌──────────┐  ┌─────────┐
 │ DISCOVER │→ │  FETCH  │→ │ CLEAN  │→ │  EXTRACT  │→ │ VALIDATE │→ │  STORE  │
 │  seeds   │  │ HTML/PDF│  │ →text  │  │   (LLM)   │  │ (no LLM) │  │ Postgres│
 └──────────┘  └─────────┘  └────────┘  └───────────┘  └──────────┘  └─────────┘
    IDs/URLs      raw+hash     markdown     typed JSON     tier A/B/C    + audit
                  ↓ archived                + evidence
                  forever                     quotes
```

Five rules that follow from this:

1. **Deterministic where possible, LLM only where necessary.** A CSS selector that gets the Semesterbeitrag costs nothing and never hallucinates. Use the LLM for prose-heavy pages (admission regulations), not for tables you could parse.
2. **Archive the raw bytes forever.** Storage is ~free; re-crawling is not, and neither is being unable to prove where a number came from. Every extraction must be reproducible from the archive without touching the network again.
3. **Content-hash everything.** ~90% of pages are unchanged on any given re-crawl. Hashing turns your monthly refresh from a €40 LLM bill into a €4 one.
4. **The LLM never decides truth.** It proposes typed JSON. Deterministic code (§5) decides whether that JSON is stored, and at what quality tier.
5. **Cheap model + tight schema beats expensive model + loose prompt.** Every time. A Flash-class model with a 6-field schema and a required evidence quote outperforms a frontier model asked to "extract everything relevant."

---

## 1. Layer 1 — Discovery (build the URL frontier)

Before crawling anything, build the canonical list of *what exists*. Getting this wrong means duplicate institutions polluting your KB forever.

| Tool | Link | Use here |
|---|---|---|
| **ROR data dump** | [ror.org/data](https://ror.org/data) · Zenodo, CC0 | ~110k research orgs with canonical names, aliases, geo, Wikidata/GRID cross-IDs. **Start here.** Gives you `institution.ror_id` and the alias list that makes "TUM" = "TU München" work. |
| **Hochschulkompass `hs_liste.txt`** | [downloads page](https://www.hochschulkompass.de/en/higher-education-institutions/downloads.html) | Tab-separated list of every German HEI. Personal-use terms — use as a discovery seed, not as published content. |
| **Wikidata SPARQL** | [query.wikidata.org](https://query.wikidata.org/) | Fill gaps: German/English name pairs, logos, coordinates, founding year. One query gets all German universities. |
| **Destatis GENESIS API** | [destatis.api.bund.dev](https://destatis.api.bund.dev/) · [restatis (R)](https://correlaid.github.io/restatis/) | Authoritative student counts. Free, no registration, Data Licence Germany 2.0. |
| **`sitemap.xml` + [katana](https://github.com/projectdiscovery/katana)** | Go, fast crawler | For each university domain, harvest candidate URLs. Filter on German keywords: `zulassung`, `bewerbung`, `studiengang`, `semesterbeitrag`, `ordnung`, `international`. |
| **[Splink](https://github.com/moj-analytical-services/splink)** | Probabilistic record linkage, DuckDB backend | **Deduplicate institution records across ROR + Hochschulkompass + Destatis + DAAD.** Fellegi-Sunter model, unsupervised, links a million records on a laptop in ~a minute. Alternatives: [dedupe](https://github.com/dedupeio/dedupe) (active learning, needs labelling), [Zingg](https://github.com/zinggAI/zingg) (Spark). Splink is the right default at your scale. |

**Output of this layer:** a `crawl_target` table — `(url, source_id, entity_type, expected_fields[], priority, next_refresh_due)`. Everything downstream is driven by this table, not by hardcoded URL lists.

---

## 2. Layer 2 — Fetch

### 2.1 Pick the lightest tool that works

Roughly 70% of German university pages are server-rendered HTML. Do not launch a browser for those.

| Tool | Link | When to use | Notes |
|---|---|---|---|
| **httpx + tenacity** | [httpx](https://www.python-httpx.org/) | Static pages, APIs (Destatis, BA Jobsuche, DEQAR, ROR) | HTTP/2, async, connection pooling. Wrap in `tenacity` for exponential backoff. Fastest and cheapest path. |
| **Scrapy** | [scrapy.org](https://scrapy.org/) | High-volume static crawling — Semesterbeitrag pages, Stellenwerk listings, uni-assist | Battle-tested: built-in `AUTOTHROTTLE`, `robots.txt` obedience, dedup filter, retry middleware, resumable jobs. **The workhorse.** |
| **Crawl4AI** | [github.com/unclecode/crawl4ai](https://github.com/unclecode/crawl4ai) · ~66k★ | Turning arbitrary pages into clean LLM-ready markdown | Local-first, no API calls, Apache 2.0. Handles JS via Playwright under the hood. Its built-in markdown generator + content filters typically **cut token counts 60–80% vs raw HTML** — that is the main cost lever in the whole pipeline. |
| **Firecrawl (self-host)** | [github.com/firecrawl/firecrawl](https://github.com/firecrawl/firecrawl) | Same job, hosted/managed option; generous free tier | Use the cloud free tier for prototyping, self-host or switch to Crawl4AI for volume. AGPL — check licence fit before embedding. |
| **Playwright** | [playwright.dev/python](https://playwright.dev/python/) | JS-rendered pages: DAAD programme search, some portals | Slow (~2–5s/page). Use `route.abort()` on images/fonts/analytics — cuts page time roughly in half. |
| **Patchright** | [github.com/Kaliiiiiiiiii-Vinyzu/patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright) | Drop-in stealth Playwright fork | Patches the CDP `Runtime.enable` leak. Zero code change. Reach for this only if a site actually blocks you. |
| **Camoufox** | [camoufox.com](https://camoufox.com/) | Hardest anti-bot targets (WG-Gesucht, ImmoScout) | Firefox fork with C++-level fingerprint patches; ~0% headless detection. Slow. **Last resort — and reconsider whether you should be scraping that source at all.** |
| **curl-impersonate / curl_cffi** | [curl_cffi](https://github.com/lexiforest/curl_cffi) | TLS-fingerprint blocks without needing a browser | Much cheaper than a browser when the block is TLS-level, not JS-level. |

> **Judgement call:** for a study-abroad KB, you should need Patchright/Camoufox for *at most* the housing sites. If you find yourself fighting anti-bot on a university page, you're crawling too fast. Slow down instead.

### 2.2 Politeness configuration (non-negotiable)

```python
# scrapy settings.py
ROBOTSTXT_OBEY = True
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
DOWNLOAD_DELAY = 2.0                      # 2-5s per host
CONCURRENT_REQUESTS_PER_DOMAIN = 1
USER_AGENT = "YourProductBot/1.0 (+https://yourproduct.com/bot; contact@yourproduct.com)"
HTTPCACHE_ENABLED = True                  # ETag / Last-Modified
RETRY_TIMES = 3
```

Identify yourself with a real contact URL. German university IT departments will email you before blocking you if you do — and a polite reply has repeatedly turned into a data-sharing offer.

**Also automate the legal check** (see `02-DATA-SOURCES.md` §1): for every new host, fetch `robots.txt` *and* the Impressum/ToS, run a small classifier or LLM call over the ToS asking "does this text reserve rights against text and data mining?", and store the answer in `source.tdm_reservation_detected`. The LG Hamburg ruling indicated a natural-language reservation can count as machine-readable — so "we didn't parse the ToS" is not a defence.

### 2.3 Archive immediately, before anything else

```python
snapshot = {
    "url": url, "fetched_at": now, "http_status": r.status_code,
    "content_hash": hashlib.sha256(r.content).hexdigest(),
    "raw_path": f"s3://kb-raw/{source_id}/{date}/{url_hash}.html.gz",
    "etag": r.headers.get("ETag"), "lang": detect(text),
}
if content_hash == previous_hash:
    mark_checked(url); return          # ← skips ~90% of work on refresh runs
```

Store to **MinIO** ([min.io](https://min.io/), self-hosted S3) or plain gzipped files on disk. Never delete. This archive is what makes your pipeline re-runnable and your facts defensible.

---

## 3. Layer 3 — Clean (HTML/PDF → text)

Token cost is proportional to input size. This layer is where you save most of your money, and it needs no AI at all.

### 3.1 HTML

| Tool | Link | Use |
|---|---|---|
| **trafilatura** | [github.com/adbar/trafilatura](https://github.com/adbar/trafilatura) | **Best boilerplate removal for German-language pages.** Academic provenance, benchmarks well, extremely fast, no ML dependency. Strips nav/footer/cookie banners, keeps main content. First thing to try. |
| **Crawl4AI markdown generator** | (as above) | Fit-markdown + pruning/BM25 content filters; integrates fetch+clean in one step |
| **selectolax** | [github.com/rushter/selectolax](https://github.com/rushter/selectolax) | When you *do* know the selector — 10–20× faster than BeautifulSoup. Use for the ~30% of pages with stable structure (fee tables, deadline boxes). |
| **html-to-markdown / markdownify** | [markdownify](https://github.com/matthewwithanm/python-markdownify) | Preserve table structure as markdown — LLMs read markdown tables far more reliably than HTML `<table>` soup |

**Table-preservation matters here.** Semesterbeitrag breakdowns and NC cutoff lists are tables. Converting them to markdown before extraction materially improves accuracy over flattening to plain text.

### 3.2 PDF — the *Zulassungsordnung* problem

This is where your product's real value lives (see `01-DATA-MODEL.md` §2.4) and where naive pipelines fail. German admission regulations are structured legal documents with numbered paragraphs, nested lists, and ECTS tables.

| Tool | Link | Best for | Notes |
|---|---|---|---|
| **Docling** | [github.com/docling-project/docling](https://github.com/docling-project/docling) · IBM, MIT | **Default choice here.** PDF/DOCX/PPTX/XLSX/HTML → structured markdown or JSON, with strong table structure recovery and document hierarchy. Native LangChain/LlamaIndex integration. Preserves the § numbering you need for citations. |
| **Marker** | [github.com/datalab-to/marker](https://github.com/datalab-to/marker) | High-fidelity structure, equations, forms | Excellent quality; **check the licence** — it carries commercial-use restrictions above a revenue threshold. |
| **MinerU** | [github.com/opendatalab/MinerU](https://github.com/opendatalab/MinerU) | Complex layouts, multi-column | Shanghai AI Lab. Strongest on CJK; still very good on European multi-column documents. |
| **olmOCR** | [github.com/allenai/olmocr](https://github.com/allenai/olmocr) | **Scanned** PDFs, legacy archives | VLM-based OCR. Some older university statutes are scans — this is your fallback. Needs a GPU. |
| **pymupdf4llm** | [pymupdf4llm](https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/) | Quick native-text PDFs | Fastest; try first, fall back to Docling if the output is garbled. AGPL. |

**Recommended cascade:**
```
pymupdf4llm  →  is text_len < 500 or table_count == 0?
             →  Docling      →  still poor (scanned)?
                             →  olmOCR
```
Log which stage produced the text into `extraction_run.method` — when a requirement turns out wrong, the first question is always "how was this PDF parsed?"

### 3.3 Chunking for extraction

Do **not** feed a 40-page Zulassungsordnung to the model in one call. Split on structure (§ / Abschnitt headings), keep sections intact, and **route** chunks: only chunks matching `zulassungsvoraussetzung|eignung|nachweis|ECTS|Sprachkenntnisse|Frist` go to the requirements extractor. Everything else is skipped. This alone typically cuts LLM spend by 5–10×.

---

## 4. Layer 4 — Extract (the only place an LLM belongs)

### 4.1 Framework choice

| Tool | Link | Strengths | Pick it when |
|---|---|---|---|
| **Instructor** | [python.useinstructor.com](https://python.useinstructor.com/) | Wraps any LLM client with Pydantic validation + automatic retry on validation failure. Python/TS/Go/Ruby. | **The safe default.** Near-zero learning curve, works with every provider, covers the 80% case. Start here. |
| **LangExtract** | [github.com/google/langextract](https://github.com/google/langextract) | **Source grounding** — every extracted value maps to its exact character offset in the source text. Plus schema enforcement and multi-model support (Gemini/OpenAI/Ollama). | **Strongly recommended for the requirements layer.** It implements Validation Gate 2 (evidence grounding) natively — the check that kills most hallucinations. Purpose-built for long documents with many extractions. |
| **Outlines** | [github.com/dottxt-ai/outlines](https://github.com/dottxt-ai/outlines) | Constrains generation at the token level via FSM — invalid JSON is *mechanically impossible*, not retried | High-throughput local inference where retries cost real GPU time. Pairs with vLLM. |
| **BAML** | [boundaryml.com](https://boundaryml.com/) | Schema-as-language with its own parser; strong versioning and testing story | You want prompt/schema versioning as first-class engineering artefacts, or share schemas across Python and TS services |
| **PydanticAI** | [ai.pydantic.dev](https://ai.pydantic.dev/) | Agent framework with typed outputs, from the Pydantic team | You later need multi-step agentic extraction (e.g. follow a link to find the missing deadline) |

**Recommendation for this project:** **Instructor for structured pages, LangExtract for regulation PDFs.** The source-grounding feature is not a nice-to-have here — it is the difference between "the model says 24 ECTS in Mathematics" and "the model says 24 ECTS in Mathematics, and here is the sentence on page 7 that says so." Your users are making €12,000 decisions on these numbers.

### 4.2 The natural-language scrapers — where they fit

| Tool | Link | Honest assessment |
|---|---|---|
| **ScrapeGraphAI** | [github.com/ScrapeGraphAI/Scrapegraph-ai](https://github.com/ScrapeGraphAI/Scrapegraph-ai) | Describe what you want in plain English; the LLM figures out extraction, no selectors. **Genuinely useful for the long tail** — 400 university fee pages with 400 different layouts. Too slow and non-deterministic for high-volume repeat crawling. |
| **LLM Scraper** | [github.com/mishushakov/llm-scraper](https://github.com/mishushakov/llm-scraper) | TypeScript, Playwright + Zod schemas. Good if your stack is TS. |
| **Crawl4AI `LLMExtractionStrategy`** | (as above) | Built-in schema-driven extraction — avoids adding another dependency if you're already using Crawl4AI |

**Use these for exploration and the long tail; use Instructor/LangExtract over pre-cleaned text for anything you run monthly.** A good pattern: use ScrapeGraphAI *once* on a new site to discover where the data lives, then write a cheap deterministic selector from what it found.

### 4.3 Model choice and cost

| Option | Link | Cost | Verdict for this project |
|---|---|---|---|
| **Gemini Flash-Lite / Flash class** | [ai.google.dev](https://ai.google.dev/pricing) | ~$0.10/M input (Lite) → ~$1.50/M (Flash) | **Start here.** Full extraction pass over ~25k programme pages lands in the **$10–40** range. Long context handles whole regulations. Free tier is enough to build the gold set. |
| **Local: Qwen 3.x / Gemma / GLM via vLLM** | [vLLM](https://github.com/vllm-project/vllm) · [Ollama](https://ollama.com/) | Hardware only | Qwen3-class models are now genuinely strong at JSON extraction and native tool calling. Worth it **only above ~$20k/month API spend** — below that, the 10–20 engineering hours/month of maintenance costs more than the API. You will not hit that threshold. |
| **SGLang / llama.cpp** | [SGLang](https://github.com/sgl-project/sglang) | Hardware only | Same conclusion. Revisit at scale. |

> **Do the arithmetic before self-hosting.** Your entire corpus is ~25k documents refreshed monthly. That is a rounding error on a Flash-class API bill and a full-time job on your own GPUs. Use the API; spend the saved time on requirement extraction quality.

### 4.4 Prompt discipline (this is where accuracy is won)

```python
class LanguageRequirement(BaseModel):
    test: Literal["IELTS","TOEFL_iBT","TestDaF","DSH","telc","Goethe","Duolingo"]
    minimum_overall: float | None
    component_minimums: dict[str, float] | None
    is_mandatory: bool
    waiver_conditions: str | None
    evidence_quote: str = Field(description="Verbatim sentence from the source. Must appear character-for-character.")
    confidence: float = Field(ge=0, le=1)
```

Rules that matter more than model choice:

- **One schema per call.** Batch by theme — identity / requirements / money / dates. Asking for 40 fields at once collapses accuracy.
- **Demand `null` explicitly:** *"If the source text does not state this, return null. Do not infer. Do not use general knowledge about German universities."* Model priors about typical German admission rules are the #1 source of plausible-but-wrong facts in this domain.
- **Require `evidence_quote` on every non-null field.** Feeds Gate 2. Non-optional.
- **Extract from the German original**, and ask for the German text preserved plus an English translation. Never extract from the English summary page when a German original exists — it is legally non-binding and often stale.
- **Pin the model version** and store it in `extraction_run.model`. An unannounced provider-side model update silently changes your dataset.
- **Version your prompts** in git alongside the schema, and record `prompt_version` on every run.

---

## 5. Layer 5 — Validate (deterministic code, zero LLM)

The five gates from `01-DATA-MODEL.md` §6, with tooling attached. Failure at any gate routes the record to a review queue **with the failing gate recorded**.

| Gate | Tool | Implementation |
|---|---|---|
| **1. Schema** | [Pydantic v2](https://docs.pydantic.dev/) | Types, enums, ranges. IELTS ∈ [0,9] step 0.5; German grade ∈ [1.0,4.0]; tuition ∈ [0,5000]. Catches ~15% of first-pass output for free. |
| **2. Evidence grounding** | plain Python, or **LangExtract natively** | Assert `normalize(evidence_quote) in normalize(source_text)`. If absent → **discard, don't review**: the model fabricated it. Highest value-per-line-of-code in the entire pipeline. |
| **3. Business rules** | [Pandera](https://pandera.readthedocs.io/) | Dataframe-level typed checks — public uni + not Baden-Württemberg ⇒ tuition = 0; `uni_assist_deadline ≤ application_deadline`; `min ≤ typical ≤ max`; any figure contradicting a `policy_constant` → **auto-overwrite + log**. |
| **4. Cross-source agreement** | your own SQL | Same fact from ≥2 independent sources → tier A. Disagreement → tier C + review, Tier-1 source wins provisionally. Track `agreement_count`. |
| **5. Outlier detection** | Pandera / scipy | Z-score or IQR per field per cohort. €4,200 semester contribution among peers at €280 = extraction bug. **Flag, don't drop.** |

**Framework note:** [Great Expectations](https://greatexpectations.io/) gives you the richest expectation library plus Data Docs (human-readable HTML validation reports — genuinely useful for a non-technical reviewer). [Soda Core](https://github.com/sodadata/soda-core) is YAML-first and better for ongoing freshness/volume monitoring. **Pandera is the right pick for you**: Python-native, fits directly around Pydantic models, minimal ceremony. Add Soda later for production freshness alerts if you want them.

### 5.1 The gold set — the highest-leverage thing in this document

Hand-verify **100–200 records** (programmes, with full requirement sets). Freeze them. Every prompt change, model change, or parser change runs against this set before deploy, reporting **field-level precision and recall**.

Without this you cannot answer "did upgrading the model help?" — and you will churn on prompt tweaks forever, guessing. Tools: plain pytest, or [promptfoo](https://github.com/promptfoo/promptfoo) for prompt regression testing.

### 5.2 Sampled LLM-as-judge

Take a **2–5% random sample** per extraction run. Hand a judge model `(source_text, extracted_json)` and ask it to find contradictions. Track pass rate per prompt version as a regression metric. Cheap, and it's how you find out a site redesign silently broke your extractor before your users do.

### 5.3 Human review queue

Anything at tier C, low confidence, or a Gate 3–5 flag. Build the simplest possible UI — [Streamlit](https://streamlit.io/) with source text on the left, extracted JSON editable on the right, approve/reject buttons. A person can clear 100+ records/hour with a good layout. [Label Studio](https://labelstud.io/) if you want proper annotation workflows and inter-annotator agreement.

**Budget for this.** Assume 10–15% of high-stakes extractions need human eyes. That is not a pipeline failure; it is the correct design for data that people make expensive decisions on.

---

## 6. Layer 6 — Store

### 6.1 The stack

| Layer | Tool | Why |
|---|---|---|
| Raw archive | **MinIO** ([min.io](https://min.io/)) or gzipped files | Immutable snapshots, partitioned `source/date/`. Never deleted. |
| Staging | **DuckDB** ([duckdb.org](https://duckdb.org/)) + Parquet | Extracted-but-unvalidated JSON. DuckDB queries Parquet in place, zero infrastructure, and is what Splink runs on anyway. |
| Core | **PostgreSQL 16+** | All entities from `01-DATA-MODEL.md`. JSONB for `requirements`, `curriculum_modules`, `component_minimums`. Add `pgvector` later. |
| Migrations | **Alembic** ([alembic.sqlalchemy.org](https://alembic.sqlalchemy.org/)) | Your schema *will* change. Version it from commit one. |
| Transforms | **dbt-core** ([getdbt.com](https://www.getdbt.com/product/dbt-core)) | staging → core models as versioned SQL, with built-in tests (`unique`, `not_null`, `accepted_values`, `relationships`). Optional but pays off fast. |
| Orchestration | **Prefect** ([prefect.io](https://www.prefect.io/opensource)) | Python-native, minimal ceremony, good retries/observability. [Dagster](https://dagster.io/) if you prefer asset-based thinking. **Don't reach for Airflow.** For the first month, cron + a Postgres queue table is genuinely fine. |
| Change monitoring | **changedetection.io** ([github](https://github.com/dgtlmoon/changedetection.io)) | Watch ~50 critical pages (deadline pages, fee pages, policy pages) for changes between scheduled crawls. Cheap early warning. |
| Secrets/config | **pydantic-settings** | Keep API keys and crawl configs out of code |

### 6.2 Write pattern — every fact carries its lineage

```sql
INSERT INTO requirement (
  programme_id, kind, subkind, operator, value_num, unit,
  is_mandatory, component_minimums,
  -- provenance, always
  snapshot_id, evidence_quote, evidence_offset,
  extracted_by_model, prompt_version, confidence,
  agreement_count, quality_tier,
  observed_at, valid_from, valid_to
) VALUES (...)
ON CONFLICT (programme_id, kind, subkind, applicant_class)
DO UPDATE SET ... WHERE EXCLUDED.quality_tier <= requirement.quality_tier;
-- ↑ never let a tier-C scrape overwrite a tier-A human-verified fact
```

Plus an append-only `fact_history` table (old value, new value, snapshot_id, changed_at) written by a trigger. When a user asks "why did this deadline change?", you can answer.

### 6.3 What "done" looks like for this document

You are ready to build the graph/vector layer when:

- [ ] Every institution has a stable ID and ROR/Wikidata cross-references; no duplicates (Splink clusters reviewed)
- [ ] Every stored fact has `snapshot_id` + `evidence_quote` + `quality_tier`
- [ ] All five validation gates run automatically in CI on every extraction batch
- [ ] The gold set exists, is frozen, and precision/recall is reported per deploy
- [ ] `next_refresh_due` drives a scheduled crawl; content hashing skips unchanged pages
- [ ] Raw snapshots are archived and the whole pipeline is re-runnable offline from them
- [ ] `policy_constant` overrides are wired and tested against deliberately stale scraped values

Only then chunk and embed. Building a vector index over unvalidated data means burning the embedding cost twice and, worse, shipping confident wrong answers in between.

---

## 7. Suggested build sequence

| Week | Work | Tools | Outcome |
|---|---|---|---|
| **1** | Institution spine + dedup | ROR dump, Hochschulkompass `hs_liste.txt`, Destatis API, **Splink** | ~400 clean institution records, cross-IDs, no duplicates |
| **2** | Fetch + archive infrastructure | Scrapy, httpx, MinIO, content hashing, `crawl_target` table | Re-runnable, polite, resumable crawler |
| **3** | Clean layer + PDF cascade | trafilatura, Crawl4AI, Docling, pymupdf4llm | Markdown corpus, 60–80% token reduction |
| **4** | Extraction v1 — structured pages | **Instructor** + Pydantic + Gemini Flash | Programmes, fees, deadlines as typed JSON |
| **5** | Extraction v2 — regulation PDFs | **LangExtract** + Docling | Typed `requirement` rows with source grounding — *the moat* |
| **6** | Gold set + all five gates | pytest, Pandera, promptfoo, Streamlit review UI | Measurable extraction quality; humans in the loop |
| **7** | Money + work layers | Scrapy, BA Jobsuche API, Numbeo, WG-Gesucht (Patchright if needed) | `cost_of_living`, `labour_market` populated |
| **8** | Career layer | Entgeltatlas community client, Destatis GENESIS, BERUFENET | `occupation_salary`, `shortage_status` |
| **9** | Refresh loop + monitoring | Prefect, changedetection.io, Soda Core | KB stays alive; deadline changes become a product feature |

---

## 8. Traps specific to this toolchain

| Trap | Why it bites here | Fix |
|---|---|---|
| Feeding raw HTML to the LLM | 5–10× token cost, worse accuracy | trafilatura/Crawl4AI first, always |
| Using an AI agent to "browse and find" data | Non-deterministic, unauditable, slow | Discover once with ScrapeGraphAI, then write a deterministic selector |
| No content hashing | Every refresh re-pays full extraction cost | Hash + skip; ~90% of pages are unchanged |
| Extracting from English pages | Legally non-binding, often stale | Extract from German; store both |
| One giant extraction schema | Accuracy collapses past ~10 fields | One schema per theme, multiple calls |
| No evidence quotes | Hallucinations are undetectable | LangExtract source grounding + Gate 2 |
| Trusting `robots.txt` alone | ToS-level TDM reservations also count (LG Hamburg) | Parse ToS too, store the verdict |
| Self-hosting LLMs too early | 10–20 eng-hours/month; break-even is ~$20k/mo API spend | Use Flash-class APIs until volume justifies otherwise |
| Skipping migrations | Schema changes weekly early on | Alembic from day one |
| Embedding before validating | Pays embedding cost twice, ships wrong answers meanwhile | Complete §6.3 checklist first |
| Marker's licence | Commercial-use restrictions above a revenue threshold | Read it, or default to Docling (MIT) |
| Firecrawl AGPL | Copyleft implications if embedded | Use the hosted free tier, or Crawl4AI (Apache 2.0) |
| Crawling too fast, then reaching for stealth tools | You caused the block | Slow to 1 req / 2–5s before adding Camoufox |

---

## 9. Licence summary (check before you build on any of these)

| Tool | Licence | Commercial use |
|---|---|---|
| Crawl4AI | Apache 2.0 | ✅ Unrestricted |
| Docling | MIT | ✅ Unrestricted |
| Scrapy | BSD-3 | ✅ Unrestricted |
| trafilatura | Apache 2.0 | ✅ Unrestricted |
| Instructor | MIT | ✅ Unrestricted |
| LangExtract | Apache 2.0 | ✅ Unrestricted |
| Splink | MIT | ✅ Unrestricted |
| Pandera | MIT | ✅ Unrestricted |
| Playwright | Apache 2.0 | ✅ Unrestricted |
| Patchright / Camoufox | Apache 2.0 / MPL | ✅ but check anti-circumvention exposure per target site |
| MinerU | AGPL-3.0 | ⚠️ Copyleft |
| Firecrawl | AGPL-3.0 | ⚠️ Copyleft — hosted tier avoids this |
| pymupdf4llm | AGPL-3.0 | ⚠️ Copyleft (commercial licence available) |
| Marker | modified — revenue-capped | ⚠️ Read carefully |
| ScrapeGraphAI | MIT (core) | ✅ Core is fine |

> Licence of the *tool* is separate from the rights over the *data* it fetches. Both must clear. See `02-DATA-SOURCES.md` §1 for the data side.

---

## 10. Sources consulted

AI scraping landscape: [ScrapeOps 2026 comparison](https://scrapeops.io/web-scraping-playbook/best-ai-web-scraping-tools/) · [Firecrawl: best open-source scraping libraries](https://www.firecrawl.dev/blog/best-open-source-web-scraping-libraries) · [Firecrawl: best open-source crawlers](https://www.firecrawl.dev/blog/best-open-source-web-crawler) · [Crawl4AI alternatives](https://scrapegraphai.com/blog/crawl4ai-alternatives)
Structured output: [Instructor docs](https://python.useinstructor.com/) · [BAML: every way to get structured output](https://boundaryml.com/blog/structured-output-from-llms) · [LangExtract deep dive (TDS)](https://towardsdatascience.com/extracting-structured-data-with-langextract-a-deep-dive-into-llm-orchestrated-workflows/) · [LangExtract production notes](https://genmind.ch/posts/LangExtract-Production-LLM-Powered-Information-Extraction/) · [8 structured output libraries ranked](https://techsy.io/en/blog/best-llm-structured-output-libraries)
PDF extraction: [Docling vs Marker vs MinerU vs olmOCR](https://www.soup.io/which-pdf-parser-should-you-use-comparing-docling-marker-netmind-parsepro-mineru-olmocr) · [Open-source PDF→Markdown 2026](https://themenonlab.blog/blog/best-open-source-pdf-to-markdown-tools-2026) · [Structured PDF-to-JSON guide](https://www.marktechpost.com/2026/07/04/structured-pdf-to-json-a-guide-to-open-source-extraction-models-in-2026/)
Stealth browsers: [Camoufox stealth overview](https://camoufox.com/stealth/) · [Playwright stealth 2026: Patchright vs Camoufox vs nodriver](https://scrapewise.ai/blogs/playwright-stealth-2026) · [Anti-detect benchmark](https://ianlpaterson.com/blog/anti-detect-browser-benchmark-patchright-nodriver-curl-cffi/)
Local vs API inference: [Local LLM inference tools July 2026](https://dev.to/sreeraj-sreenivasan/the-complete-guide-to-local-llm-inference-tools-in-july-2026-llamacpp-ollama-vllm-sglang-and-4mh1) · [Self-host vs API break-even](https://tokenmix.ai/blog/self-host-llm-vs-api) · [Self-hosted LLM costs 2026](https://www.sitepoint.com/self-hosted-llm-costs-2026/)
Entity resolution: [Splink](https://moj-analytical-services.github.io/splink/index.html) · [Open-source ER libraries compared](https://tilores.io/content/best-open-source-entity-resolution-and-record-linkage-libraries-splink-zingg-dedupe-and-when-to-move-beyond-them/)
Data quality: [GE vs dbt tests vs Soda Core](https://pipecode.ai/blogs/data-quality-frameworks-great-expectations-vs-dbt-tests-vs-soda-core) · [Great Expectations vs Soda 2026](https://aiml.qa/blog/great-expectations-vs-soda/)

*Tool landscape verified July 2026. This space moves fast — re-check the extraction and stealth sections every ~6 months.*
