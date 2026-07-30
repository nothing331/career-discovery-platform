# Germany Study-Abroad Knowledge Base — Data Sources

**Version:** 1.0 · **Last reviewed:** 2026-07-29
**Purpose:** For every field in `01-DATA-MODEL.md`, name the source, how to get it, what it costs, how legal it is, how often to refresh, and what it is (and is not) good for.

---

## 0. Source authority tiers

Use these tiers everywhere. A fact's tier determines whether it may drive an eligibility decision.

| Tier | Meaning | Examples | Usable for hard filters? |
|---|---|---|---|
| **1** | Legally authoritative — the body that sets the rule | University admission regulations (*Zulassungsordnung*), Auswärtiges Amt, anabin/ZAB, Destatis, Bundesland ministries, Minijob-Zentrale | ✅ Yes |
| **2** | Official aggregator — accurate, sometimes lagging | Hochschulkompass (HRK), DAAD, uni-assist, Studierendenwerke, EQAR/DEQAR | ✅ Yes (flag lag) |
| **3** | Commercial / market data — good signal, no authority | Numbeo, ImmoScout24, WG-Gesucht, Stellenwerk, StepStone, Glassdoor | ⚠️ Estimates only |
| **4** | Community / editorial | Reddit r/germany, Studycheck, blogs, YouTube, consultancy sites | ❌ Never; colour only |

**Golden rule:** if a Tier-3/4 source disagrees with Tier 1, Tier 1 wins and the conflict is logged. If two Tier-1 sources disagree (German page vs English page), the **German** page wins and the record is flagged for human review.

---

## 1. Legal position on collecting this data (read before writing a crawler)

This is the part most people skip and then rebuild everything.

1. **§ 44b UrhG (German implementation of EU DSM Art. 4)** permits text-and-data-mining reproductions of *lawfully accessible* works — including for commercial purposes — **unless the rightsholder has declared a machine-readable reservation**. The LG Hamburg (*Kneschke v. LAION*, 2024) indicated that a reservation written in natural language in the Terms of Use may still count as "machine-readable", since a TDM operator can be expected to use an LLM to read it. **Practical consequence: parse both `robots.txt` and the ToS/Impressum for opt-outs, and store the result in `source.tdm_reservation_detected`.**
2. **§ 87b UrhG / database right** protects substantial extractions from an investment-protected database. Hochschulkompass and DAAD are exactly this kind of database. Extracting *facts* (a deadline, a fee) is far safer than mirroring their *compilation*. **Store facts, re-verify against the university's own page, never republish their database as a whole.**
3. **Hochschulkompass explicitly restricts its downloads to personal use**; commercial use "requires the approval of the Foundation for the Promotion of the HRK". Use it for discovery and cross-checking, then obtain the fact from the university itself for anything you publish commercially.
4. **GDPR** — none of this data should include personal data. Do not scrape professor names, student reviews with identifiers, or job-ad contact persons into your KB.
5. **Practice, not just theory:** identify your bot in the User-Agent with a contact URL, obey `Crawl-delay`, cap at ~1 request per 2–5 s per host, cache aggressively via ETag/Last-Modified, and never re-fetch unchanged pages. This is also what keeps you un-blocked.
6. **Ask first where it's cheap.** DAAD, HRK, and most international offices respond to a polite email describing a student-facing product. A licence or a data dump is worth more than three months of scraper maintenance.

---

## 2. Master source table

### 2.1 Institutions & programmes (academic core)

