# Germany Study-Abroad Knowledge Base — What Data To Store

**Version:** 1.0 · **Last reviewed:** 2026-07-29
**Purpose:** Define every entity, field, and piece of metadata the knowledge base must hold so it can (a) answer free-form student questions, (b) hard-filter eligibility, and (c) score profile↔programme relevance.

---

## 0. Design principles (read this before the schema)

1. **Separate FACTS from TEXT.** Two stores, one ID space.
   - *Structured store* (Postgres): everything a `WHERE` clause or a comparison operator touches — fees, deadlines, GPA cutoffs, IELTS minimums, rent. Never let an LLM decide eligibility.
   - *Vector store* (pgvector / Qdrant): prose chunks — course descriptions, "who should apply", module lists, city vibe. Used only for retrieval and explanation.
   - Every vector chunk carries the structured entity's ID in metadata so you can filter-then-search, not search-then-hope.

2. **Every fact is a *claim*, not a truth.** Store `value + source_url + scraped_at + confidence + extraction_method`. A knowledge base without provenance cannot be debugged, cannot be legally defended, and cannot be refreshed selectively.

3. **Model the four axes separately.** Academic · Financial · Legal/Visa · Career. A programme is a good match only if it clears all four. Most products only build the first and are useless.

4. **National constants are code, not scraped data.** Blocked-account amount, minimum wage, minijob ceiling, work-day allowance — these change by law once a year and scraped blog posts are almost always stale. Keep them in a versioned `policy_constants` table with `valid_from`/`valid_to` and *overwrite* any scraped value that contradicts the current constant.

5. **Store ranges, not point estimates, for anything financial.** "Rent €350–450" must become `min`, `max`, `typical`, `basis` (per-room / per-flat / warm / kalt). Collapsing it to one number is where every budgeting tool goes wrong.

6. **Bitemporal.** Keep `valid_from`/`valid_to` (when the fact was true in the world) *and* `observed_at` (when you saw it). Deadlines and fees are seasonal; you need to answer "what was the WS26/27 deadline" after it has passed.

7. **Language.** Store German original **and** English. Requirements are legally binding in German; the English page is often an outdated summary. Field pattern: `text_de`, `text_en`, `authoritative_lang`.

---

## 1. Entity map

```
Institution ──< Faculty ──< Programme ──< Intake (admission cycle)
     │                          │             └──< Requirement (typed, atomic)
     │                          └──< Fee
     ├──< Campus ──> City ──< CostOfLiving ──< PriceObservation
     │                   ├──< HousingMarket
     │                   ├──< LabourMarket (part-time, student)
     │                   └──< GraduateLabourMarket (post-degree, by occupation)
     ├──< Accreditation
     ├──< GraduateOutcome (per programme: employment rate, salary, time-to-job)
     └──< Scholarship (also nationally scoped)

Occupation (KldB/ISCO) ──< OccupationSalary (by region × experience × qualification)
                       └──< ShortageStatus (Engpassanalyse → Blue Card threshold)

PolicyConstant (federal / state, time-versioned)
GradeConversionRule (country → German scale)
CountryQualification (anabin recognition status)
DocumentChecklist (per nationality × programme type)
Source / Snapshot / ExtractionRun  ← provenance backbone
UserProfile ──< MatchResult
```

---

## 2. Core academic entities