| # | Source | Tier | Feeds (fields) | Access | Cost | Refresh | Notes |
|---|---|---|---|---|---|---|---|
| 1 | **Hochschulkompass** (HRK) — `hochschulkompass.de` | 2 | `institution.*`, `programme.*`, `admission_restriction`, `start_terms`, `teaching_language` | HTML search + `hs_liste.txt` (tab-separated list of all HEIs) on the Downloads page | Free | Quarterly (institutions), per-semester (programmes) | **The best starting spine.** Official HRK register, ~400 HEIs, ~23k programmes. Downloads are personal-use-only — use as discovery/seed, verify commercially-used facts elsewhere. No public API. |
| 2 | **DAAD International Programmes** — `www2.daad.de/deutschland/studienangebote/international-programmes/en/` | 2 | English-taught programmes, tuition, `requirements` prose, deadlines, contact | HTML; the search result page is backed by an internal JSON endpoint (inspect network tab) | Free | Monthly in season | Best coverage of **English-taught** degrees, which is your core market. Also has explicit "Costs / Funding" and "Requirements" blocks — much easier to extract than raw uni pages. |
| 3 | **University's own admission regulations** (`Zulassungsordnung` / `Prüfungsordnung`, usually PDF) | **1** | `requirement.ects_subject`, `gpa`, aptitude procedure, `nc_last_year_*` | PDF scrape + LLM extraction | Free | Per semester | **The only legally binding source.** Everything else summarises it. This is where the "24 ECTS in Mathematics" rules actually live. Highest extraction effort, highest value — this is your product's moat. |
| 4 | **uni-assist** — `uni-assist.de` | 2 | `institution.uses_uni_assist`, `uni_assist_deadline`, `vpd_required`, application fees, country-specific document lists | HTML | Free | Per semester | Also publishes **country-specific document requirements** — directly feeds `document_checklist`. Their deadline is typically ~6 weeks before the university's; this alone is a feature students will pay for. |
| 5 | **anabin / ZAB** — `anabin.kmk.org` | **1** | `hzb_recognition.*`, institution class (H+/H±/H−), degree equivalence | HTML (frame-based, awkward; stable query params) | Free | Quarterly | Decides whether a user's degree is recognised **at all**. Non-negotiable for an Indian/Nigerian/Pakistani user base. Hard to scrape, small dataset — consider a one-time careful extraction per country you serve. |
| 6 | **DEQAR / EQAR** — `deqar.eu` | 2 | `accreditation_*`, programme-level QA reports | **Public REST API** | Free | Yearly | Clean, machine-readable, gives you legitimacy signals ("is this private uni actually accredited?"). Syncs from ETER daily. |
| 7 | **Akkreditierungsrat** — `akkreditierungsrat.de` | **1** | German programme accreditation status | HTML/DB search | Free | Yearly | German-specific complement to DEQAR. |
| 8 | **ETER / OrgReg** | 2 | European HEI register, staff/student counts, finances, identifiers | Bulk download (CSV) | Free | Yearly | Best cross-country institutional metadata; the ID backbone DEQAR itself uses. |
| 9 | **ROR** — `ror.org` | 2 | `ror_id`, canonical names, aliases, geo, links to Wikidata/GRID | Full data dump (Zenodo) + API | Free, CC0 | Yearly | **Do this on day one.** Solves entity resolution ("TUM" vs "TU München") before it becomes a nightmare. |
| 10 | **Wikidata** | 3 | aliases, logos, founding year, coordinates, cross-IDs, multilingual names | SPARQL endpoint + dumps | Free, CC0 | Quarterly | Cheapest way to enrich institution records and get German/English name pairs. |
| 11 | **OpenAlex** | 3 | research output, fields of strength, `openalex_id` (94% carry ROR IDs) | REST API, no key needed | Free, CC0 | Yearly | Lets you say "this uni is strong in ML" with evidence instead of marketing copy. Good differentiator for programme ranking. |
| 12 | **Destatis GENESIS-Online** (Statistisches Bundesamt) | **1** | `student_count`, `intl_student_share`, graduates by subject, dropout proxies | **REST/JSON API + flat-file CSV**, free, no registration, Data Licence Germany 2.0 (attribution) | Free | Yearly | The only *authoritative* numbers on students and institutions. Also `restatis` R client if useful. Table families: 21311 (students), 21321 (examinations). |
| 13 | **Studienwahl.de / Hochschulstart (SfH)** | **1** | `bundesweiter NC` programmes, central allocation rules, NC cutoffs | HTML | Free | Per semester | Only relevant for nationally restricted subjects (medicine, dentistry, pharmacy, vet). Skip unless you serve those. |
| 14 | **StudyCheck / MeineUni** | 4 | student satisfaction, reported experiences | HTML | Free | Yearly | Tier 4 — display only, clearly labelled. Do **not** let it touch eligibility. |

### 2.2 Money — fees, cost of living, housing

| # | Source | Tier | Feeds | Access | Cost | Refresh | Notes |
|---|---|---|---|---|---|---|---|
| 15 | **University "Semesterbeitrag" pages** | **1** | `semester_contribution_eur` + breakdown, `long_study_fee` | HTML per uni | Free | Per semester | Small pages, highly structured, easy win. ~400 URLs total. |
| 16 | **Baden-Württemberg MWK** (`mwk.baden-wuerttemberg.de`) | **1** | non-EU tuition €1,500/sem, second-degree €650/sem | HTML | Free | Yearly | The one state that breaks "Germany is free". Model per-state, not per-country. |
| 17 | **Deutsches Studierendenwerk + local Studierendenwerke (57 of them)** | **1/2** | dorm rents, dorm places & waitlists, Mensa prices, semester contribution components | HTML per Studierendenwerk | Free | Per semester | Dorm availability is the single biggest lever on affordability and nobody models it. Also publishes the **Sozialerhebung** — the authoritative national survey of what students actually spend. |
| 18 | **DSW Sozialerhebung (22nd survey) / "Studieren in Deutschland"** | **1** | national baseline monthly spend by category | PDF + tables | Free | Every ~3 yrs | Use as the *sanity-check baseline* for all scraped cost data. If your scraped city cost is 40% below this, your extraction is wrong. |
| 19 | **WG-Gesucht** — `wg-gesucht.de` | 3 | real WG room rents per city/district, warm/kalt, availability counts | HTML listings | Free | Monthly | **The most accurate rent signal for students** — Numbeo measures the general market, WG-Gesucht measures the student market. Aggregate ≥100 listings/city, store median + p25/p75, never individual listings (GDPR + ToS). Scrape gently; they block aggressively. |
| 20 | **ImmoScout24 / Immowelt** | 3 | studio & 1-room rents | HTML / limited API | Free tier | Quarterly | Cross-check for WG-Gesucht; better for non-shared housing. |
| 21 | **Numbeo** — `numbeo.com` | 3 | groceries, transport, utilities, restaurants per city | HTML; paid API available | Free (scrape) / paid API | Quarterly | Crowd-sourced, city-level, wide coverage. Good for *relative* comparison (Munich vs Chemnitz), weak on absolutes. ToS restricts scraping — the paid API is cheap and removes the risk. |
| 22 | **Destatis Verbraucherpreisindex + Mietspiegel** | **1** | inflation adjustment, official rent indices per city | GENESIS API / municipal PDFs | Free | Yearly | Use to **age-adjust** older scraped costs instead of re-scraping everything. |
| 23 | **Rundfunkbeitrag** — `rundfunkbeitrag.de` | **1** | €18.36/month per household, exemption rules (BAföG only) | HTML | Free | On change | Constantly forgotten in student budgets. Cheap credibility win. |
| 24 | **TK / AOK / BARMER / DAK student rates** | **1** | `student_gkv_monthly_eur` by fund and age band | HTML | Free | Yearly (Jan) | 2026: ~€141.16 (TK, under 23) to ~€146.29 (23+, with Pflegeversicherung surcharge); rate ends at 30 → ~€270–300. Also drives the "turning 30 mid-degree" edge case. |
| 25 | **Expatrio / Fintiba / Coracle** | 3 | blocked-account fees, insurance bundles, current required amount | HTML | Free | Quarterly | Useful for *product* fields (what a student pays a provider), not for the legal amount — take that from the Auswärtiges Amt. |
| 26 | **VRR / NAH.SH / local transit + university AStA pages** | **1** | `deutschland_semesterticket_eur`, coverage area | HTML | Free | Per semester | €208.80/sem through SS2026; rising to ~€226.80 from WS2026/27 (60% of the €63 D-Ticket). Store per-university, it varies. |

### 2.3 Work *during* study (part-time earning)

| # | Source | Tier | Feeds | Access | Cost | Refresh | Notes |
|---|---|---|---|---|---|---|---|
| 27 | **Bundesagentur für Arbeit — Jobsuche API** (`jobsuche.api.bund.dev`, bundesAPI project) | **1** | job postings by city/keyword, employer, working-time type | **REST API**, `X-API-Key` client ID published by the community project | Free | Weekly | Germany's largest job database, programmatically accessible. Filter for `Werkstudent`/`Aushilfe` → derive `labour_market.postings_count_30d` per city. Best structured labour source available. |
| 28 | **Stellenwerk** — `stellenwerk.de` | 2 | university-affiliated student jobs, hourly wages, language requirement | HTML per city | Free | Weekly | The *student-specific* job board network, run by Studierendenwerke. Ideal for `hourly_wage_median` and `english_ok_share_pct`. |
| 29 | **StepStone / Indeed DE / LinkedIn** | 3 | Werkstudent postings, salary ranges, English-language share | HTML (ToS-restricted; LinkedIn = do not scrape) | Free/paid | Monthly | Use BA API + Stellenwerk first. Only add these if coverage gaps remain. LinkedIn scraping is a legal and operational dead end — skip it. |
| 30 | **University HiWi / SHK pay scales** | **1** | academic assistant hourly rates (state-regulated) | HTML/PDF per uni or state | Free | Yearly | Reliable, state-set numbers — a good high-confidence anchor for wage data. |
| 31 | **Make it in Germany** (BMWK) | **1** | work rules for students, post-study options, shortage occupations | HTML | Free | Quarterly | Government portal, English, authoritative, easy to extract. |
| 32 | **Minijob-Zentrale** | **1** | `minijob_monthly_ceiling_eur` (€603 in 2026), rules | HTML | Free | Yearly (Jan) | Direct source for a `policy_constant`. |
| 33 | **Mindestlohnkommission / BMAS** | **1** | `minimum_wage_hourly_eur` (€13.90 from 2026-01-01) | HTML | Free | Yearly | Same. |