### 2.1 `institution`
| Field | Type | Notes |
|---|---|---|
| `id` | uuid | internal PK |
| `name_de`, `name_en` | text | official names |
| `aliases[]` | text[] | "TUM", "TU München", "Technical University of Munich" — critical for entity resolution |
| `ror_id`, `wikidata_qid`, `eter_id`, `deqar_id`, `hochschulkompass_id`, `openalex_id` | text | **external IDs are the single most valuable thing you can store** — they let you join free datasets later without re-scraping |
| `type` | enum | `universität` / `fachhochschule (HAW)` / `kunst_musik` / `pädagogisch` / `theologisch` / `verwaltung` |
| `carrier` | enum | `staatlich` / `kirchlich` / `privat` — drives whether tuition exists |
| `state` (Bundesland) | enum | 16 values; **tuition law is state-level, not federal** |
| `founded_year`, `student_count`, `intl_student_share` | int/num | from Destatis |
| `website`, `intl_office_url`, `admissions_email` | text | |
| `has_studienkolleg` | bool | matters for students without a recognised HZB |
| `uses_uni_assist` | enum | `full` / `vpd_only` / `no` — changes the entire application path and cost |
| `application_portal_url` | text | |
| `is_accredited`, `accreditation_body`, `accreditation_valid_to` | | via DEQAR/Akkreditierungsrat |

### 2.2 `programme`
| Field | Type | Notes |
|---|---|---|
| `id`, `institution_id` | | |
| `title_de`, `title_en` | text | |
| `degree` | enum | `B.Sc.` `B.A.` `B.Eng.` `M.Sc.` `M.A.` `M.Eng.` `M.B.A.` `Staatsexamen` `Diplom` `PhD` |
| `level` | enum | bachelor / master / doctorate / preparatory / language |
| `field_broad`, `field_narrow` | text | map to **ISCED-F 2013 codes** — do not invent your own taxonomy |
| `teaching_language` | enum | `en` / `de` / `mixed` |
| `german_share_pct` | int | "English-taught" programmes that turn German in semester 3 are a real trap |
| `duration_semesters`, `ects_total` | int | |
| `start_terms[]` | enum[] | `winter` / `summer` |
| `mode` | enum | full-time / part-time / dual / distance / berufsbegleitend |
| `admission_restriction` | enum | `zulassungsfrei` (open) / `örtlicher NC` / `bundesweiter NC` / `eignungsverfahren` (aptitude assessment) / `portfolio` |
| `is_consecutive` | bool | consecutive vs. weiterbildend — the latter usually charges real tuition and requires work experience |
| `requires_work_experience_months` | int | |
| `internship_semester` | bool + int | affects work-day accounting and total cost |
| `thesis_ects` | int | |
| `description_de/en` | text | → chunked into vector store |
| `curriculum_modules[]` | jsonb | `{module_name, ects, semester, mandatory}` — **this is the gold for syllabus-overlap scoring** |
| `career_outcomes_text` | text | |
| `double_degree_partners[]` | | |

### 2.3 `intake` (one row per programme × term × applicant class)
Deadlines differ for EU vs non-EU vs "with German HZB". Modelling this as a flat field on `programme` is the most common schema mistake.

| Field | Notes |
|---|---|
| `programme_id`, `term` | e.g. `WS2027/28` |
| `applicant_class` | `eu_eea` / `non_eu` / `german_hzb` / `all` |
| `application_opens`, `application_deadline` | date |
| `uni_assist_deadline` | date — usually **6 weeks earlier** than the university deadline; students miss this constantly |
| `vpd_required` | bool |
| `decision_expected` | date |
| `seats_total`, `applicants_last_year`, `admitted_last_year` | int — lets you compute a real acceptance rate |
| `nc_last_year_grade` | numeric — the actual NC cutoff from the previous cycle (German scale) |
| `nc_last_year_wartesemester` | int |
| `is_open` | bool (derived) |

### 2.4 `requirement` — **typed and atomic, one row per condition**
Do **not** store requirements as a blob. Every hard filter you will ever run lives here.

```jsonc
{
  "id": "...",
  "programme_id": "...",
  "applicant_class": "non_eu",
  "kind": "language_test | prior_degree | gpa | ects_subject | test_score |
           work_experience | portfolio | interview | motivation_letter |
           cv | recommendation | aps | visa | other",
  "subkind": "IELTS",              // TOEFL, DSH, TestDaF, GRE, GMAT, telc, Goethe
  "operator": ">=",                // >=, <=, ==, in, exists
  "value_num": 6.5,
  "value_text": null,
  "unit": "band",
  "component_minimums": {"writing": 6.0, "speaking": 5.5},  // sub-scores are separate rejections
  "is_mandatory": true,            // vs. "recommended" / "may improve chances"
  "waiver_conditions": "waived if prior degree taught fully in English",
  "evidence_quote": "Applicants must provide IELTS Academic with an overall band of 6.5...",
  "source_url": "...",
  "confidence": 0.93,
  "extracted_by": "gemini-flash|regex|human"
}
```

Requirement kinds you must cover for Germany specifically:
- **`ects_subject`** — "at least 24 ECTS in Mathematics, 18 in Programming". Store as `{subject, min_ects}` list. This is the single most decisive Master's filter in Germany and almost no aggregator has it.
- **`gpa`** — always store `value_num` **on the German 1.0–4.0 scale** plus `original_scale` and the conversion rule ID used.
- **`aps`** — mandatory for India/China/Vietnam; store as a requirement so it appears in the checklist automatically.
- **`prior_degree`** — required field of study, minimum ECTS (180/210/240), and whether a 3-year Indian bachelor is accepted (frequently *not*, for FH→Uni transitions).

### 2.5 `hzb_recognition` (anabin-derived)
| Field | Notes |
|---|---|
| `country`, `qualification_name`, `awarding_body` | |
| `status` | `direct_access` / `restricted_access` / `studienkolleg_required` / `not_recognised` |
| `anabin_class` | H+ / H+/- / H- for institutions; A/B/C for degrees |
| `notes`, `source_url`, `checked_at` | |

This single table decides whether a user is eligible *at all*. Without it, every match score is fiction.

### 2.6 `grade_conversion_rule`
| Field | Notes |
|---|---|
| `country`, `scale_type` | e.g. `IN_CGPA_10`, `IN_PERCENT`, `US_GPA_4`, `UK_CLASS` |
| `method` | `modified_bavarian` / `table_lookup` / `institution_specific` |
| `params` | `{Nmax, Nmin}` for the Bavarian formula |
| `institution_id` | nullable — some unis publish their own tables and they override the national one |

> Modified Bavarian Formula: `x = 1 + 3 × (Nmax − Nd) / (Nmax − Nmin)`
> Store both the computed value and the inputs, so you can recompute when a uni publishes its own table.

---

## 3. Financial entities

### 3.1 `fee` (per programme × term × applicant class)
| Field | Notes |
|---|---|
| `tuition_per_semester_eur` | 0 for most public unis |
| `tuition_non_eu_eur` | **Baden-Württemberg charges €1,500/sem for non-EU** — state-level, must be modelled |
| `second_degree_fee_eur` | BW again, €650/sem |
| `long_study_fee_eur` | Langzeitstudiengebühren, several states |
| `semester_contribution_eur` | Semesterbeitrag — the real recurring cost at public unis |
| `contribution_breakdown` | jsonb: `{studierendenwerk, student_body_AStA, semesterticket, admin}` |
| `application_fee_eur` | uni-assist: first application + each additional |
| `enrolment_fee_eur` | |
| `currency`, `valid_for_term` | |