### 2.4 Visa, legal, immigration

| # | Source | Tier | Feeds | Access | Cost | Refresh | Notes |
|---|---|---|---|---|---|---|---|
| 34 | **Auswärtiges Amt** + individual German missions (e.g. India: `india.diplo.de`) | **1** | `visa_pathway.*`, financial-proof amount (**€11,904 / €992 per month**), fees, appointment waits, document lists | HTML per mission | Free | Monthly | Mission pages differ by country — scrape per nationality you serve, not once globally. |
| 35 | **BAMF + AufenthG / § 16b, § 20** (`gesetze-im-internet.de`) | **1** | work-day allowance (**140 full / 280 half days**, raised from 120/240 in March 2026), residence permit rules | HTML | Free | On change | `gesetze-im-internet.de` is stable, clean HTML — good for verbatim legal citation in answers. |
| 36 | **BMI / BAföG-Bedarfssatz** | **1** | source of the blocked-account amount (it tracks the BAföG maximum) | HTML/PDF | Free | Yearly | Lets you *predict* next year's blocked amount instead of discovering it late. |
| 37 | **APS offices** (India: `aps-india.de`, China, Vietnam) | **1** | APS requirement, fee, processing time, document list | HTML | Free | Quarterly | Mandatory step for your likely largest user segments; long lead times make it a planning feature. |
| 38 | **EU Blue Card salary thresholds (BMI/BA)** | **1** | post-study employment thresholds, shortage occupations | HTML | Free | Yearly (Jan) | Powers "what happens after I graduate" — the question that actually drives the purchase decision. |

### 2.5 Funding

| # | Source | Tier | Feeds | Access | Cost | Refresh | Notes |
|---|---|---|---|---|---|---|---|
| 39 | **DAAD Scholarship Database** | 2 | `scholarship.*` for international students | HTML search | Free | Quarterly | Largest single scholarship set; filterable by country and level. |
| 40 | **Deutschlandstipendium** | **1** | €300/month programme, per-university availability | HTML + per-uni pages | Free | Yearly | Per-institution availability is a real differentiator. |
| 41 | **Stiftungen** (Konrad-Adenauer, Heinrich-Böll, Friedrich-Ebert, Studienstiftung, Hans-Böckler…) | **1** | political/ideological foundation scholarships | HTML | Free | Yearly | ~13 major Begabtenförderungswerke; small dataset, high value, worth manual curation. |
| 42 | **Erasmus+ / EU funding portal** | 2 | mobility grants, joint-degree scholarships | HTML/API | Free | Yearly | |
| 43 | **mystipendium.de / European Funding Guide** | 3 | long tail of small scholarships | HTML | Free | Yearly | Aggregators — useful for recall, verify before display. |

### 2.6 Post-graduation salaries & career outcomes

This is the ROI layer. Note the tier discipline: only the first three are authoritative; everything else is self-reported and self-selected (people with good salaries report them more often), so **medians from job boards run optimistic by roughly 10–20%**.