### 3.2 `city` and `cost_of_living`
| Field | Notes |
|---|---|
| `city_id`, `name`, `state`, `population`, `lat/lon`, `ags` (official municipality key) | AGS lets you join **any** German official statistic |
| `rent_shared_room_min/typical/max_eur` | WG room, warm |
| `rent_studio_min/typical/max_eur` | |
| `dorm_room_eur`, `dorm_waitlist_months`, `dorm_places`, `dorm_coverage_pct` | Studierendenwerk — a cheap dorm place changes viability entirely |
| `groceries_eur`, `eating_out_eur`, `mensa_meal_eur` | |
| `utilities_eur`, `internet_eur`, `mobile_eur` | Nebenkosten split: `warm` rents include heating, `kalt` do not |
| `transport_eur` | usually 0 if semester ticket covers it — flag `covered_by_semesterticket` |
| `deposit_months` | Kaution, typically 2–3 cold rents — a big one-time hit students forget |
| `rundfunkbeitrag_eur` | national, €18.36/month per household |
| **Lifestyle block** — model these, don't lump into "misc" | |
| `leisure_eur` | cinema, bars, clubs — varies 3× between Munich and Leipzig |
| `gym_membership_eur` | often discounted via Hochschulsport (€20–40/semester vs €40/month commercial) |
| `clothing_eur` | seasonal spike: **winter kit is a €200–400 one-time cost** for students from tropical countries |
| `travel_domestic_eur` | largely absorbed by the D-Ticket — a genuine perk worth surfacing |
| `travel_home_annual_eur` | flights home; nationality-dependent, model per origin country |
| `study_materials_eur` | books, software, lab fees, printing |
| `phone_plan_eur`, `streaming_eur` | |
| `dining_style` | enum: `mensa_heavy` / `cook_at_home` / `mixed` — drives a €80–150/month swing; let the user pick |
| **One-time setup costs** (separate object, not monthly) | |
| `setup_costs` | jsonb: `{flight, deposit, furniture, bedding, winter_clothing, anmeldung, sim_card, bike, first_month_double_rent}` — typically **€1,500–2,500** and almost universally underestimated |
| `total_monthly_min/typical/max` | derived, with the formula stored |
| `basis`, `sample_size`, `observed_at`, `source_id` | |

### 3.3 `labour_market` (per city, per job category)
| Field | Notes |
|---|---|
| `city_id`, `role_category` | `werkstudent` / `hiwi_academic_assistant` / `gastro` / `retail` / `delivery` / `tutoring` |
| `hourly_wage_min/median/max_eur` | HiWi rates are published by universities; Werkstudent rates by job boards |
| `postings_count_30d`, `postings_trend` | scrape-derived proxy for availability |
| `english_ok_share_pct` | **the decisive variable for a non-German-speaker** — derive it by classifying job ads |
| `german_level_typical` | A2/B1/B2 |
| `typical_hours_per_week` | 10–20 for Werkstudent, 6–10 for HiWi |
| `net_ratio` | fraction of gross the student keeps — **minijob ≈ 1.0 (tax-free), Werkstudent above €603/mo pays pension contributions ≈ 0.91**. Storing gross only overstates income by ~9%. |
| `time_to_first_job_weeks` | reported median — a semester of zero income is the real risk |
| `requires_prior_experience` | bool |
| `observed_at` | |

**Realistic-earnings formula (store the computation, not just the result):**
```
hours_cap_weekly   = 20 during semester (140-full-day rule, 2026)
monthly_gross_max  = min(603, hours × 4.33 × wage)          # stay in minijob → tax-free
werkstudent_gross  = hours × 4.33 × wage                     # above 603 → ~9% deductions
realistic_monthly  = werkstudent_gross × net_ratio × english_ok_share_pct × job_found_probability
```
The last two factors are what separate an honest tool from the "just work part-time!" advice that strands students.

### 3.4 `scholarship`
`name`, `provider` (DAAD / Erasmus+ / Deutschlandstipendium / Stiftung / institution), `scope` (national/institution/programme), `amount_monthly_eur`, `duration_months`, `covers[]` (tuition, living, travel, insurance), `eligibility_requirements[]` (same typed shape as §2.4), `deadline`, `nationality_restrictions[]`, `field_restrictions[]`, `success_rate_est`, `source_url`.

### 3.5 `policy_constant` — hardcoded, time-versioned, authoritative
| key | value (as of 2026-07) | valid_from | source |
|---|---|---|---|
| `blocked_account_annual_eur` | 11,904 | 2025-01-01 | BMI / Auswärtiges Amt |
| `blocked_account_monthly_release_eur` | 992 | 2025-01-01 | |
| `minimum_wage_hourly_eur` | 13.90 | 2026-01-01 | Mindestlohngesetz |
| `minijob_monthly_ceiling_eur` | 603 | 2026-01-01 | Minijob-Zentrale |
| `minijob_annual_ceiling_eur` | 7,236 | 2026-01-01 | |
| `student_work_days_per_year` | 140 full / 280 half | 2026-03 | raised from 120/240 |
| `student_gkv_monthly_eur` | ~141–147 (fund-dependent) | 2026-01-01 | TK/AOK/BARMER |
| `gkv_over_30_monthly_eur` | ~270–300 | | student rate ends at 30 |
| `rundfunkbeitrag_monthly_eur` | 18.36 | | |
| `deutschland_semesterticket_eur` | 208.80/sem (→226.80 from WS26/27) | | 60% of €63 D-Ticket |
| `visa_fee_eur`, `residence_permit_fee_eur` | 75 / ~100 | | |

| `blue_card_threshold_eur` | 50,700 | 2026-01-01 | pegged to pension contribution ceiling |
| `blue_card_shortage_threshold_eur` | 45,934.20 | 2026-01-01 | applies to shortage occupations **and to any graduate within 3 years of graduating** |
| `job_seeker_permit_months` | 18 | | after graduation |

> ⚠️ **Validation rule:** any scraped financial figure that contradicts a `policy_constant` for the same period is *overwritten*, and the conflict is logged. Never let a 2023 blog post set your blocked-account number.

---

## 4. Career outcome entities (post-degree — the ROI half of the product)

A student is not buying a degree, they are buying an outcome. Everything above tells them what it costs; this section tells them what they get. Model it with the same rigour, and with **more** honesty about uncertainty — salary data is noisier and more self-selected than fee data.