| # | Source | Tier | Feeds | Access | Cost | Refresh | Notes |
|---|---|---|---|---|---|---|---|
| 44 | **BA Entgeltatlas** — `entgeltatlas.arbeitsagentur.de` | **1** | `occupation_salary.*` — median gross by occupation, region, age, qualification | No official API; OAuth2 client-credentials endpoint reverse-engineered by the community ([`AndreasFischer1985/entgeltatlas-api`](https://github.com/AndreasFischer1985/entgeltatlas-api)) | Free | Yearly | **The single best salary source in Germany.** Built from actual social-insurance records of every full-time employee — not a survey, not self-reported. 4,000+ job titles, national + Bundesland + district granularity. Keyed by **KldB code** — which is why `occupation.kldb_2010_code` is in the schema. |
| 45 | **Destatis Verdiensterhebung** (GENESIS tables 62361 / 62321) | **1** | gross earnings by occupation, qualification, sex, region; **percentile distributions** | GENESIS REST/JSON API, free, no registration | Free | Yearly | Gives you p25/median/p75 rather than just a mean. Use together with #44: Entgeltatlas for occupational granularity, Destatis for distribution shape. |
| 46 | **BA Fachkräfteengpassanalyse** (`statistik.arbeitsagentur.de`) | **1** | `shortage_status.*` — the official shortage-occupation list (163+ occupations), vacancy durations | PDF + Excel, twice yearly | Free | Half-yearly | Directly determines the **lower Blue Card threshold (€45,934.20 vs €50,700 in 2026)**. Also the honest answer to "will I actually find a job in this field". |
| 47 | **BA Jobsuche API** (same as #27) | **1** | graduate-level vacancy counts by occupation × city, English-language share | REST API | Free | Weekly | Reuse the student-job crawler with different filters. Vacancy *counts over time* are a better demand signal than any salary survey. |
| 48 | **DZHW Absolventenpanel / Graduate Panel** — `fdz.dzhw.eu` | **1** | `graduate_outcome.*` — employment rate, time-to-job, salary by field of study, further study rate | Application required via `metadata.fdz.dzhw.eu` (research data centre) | Free, but **application + approval needed** | Every ~4 yrs | The only *rigorous* German graduate-outcome data. Cohort-based, field-level (not programme-level). Access is a formal process — start it early, it's slow. Worth it: nobody else in your market will have this. |
| 49 | **StepStone Gehaltsreport / Gehaltsplaner** | 3 | starting salaries by field, city, degree level | HTML/PDF annual report | Free | Yearly | Large sample, well-structured annual PDF, widely cited. Self-reported → optimistic. Good for *relative* comparison across fields. |
| 50 | **Gehalt.de / kununu / Glassdoor DE** | 3 | salary by job title + employer, employer reviews | HTML (ToS-restricted) | Free/paid | Quarterly | Use for employer-level colour and role titles the official KldB codes are too coarse for. Never as a primary number. |
| 51 | **Levels.fyi / Blind** | 3 | tech-specific compensation, Berlin/Munich | HTML/API | Free | Quarterly | Only relevant if you serve CS/data students — but for that segment it's more accurate than any German source, because official data can't see equity. |
| 52 | **Absolventa / Berufsstart / Staufenbiel Berufsstart-Gehälter** | 3 | entry-level graduate salary benchmarks by degree | HTML | Free | Yearly | Germany-specific graduate-entry focus; useful cross-check on #49. |
| 53 | **BA BERUFENET** — `berufenet.arbeitsagentur.de` | **1** | `occupation.*` — canonical occupation descriptions, KldB codes, entry requirements, licence gating | HTML, structured | Free | Yearly | Your `occupation` table's spine. Also flags the **licence-gated professions** (Approbation, Staatsexamen) where a foreign degree does not convert into practice rights. |
| 54 | **Make it in Germany — Chancenkarte / Blue Card pages** (BMWK) | **1** | post-study visa routes, points criteria, salary thresholds | HTML, English | Free | Quarterly | Already source #31; reuse for the career layer. |
| 55 | **IAB / OECD Education at a Glance / Eurostat** | 2 | employment rate by education level, returns to education, cross-country comparison | Bulk CSV / API | Free | Yearly | Use for benchmarking ("is Germany better than Canada for this field") — a question your users will ask and competitors won't answer. |
| 56 | **Destatis migration + BAMF statistics** | **1** | `stay_in_germany_rate` — retention of international graduates | GENESIS / BAMF reports | Free | Yearly | Hard to get at programme level, available nationally (~45–55% of international graduates remain after 5 years). **Use it to calibrate ROI projections honestly** rather than assuming everyone stays. |
| 57 | **University career-service reports / Absolventenbefragungen** | 2 | programme-level placement rates, top employers | HTML/PDF per uni | Free | Yearly | Patchy — maybe 30% of universities publish these. Where they exist, they're the only true programme-level outcome data. Selection bias: unis publish good numbers. |

### 2.7 Community & qualitative (Tier 4 — colour only)

| # | Source | Feeds | Notes |
|---|---|---|---|
| 58 | Reddit `r/germany`, `r/StudyInGermany`, `r/cscareerquestionsEU` | real rejection stories, actual NC experiences, dorm waitlist reality, real reported starting salaries, job-hunt difficulty for non-German speakers | Official **Reddit API** (free tier, rate-limited, registration required). Genuinely valuable for "what actually happens" but must be tagged Tier 4 and never used for filtering. |
| 59 | YouTube transcripts, student blogs, Discord/Telegram groups | first-hand cost reports, visa interview questions, part-time job hunting reality | Use sparingly; high noise, high staleness. Good for building a FAQ corpus, bad for facts. |
| 60 | **Your own users** | reported outcomes: applied → admitted/rejected with profile; **and later: graduated → employed/salary** | **This becomes your most valuable dataset by year two.** Real admit/reject pairs let you calibrate admission probability empirically instead of guessing from NC cutoffs — and outcome pairs let you quote *your own* placement data, which no competitor can copy. Design the consent + schema for it now, not later. |

---

## 3. Ingestion architecture

```
                 ┌──────────────┐
 seed URLs ─────▶│  Discovery   │ Hochschulkompass hs_liste.txt + ROR + Destatis
                 │  (spine)     │ → canonical institution list w/ external IDs
                 └──────┬───────┘
                        ▼
                 ┌──────────────┐  robots.txt + ToS TDM check, per-host rate limit
                 │   Fetcher    │  Scrapy (volume) / Playwright (JS pages) /
                 │              │  Crawl4AI or Firecrawl (page → clean markdown)
                 └──────┬───────┘
                        ▼  raw HTML + markdown → object storage, content_hash
                 ┌──────────────┐
                 │  Router      │ hash unchanged? → skip. changed? → extract
                 └──────┬───────┘
                        ▼
                 ┌──────────────┐  cheap model (Gemini Flash / GPT-mini / local Qwen)
                 │  Extractor   │  + Instructor/Pydantic structured output
                 │              │  + verbatim evidence_quote required per field
                 └──────┬───────┘
                        ▼
                 ┌──────────────┐  schema → business rules → cross-source →
                 │  Validator   │  policy-constant override → outlier detection
                 └──────┬───────┘
                        ▼
              pass ──▶ Postgres (tier A/B)     fail ──▶ human review queue (tier C)
                        │
                        └──▶ chunk + embed narrative text → pgvector
```

**Tooling picks (all free / near-free):**
- **Scrapy** — high-volume static HTML (uni fee pages, Stellenwerk listings). Built-in politeness, retries, dedup.
- **Playwright** — JS-rendered pages (DAAD search, WG-Gesucht). Slow; use only where needed.
- **Crawl4AI** (open source, self-hosted) or **Firecrawl** (hosted, free tier) — page → clean markdown, which halves your LLM token cost vs. raw HTML.
- **trafilatura** — boilerplate removal, very good on German pages, no LLM needed.
- **pdfplumber / Docling / MinerU** — for Zulassungsordnung PDFs. Docling handles tables best.
- **Instructor + Pydantic** — force LLM output into your schema, with automatic retry on validation failure.
- **Great Expectations** or **Pandera** — dataset-level assertions (see §4).
- **Prefect** or plain **cron + Postgres queue** — scheduling from `next_refresh_due`. Don't reach for Airflow.
- **httpx + tenacity** — polite retry/backoff.

**Cost estimate:** ~25k programme pages × ~4k tokens input on Gemini Flash-class pricing lands in the **$10–40 range** for a full extraction pass. Extraction is not your cost problem; *maintenance* is.

---

## 4. Validating scraped data before it is stored (5 gates)

Every record passes all five, in order. Failure at any gate routes to the review queue with the failing gate recorded.

**Gate 1 — Schema (Pydantic).** Types, enums, ranges. `tuition_per_semester_eur` must be `float ≥ 0 ≤ 5000`. IELTS `∈ [0,9]` in 0.5 steps. Dates parse. German grades `∈ [1.0, 4.0]`. Rejects ~15% of first-pass LLM output for free.

**Gate 2 — Evidence grounding.** The extractor must return a verbatim `evidence_quote`. Assert that the quote **actually appears in the source snapshot** (normalised whitespace). If it doesn't, the model hallucinated — discard, don't review. This single check kills the majority of fabrications and costs nothing.

**Gate 3 — Business rules (deterministic code, not LLM).**
- Public university + not Baden-Württemberg + non-EU ⇒ tuition should be 0 → else flag.
- Semester contribution outside €80–€450 → flag.
- `uni_assist_deadline ≤ application_deadline` → else flag.
- Application deadline within 18 months of `observed_at` → else stale.
- Requirement mentions IELTS but `teaching_language = 'de'` → flag.
- Any financial figure contradicting a current `policy_constant` → **auto-overwrite + log**.
- Range fields: `min ≤ typical ≤ max`.

**Gate 4 — Cross-source agreement.** For high-stakes fields (deadline, tuition, language minimum), extract from ≥2 independent sources (e.g. DAAD + the university page). Agreement → tier A. Disagreement → tier C + review, **with the Tier-1 source winning provisionally**. Track `agreement_count` per fact.

**Gate 5 — Statistical outlier detection.** Per field, per cohort: z-score / IQR against peers. A €4,200 semester contribution among peers averaging €280 is an extraction bug (probably an annual figure, or a private uni misclassified). Flag, don't drop — outliers are sometimes real and always informative.

**Then: LLM-as-judge, sampled not exhaustive.** Take a 2–5% random sample per extraction run, hand the judge model `(source text, extracted JSON)` and ask it to find contradictions. Track the pass rate per prompt version as a regression metric. Cheap, and it tells you when a site redesign silently broke your extractor.

**And: a frozen gold set.** 100–200 hand-verified programme records. Every prompt change, model change, or parser change runs against it before deploy. Report field-level precision/recall. **Without this you cannot tell whether "upgrading the model" helped or hurt.** This is the single highest-leverage thing in the whole pipeline.

### Extraction prompt rules that matter
- One schema per prompt; don't extract 40 fields in one call — accuracy collapses. Batch by theme (identity / requirements / money / dates).
- Demand `null` explicitly: *"If the text does not state this, return null. Do not infer, do not use general knowledge about German universities."* Model priors are the #1 source of plausible-but-wrong facts here.
- Require `evidence_quote` for every non-null field (feeds Gate 2).
- Ask for `confidence` 0–1 and route `< 0.7` to review.
- Feed **German** text to the model and ask for German-preserving output plus an English translation — don't extract from the English summary page when a German original exists.
- Pin the model version. An unannounced model update silently changes your dataset.

---

## 5. Build order (what to do in which week)

| Phase | Work | Output |
|---|---|---|
| **1 — Spine** | ROR dump + Hochschulkompass `hs_liste.txt` + Destatis → canonical institution table with external IDs | ~400 institutions, entity resolution solved |
| **2 — Constants** | Hand-enter `policy_constant` from Tier-1 sources; write the override rule | Legal/financial layer that never goes stale |
| **3 — Programmes (narrow)** | DAAD International Programmes, English-taught Master's, one field | ~300 programmes, full pipeline exercised end-to-end |
| **4 — Requirements (deep)** | Zulassungsordnung PDFs for those 25–50 institutions | Typed `requirement` rows — the actual moat |
| **5 — Gold set + gates** | Hand-verify 150 records, wire all 5 validation gates, freeze the gold set | Measurable extraction quality |
| **6 — Money** | Semesterbeitrag pages + Studierendenwerke + WG-Gesucht + Numbeo + insurance | `financial_viability` becomes computable |
| **7 — Work (during study)** | BA Jobsuche API + Stellenwerk, classify English-friendliness, HiWi pay scales | Part-time realism, not fantasy |
| **7b — Careers (after study)** | BERUFENET → `occupation` table with KldB codes; Entgeltatlas + Destatis Verdiensterhebung → `occupation_salary`; Engpassanalyse → `shortage_status`; map ISCED-F → KldB so every programme reaches a salary | ROI + Blue Card eligibility become computable. **Start the DZHW data application here — approval takes months.** |
| **8 — Visa & docs** | Mission pages per target nationality + anabin + APS | `document_checklist` generation |
| **9 — Refresh loop** | `next_refresh_due` scheduler, content-hash diffing, change alerts | KB stays alive; deadline changes become a *feature* (notifications) |
| **10 — Feedback** | Capture user outcomes (applied → admitted/rejected) | Empirical admission probability; compounding data moat |

---

## 6. Honest assessment of the hard parts

| Risk | Reality | Mitigation |
|---|---|---|
| **Requirements live in PDFs, in German, in legal prose** | This is 80% of the work and where every competitor gives up | Do it for 25 institutions properly rather than 400 badly. Depth beats breadth here. |
| **Maintenance, not acquisition, is the cost** | Building it once is a month. Keeping 25k programmes fresh is forever | Content-hash diffing + `next_refresh_due` + change alerts. Only re-extract what changed. |
| **Hochschulkompass/DAAD are database-right protected** | Mirroring them commercially is a real legal exposure | Use as discovery; source published facts from the university's own page; email them for a licence |
| **WG-Gesucht / Numbeo will block you** | Aggressive anti-bot; ToS restrict scraping | Low rate, aggregate-only storage, cache long, consider Numbeo's paid API — it's cheap relative to the risk |
| **"English-taught" is a soft lie** | Programmes drift to German; DAAD lists them anyway | Store `german_share_pct`; extract from curriculum, not the marketing header |
| **LLM confidently invents German requirements** | It "knows" typical German admission rules and will fill gaps with them | Gate 2 (evidence grounding) + explicit null instruction. Non-optional. |
| **Deadlines change mid-season** | Extensions are announced on the university page only | Weekly refresh for volatile fields during Nov–Jan and Apr–Jul peaks |
| **Legal figures change every January** | Minimum wage, minijob ceiling, insurance rates, blocked amount, **Blue Card thresholds** all reset | Annual January audit ritual against Tier-1 sources — put it in the calendar |
| **Programme → occupation mapping is fuzzy** | An M.Sc. in "Data Engineering" maps to 5+ KldB codes with different salaries | Store a weighted many-to-many `programme_field → occupation` map, show a salary *range* across the plausible set, never a single number |
| **Salary data is self-selected and optimistic** | StepStone/Glassdoor medians run 10–20% above official records | Anchor on Entgeltatlas (social-insurance records, not a survey); use job boards only for relative shape |
| **Gross ≠ net, and the gap is huge in Germany** | €50,700 gross ≈ €2,900–3,100/month net | Always compute and display net; store the tax assumptions used |
| **Not everyone stays** | International graduate retention is ~45–55%, not 100% | Multiply ROI projections by `stay_probability` and say so on screen |
| **Entgeltatlas has no official API** | Community client could break; underlying data lags ~2 years | Cache aggressively, inflation-adjust via Destatis index, keep a manual-download fallback |
| **Licence-gated fields** | Medicine, law, teaching, psychotherapy: a foreign degree often doesn't grant practice rights | Flag via BERUFENET `requires_licence` and warn loudly before the user spends €12k |

---

## 7. Sources consulted for this document

Blocked account 2026: [Expatrio](https://www.expatrio.com/about-germany/blocked-amount-2025) · [MyGermanUniversity](https://www.mygermanuniversity.com/articles/Germany-Blocked-Account-Amount) · [Study.eu](https://www.study.eu/article/germany-blocked-bank-accounts-for-students-guide)
Minijob & minimum wage 2026: [PayStat](https://paystat.de/en/blog/minijob-2026-regeln-grenze-steuern/) · [IamExpat](https://www.iamexpat.de/career/employment-news/what-changing-minijobs-germany-2026) · [Payleute](https://payleute.com/germany-minimum-wage-2026-payroll-impact-mini-job-limits/)
140-day work rule: [VisaHQ](https://www.visahq.com/news/2026-03-08/de/germany-eases-work-hour-cap-for-international-students-to-140-full-days/) · [MS in Germany](https://msingermany.com/blog/student-work-rules-germany-140-days-2026) · [ApplyBoard](https://assist.applyboard.com/hc/en-us/articles/26395366417933-Working-While-Studying-in-Germany-2026-Rules-for-International-Students)
Health insurance 2026: [student-insurance.com GKV comparison](https://www.student-insurance.com/blog/gkv-comparison-2026-tk-aok-barmer-dak/) · [GradRight](https://gradright.com/health-insurance-cost-in-germany-for-international-students-complete-guide/)
Semester ticket: [Studentenwerk Leipzig](https://www.studentenwerk-leipzig.de/en/news/semester-fee-increases-deutschland-semesterticket-and-mobility-fund-become-more-expensive/) · [VRR](https://www.vrr.de/en/tickets-fares/germany-semester-ticket/)
Hochschulkompass downloads & terms: [Downloads page](https://www.hochschulkompass.de/en/higher-education-institutions/downloads.html)
Destatis open data & API: [Open Data](https://www.destatis.de/EN/Service/OpenData/opendata-einleitung.html) · [GENESIS API](https://www.destatis.de/EN/Service/OpenData/api-webservice.html) · [destatis.api.bund.dev](https://destatis.api.bund.dev/)
BA Jobsuche API: [bundesAPI/jobsuche-api](https://github.com/bundesAPI/jobsuche-api) · [jobsuche.api.bund.dev](https://jobsuche.api.bund.dev/)
Identifiers & registries: [ROR](https://ror.org/tags/openalex/) · [OpenAlex institutions](https://docs.openalex.org/api-entities/institutions/institution-object) · [DEQAR data model](https://docs.deqar.eu/stable/architecture_data_model/)
TDM / scraping law: [Morrison Foerster on LG Hamburg](https://www.mofo.com/resources/insights/241004-to-scrape-or-not-to-scrape-first-court-decision) · [Harte-Bavendamm](https://www.harte-bavendamm.de/en/ip-blog/landmark-decision-by-the-hamburg-regional-court-on-the-copyright-admissibility-of-data-scraping-for-training-ai-models) · [§ 44b UrhG text](https://gesetze.legal/bund/urhg/44b)
DAAD: [International Programmes](https://www2.daad.de/deutschland/studienangebote/international-programmes/en/) · [Admission database](https://www.daad.de/en/studying-in-germany/requirements/admission-database/)
Salaries & careers: [BA Entgeltatlas](https://entgeltatlas.arbeitsagentur.de/) · [community Entgeltatlas API](https://github.com/AndreasFischer1985/entgeltatlas-api) · [BA Entgelt statistics](https://statistik.arbeitsagentur.de/DE/Navigation/Statistiken/Themen-im-Fokus/Entgelt/Entgelt-Nav.html) · [DZHW Graduate Panel](https://www.dzhw.eu/en/forschung/projekt?pr_id=467) · [FDZ-DZHW data access](https://www.fdz.dzhw.eu/en/service/glossar/graduate-panel)
EU Blue Card 2026 thresholds: [Tafapolsky & Smith](https://tandslaw.com/germany-updated-eu-blue-card-salary-thresholds-effective-1-january-2026/) · [VisaHQ](https://www.visahq.com/news/2026-01-02/de/germany-raises-eu-blue-card-salary-thresholds-as-2026-rules-take-effect/) · [Jobbatical shortage occupations](https://www.jobbatical.com/blog/germany-shortage-occupations-bottleneck-professions-eu-blue-card)

*Figures verified July 2026. Re-audit every January.*