### 4.1 `occupation` (the join key for all salary data)
| Field | Notes |
|---|---|
| `id`, `title_de`, `title_en`, `aliases[]` | |
| `kldb_2010_code` | German occupational classification (Klassifikation der Berufe) — **the key that unlocks every official German salary and shortage dataset** |
| `isco_08_code` | international equivalent, for cross-country comparison |
| `field_isced_f[]` | maps back to `programme.field_narrow` — this is how you connect a degree to a job |
| `requires_licence` | bool — medicine, law, teaching, psychotherapy require German state approval (*Approbation*/*Staatsexamen*); **a foreign degree in these fields often does not lead to the job at all** |
| `licence_pathway_notes` | text |

### 4.2 `occupation_salary`
| Field | Notes |
|---|---|
| `occupation_id`, `region` (national / Bundesland / AGS city), `year` | |
| `qualification_level` | `bachelor` / `master` / `phd` / `vocational` — the spread is large and usually ignored |
| `experience_band` | `entry_0_2` / `mid_3_5` / `senior_6_plus` |
| `gross_annual_p25 / median / p75_eur` | **store the distribution, never a single "average"** — salary means are skewed and mislead |
| `gross_monthly_median_eur` | |
| `net_monthly_median_eur` | computed via tax class + church tax flag + social contributions; students care about net, and German gross→net is brutal (~35–42% wedge) |
| `sample_size`, `basis` | full-time socially-insured employees vs. self-reported |
| `source_id`, `observed_at`, `tier` | |

> **Store net, and store how you computed it.** A €50,700 Blue Card salary is ~€2,900–3,100 net/month in tax class I. Quoting gross to an Indian or Nigerian student who mentally converts to rupees/naira produces wildly wrong expectations. Net + local purchasing power is the honest comparison.

### 4.3 `shortage_status` (Engpassanalyse)
| Field | Notes |
|---|---|
| `occupation_id`, `region`, `year` | |
| `is_shortage` | bool — from the BA *Fachkräfteengpassanalyse* (163+ occupations as of 2025/26) |
| `shortage_score` | BA's own index |
| `vacancy_duration_days` | how long roles stay open — the best single demand proxy |
| `qualifies_lower_blue_card_threshold` | bool — **directly changes the visa maths** |

This table is the bridge between "what should I study" and "will I be allowed to stay". A programme feeding a shortage occupation lowers the Blue Card bar to €45,934.20 and shortens the path to permanent residence — that is a concrete, checkable product answer.

### 4.4 `graduate_outcome` (per programme, or per field × institution-type where programme-level data doesn't exist)
| Field | Notes |
|---|---|
| `programme_id` *or* `(field_isced_f, institution_type, region)` | be explicit about the granularity you actually have |
| `employment_rate_6m`, `employment_rate_12m` | |
| `stay_in_germany_rate` | share of international graduates still in Germany after 2 years — **the single most decision-relevant number for your user, and the hardest to get** |
| `median_time_to_first_job_months` | |
| `starting_salary_p25 / median / p75_eur` | |
| `share_working_in_field_pct` | guards against "employed, but driving for Lieferando" |
| `top_employers[]`, `top_sectors[]` | |
| `further_study_rate_pct` | | 
| `data_granularity` | enum: `programme` / `institution` / `field_national` — **never present national-field data as programme-specific**; label it in the UI |
| `cohort_year`, `sample_size`, `source_id`, `tier` | |

### 4.5 `graduate_labour_market` (per city/region)
`region`, `year`, `unemployment_rate`, `graduate_vacancy_count`, `english_speaking_role_share_pct`, `top_hiring_sectors[]`, `avg_cost_adjusted_salary` (salary ÷ local cost index — Munich's higher pay is partly illusory), `international_hiring_friendliness_score`.

### 4.6 `roi_projection` (computed per user × programme, not stored raw)
```
total_cost   = Σ(tuition + semester_contribution) + months × monthly_need
             + setup_costs + visa/APS/flights + blocked_account_opportunity_cost
income_during= months × realistic_part_time_monthly            (from §3.3)
income_after = starting_salary_net_median × 12 × horizon_years × stay_probability
payback_months = (total_cost − income_during) / (starting_salary_net − living_cost)
```
Store every input's `source_id` and `tier`, plus a `confidence_band`. **Present ROI as a range with an explicit "assumes you find work in Germany" caveat** — the stay-rate is typically 40–55%, not 100%, and a tool that implies otherwise is doing harm.

### 4.7 Honest-modelling rules for this section
- Salary data is **Tier 3 by default** (self-reported: StepStone, kununu, Glassdoor). Only BA Entgeltatlas and Destatis Verdiensterhebung are Tier 1.
- Always show `p25–p75`, never a bare average.
- Always distinguish **gross vs net** and label which you're showing.
- Never present a national field-level median as a programme's outcome — use `data_granularity` to force the distinction into the UI.
- Flag licence-gated fields (medicine, law, teaching, psychology) loudly; a foreign degree there frequently does not convert into practice rights.
- Salary figures older than 2 years must be inflation-adjusted via the Destatis index, with the adjustment recorded.

---

## 5. Legal / visa entities

### 5.1 `visa_pathway` (per nationality × purpose)
`nationality`, `purpose` (study / studienkolleg / language course / job seeker / post-study), `visa_type` (National D §16b AufenthG), `required_documents[]`, `processing_time_weeks_min/max`, `appointment_wait_weeks`, `fee_eur`, `financial_proof_options[]` (blocked account / scholarship / Verpflichtungserklärung / parental income), `mission_urls[]`, `apply_from_country_only` bool.

### 5.2 `post_study` (national, with occasional state variation)
`job_seeker_permit_months` (18 for graduates), `work_rights_during_search`, `path_to_eu_blue_card` (salary thresholds — general + shortage occupation, updated annually), `path_to_permanent_residence_months` (21 with B1, 33 otherwise for graduates), `citizenship_years`, `Chancenkarte` points criteria.

### 5.3 `document_checklist`
Generated, not scraped: `(nationality, level, institution) → ordered list of documents` with `issuing_authority`, `apostille_required`, `translation_required`, `typical_lead_time_days`, `cost_eur`. This is what actually makes a product sticky — students don't want a list of universities, they want to know what to do on Tuesday.

---

## 6. Provenance & quality backbone (non-negotiable)

### 6.1 `source`
`id`, `name`, `base_url`, `type` (official / semi-official / commercial / community / user), `authority_tier` (1–4, see file 02), `licence`, `robots_allows`, `tdm_reservation_detected` bool, `terms_url`, `crawl_delay_s`, `contact`.

### 6.2 `snapshot`
`id`, `source_id`, `url`, `fetched_at`, `http_status`, `content_hash`, `raw_path` (S3/disk, **keep the raw HTML/markdown forever** — cheap, and it's your only defence when an extraction turns out wrong), `etag`, `lang_detected`.

### 6.3 `extraction_run`
`id`, `snapshot_id`, `model`, `prompt_version`, `schema_version`, `cost_usd`, `latency_ms`, `validation_passed`, `validation_errors[]`, `human_reviewed_by`, `reviewed_at`.

### 6.4 Field-level provenance
Every high-stakes fact (deadlines, fees, cutoffs, language minimums) stores:
`value`, `snapshot_id`, `evidence_quote`, `evidence_char_offset`, `confidence`, `agreement_count` (how many independent sources agreed), `conflict_flag`.

### 6.5 Quality tiers on each record
- `A` — from a Tier-1 official source, schema-validated, cross-confirmed by ≥2 sources or human-reviewed.
- `B` — Tier-1/2 source, single observation, schema-valid.
- `C` — LLM-extracted from prose, low confidence, or older than the freshness SLA.
- `D` — community/blog derived. **Never used for hard filters; may be shown as "reported by students".**

> Product rule: eligibility decisions may only use A/B facts. C/D facts can be surfaced with a visible "unverified — check with the university" badge.

### 6.6 Freshness SLA per field class
| Class | Refresh | Examples |
|---|---|---|
| Volatile | weekly during application season | deadlines, portal open/closed, seat counts |
| Seasonal | per semester | fees, semester contribution, NC cutoffs |
| Slow | quarterly | requirements, curriculum, rent, wages |
| Legal | on change + annual audit | policy constants, visa rules |
| Static | yearly | institution identity, accreditation |

Store `next_refresh_due` on every row and drive the crawler from it.

---

## 7. User-side entities (the other half of the matching problem)

### 7.1 `user_profile` — must mirror the requirement schema exactly
```jsonc
{
  "nationality": "IN",
  "current_country": "IN",
  "age": 23,
  "education": [{
     "level": "bachelor", "title": "B.Tech Computer Science",
     "institution": "...", "anabin_status": "direct_access",
     "duration_years": 4, "ects_equivalent": 240,
     "grade": {"value": 7.8, "scale": "IN_CGPA_10", "max": 10, "min_pass": 5},
     "grade_german": 2.16,           // computed, with rule_id stored
     "subject_ects": {"mathematics": 26, "computer_science": 84, "statistics": 8},
     "transcript_parsed": true
  }],
  "tests": {"ielts": {"overall": 7.0, "writing": 6.5, "date": "2026-03-01"},
            "gre": null, "testdaf": null},
  "german_level": "A1",
  "work_experience_months": 12,
  "publications": 0,
  "budget": {"total_available_eur": 14000, "monthly_family_support_eur": 300,
             "can_fund_blocked_account": true, "needs_scholarship": true},
  "constraints": {"preferred_terms": ["WS2027/28"], "max_tuition_per_sem": 0,
                  "cities_preferred": [], "willing_to_learn_german": true,
                  "must_allow_part_time_work": true},
  "goals": {"target_fields": ["Data Engineering","ML"], "career": "industry"}
}
```
Store the **raw user input text alongside the parsed profile** — parsing improves, and you'll want to re-derive old profiles.

### 7.2 `match_result` — store the explanation, not just the score
`user_id`, `programme_id`, `computed_at`, `engine_version`,
`hard_filter_passed` bool, `blocking_reasons[]` (e.g. `ects_subject.mathematics: have 26, need 30`),
`academic_score`, `financial_score`, `admission_probability_band` (`safe`/`target`/`reach`),
`syllabus_overlap_pct`, `evidence[]` (requirement_id → user field → verdict),
`llm_rationale_text`, `facts_used[]` (snapshot IDs — so a wrong answer is traceable).

### 7.3 `financial_viability` (computed per user × city)
```
monthly_need    = rent_typical + groceries + insurance + rundfunk + mobile + misc + transport
monthly_income  = family_support + scholarship + part_time_realistic
part_time_realistic = min(minijob_ceiling, hours_allowed_by_140_day_rule × wage_median × english_ok_factor)
surplus         = monthly_income − monthly_need
verdict         = comfortable | viable_with_job | tight | not_viable
one_time_costs  = blocked_account + visa + flights + deposit + first_semester_contribution + APS
```
Store the whole computation, each input's source, and the verdict — not just the verdict.

---

## 8. Vector store contents (what gets embedded)

Chunk and embed **only** narrative text, each with metadata `{entity_type, entity_id, institution_id, city_id, lang, source_url, tier, valid_from}`:
- programme description, "who is this for", module/curriculum prose
- admission-requirement prose **verbatim** (so the LLM can quote the exact sentence when explaining a rejection)
- FAQ pages from international offices
- visa procedure text per consulate
- city/student-life descriptions
- scholarship descriptions

Do **not** embed numbers you intend to compare. Retrieve by filtering on structured fields first, then rank by vector similarity within that filtered set.

---

## 9. Physical storage recommendation

| Layer | Tech | Holds |
|---|---|---|
| Raw | object storage (S3/MinIO), partitioned `source/date/` | every fetched HTML + markdown, immutable |
| Staging | DuckDB / Parquet | extracted-but-unvalidated JSON |
| Core | **PostgreSQL** (+ `pgvector`) | all entities above; JSONB for `requirements`, `curriculum_modules`, `component_minimums` |
| Search | pgvector (start) → Qdrant (if >5M chunks) | embeddings |
| Cache | Redis | user session, computed match results |
| Audit | append-only `fact_history` table | every value change with old/new/source |

Start with Postgres alone. A separate vector DB before ~1M chunks is premature and doubles your consistency problems.

---

## 10. Minimum viable slice (build this first)

Do not attempt all 16 states and 400+ institutions on day one. First vertical slice:

- 25 institutions, 1 field (e.g. CS/Data), Master's, English-taught, WS intake
- Entities: `institution`, `programme`, `intake`, `requirement`, `fee`, `city`, `cost_of_living`, `policy_constant`, `hzb_recognition`, `grade_conversion_rule`, plus the full provenance backbone
- ~200 programmes × ~12 requirements each ≈ 2,400 typed requirement rows — enough to prove the hard-filter engine works
- Manually verify 100% of this slice. Your extraction prompts are only as good as the gold set you build here.

Expand along **one** axis at a time: more fields → more institutions → bachelor's → German-taught.

---

## 11. Known traps this schema is designed to survive

| Trap | Schema defence |
|---|---|
| "Tuition is free in Germany" | `fee` is per state × applicant class; BW non-EU tuition is modelled |
| Deadline differs for non-EU | `intake` is keyed by `applicant_class` |
| uni-assist deadline ≠ uni deadline | separate `uni_assist_deadline` field |
| English programme becomes German later | `german_share_pct` |
| Rent quoted "kalt" vs "warm" | `basis` field on every price |
| Stale legal figures | `policy_constant` overrides scraped values |
| 3-year bachelor rejected | `prior_degree` requirement with `min_ects` + `hzb_recognition` |
| Sub-score IELTS rejection | `component_minimums` |
| NC cutoff varies yearly | `nc_last_year_*` on `intake`, not on `programme` |
| Student turns 30 → insurance doubles | `policy_constant` + age in `user_profile` |
| Dorm place vs. private rent | separate fields; viability computed both ways |
| Source page silently changes | `content_hash` on `snapshot` + `fact_history` diff |

---

*Companion document:* `02-DATA-SOURCES.md` — where each of these fields actually comes from.
