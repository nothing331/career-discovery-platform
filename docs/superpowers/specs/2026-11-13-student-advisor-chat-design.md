# Student Advisor Chat — Design (DRAFT for review)

**Date:** 2026-11-13 · **Status:** draft, awaiting founder decisions (see §6) · **Builds on:** `data-engine/` (scraper), `scraping/01-DATA-MODEL.md`, `product-workspace/research-findings/student-problems.json`

---

## 0. Intent

A free chat app where Indian students (Class 11/12 students, Class 12 pass-outs, Indian bachelor's students/graduates) talk to an advisor agent that walks them from "what is studying in Germany?" to "these are the programmes I can realistically get into, and what I have to do, by when". Every concrete fact (fee, deadline, IELTS score, rule) is shown with the official source it came from and the date it was checked.

**Why this shape:** earlier research found students' real work is (a) deciding a route — especially for bachelor's, where pathway and timing come before matching — and (b) checking their profile against requirements. Agencies are distrusted; official sources exist but are scattered. The product's edge is *clear route + cross-checkable proof*, not "AI says you'll get in".

**Goals**
- Guide a student through a structured journey without forcing it — they can jump to any question.
- Different journeys for the bachelor's route and the master's route.
- Every number comes from the knowledge base with a citation; nothing numeric is generated from model memory.
- Learn what students ask (logged, consented) to steer what we scrape next.

**Non-goals (v1)**
- Admission prediction or "your chances are X%".
- Submitting applications, uploading documents, paid features.
- Countries other than Germany; subjects beyond the seeded set.

**Anti-goals (failure even if it "works")**
- Confidently stating a stale or wrong fee/deadline/rule.
- Telling a Class 12 student they can apply directly to a bachelor's when they can't (Studienkolleg/70% rule).
- Collecting more personal data than the conversation needs (DPDP; see `research-findings/privacy-data.json`).

---

## 1. Part one — the conversation structure

The journey has **7 stages**. The agent always knows which stage the student is in and what it still needs to know, but a direct question ("what's TUM's fee?") is always answered immediately, then the agent offers to return to where they were.

```
 ┌─ S0 Hello & who are you ──────────────────────────────────────────┐
 │   (2–3 questions max → picks the track)                           │
 └──────────────┬──────────────────────────────┬─────────────────────┘
                │ Class 11/12 / 12-pass        │ Bachelor's student / graduate
                ▼                              ▼
          S1 Germany 101  (shared, shorter for master's track)
                │                              │
                ▼                              ▼
     S2B Can I get in? (Bachelor)     S2M Can I get in? (Master)
     HZB · 70% rule · 3 routes        degree length/ECTS · grades
     Studienkolleg = "13th year"      APS · dMAT · subject fit
                │                              │
                └──────────────┬───────────────┘
                               ▼
                 S3 Exams & documents checklist
                               ▼
                 S4 Explore colleges (types → fields → list)
                               ▼
                 S5 Programme deep-dive & fit check
                               ▼
                 S6 Your plan: timeline, money, visa
```

### S0 — Hello & who are you
- **Goal:** pick the track; collect the *minimum* profile.
- **Asks (one at a time, all skippable):** current stage (Class 11 / Class 12 / 12-pass / in bachelor's year N / graduated); field of interest (engineering, CS, natural science, business, medicine, "not sure"); for Class 12: board + expected/actual percentage + JEE Advanced taken?; for graduates: degree name, 3 or 4 years, CGPA.
- **Exit:** track known (bachelor/master/unsure). Unsure → S1 then ask again.
- **Never asks:** name, phone, email, parents' income (budget is asked later as a range, optional).

### S1 — Germany 101
- **Covers:** why Germany (public universities, low/no tuition — *with the exceptions*), the **types of institutions** (Universität, Technische Universität & TU9, Fachhochschule/HAW = University of Applied Sciences, art/music colleges, public vs private), degrees (Bachelor 6–8 semesters, Master 2–4, Staatsexamen), English- vs German-taught (≈300 English bachelors vs ≈2,000 German; 2,000+ English masters), the semester contribution.
- **Must say early:** tuition is *not* free everywhere for non-EU students — Baden-Württemberg charges €1,500/semester (KIT, Tübingen, Freiburg, Heidelberg, Stuttgart), TUM charges per programme, FAU announced fees from SS 2027 (unverified).
- **Style:** short cards, not walls of text; "want more on X?" chips.

### S2B — Can I get in? (Bachelor track) — the critical stage
1. **HZB in plain words:** "Germany needs a school-leaving certificate that counts as university entrance. An Indian Class 12 on its own usually does not."
2. **Gate check — the 70% rule (new, from 15 March 2026, applies from WS 2026/27):** the Studienkolleg route and the one-year-in-India route both need ≥70% overall in Class XII (any board) [APS India news, 23 Feb 2026]. Agent asks for the percentage if not known and branches:
   - ≥70% → show the routes.
   - <70% → honest message: no Class-12 route; options are an Indian bachelor's then a German master's (switch to master's track preview), or a private/foundation option (flagged as paid).
   - JEE Advanced passed → direct subject-restricted entry for technical/science subjects (whether the 70% rule also applies is **open** — say so).
3. **The routes:**
   - **(a) Studienkolleg + Feststellungsprüfung ("the 13th year")** — 1 year (2 semesters), ~32 h/week, free at state colleges (semester fee still applies), entrance exam (Aufnahmeprüfung) in Germany, usually German B1–B2 needed, course types by intended subject: **T** (engineering/maths/science), **M** (medicine/biology), **W** (business), **G** (humanities/law), **S** (languages); UAS-Studienkollegs: TI/WW/GD/SW. You apply *through a university* (e.g. LMU/TUM → Studienkolleg München; Heidelberg, Freiburg, Tübingen, Stuttgart → Studienkolleg Heidelberg/Karlsruhe; TU Darmstadt has its own; FU Berlin's own via uni-assist; Saarland uses its VSI prep year instead). Passing FSP does not guarantee a place.
   - **(b) JEE Advanced** — direct application to technical/science subjects.
   - **(c) One successful year at a recognised Indian university** in the same/related subject → direct subject-restricted admission.
   - **(d) IB / GCE** where relevant.
4. **Language reality:** Studienkollegs teach in German; English Studienkollegs are rare (a few paid foundation years). An English-taught bachelor still needs HZB.
- **Exit:** student knows which route applies to them, or that they should go via master's.

### S2M — Can I get in? (Master track)
- 4-year B.Tech/B.E. → generally treated as equivalent; 3-year B.Sc/BCA → **depends on the programme** (180 vs 210/240 ECTS) — agent checks per programme in S5, never generalises.
- Grade conversion (Modified Bavarian formula) — agent can compute it, labelled "estimate; the university converts it itself".
- **APS certificate** — mandatory for Indian applicants (bachelor's, master's and Studienkolleg): what it is, fee (≈₹18,000 — *unverified*), 4–12 weeks, start Jan–Mar for winter intake.
- **dMAT** — mandatory for Indian-degree master's applicants in engineering, commerce/economics, business from SS 2027 intake (details medium-confidence).
- Subject fit: minimum ECTS in maths/CS etc. (we have this for some programmes, e.g. Hamburg M.Sc.).

### S3 — Exams & documents
Personal checklist built from S0–S2: APS, IELTS/TOEFL (typical 6.0–7.0 / 80–100), German tests (TestDaF TDN4, DSH-2, telc C1, Goethe), Studienkolleg entrance test, dMAT, GRE (rare, programme-specific), VPD from uni-assist where needed. Each item: what, why, cost, lead time, official link.

### S4 — Explore colleges
Order: **by type → by field → list**.
- "Technical universities (TU9) — engineering/CS strength", "Research universities — sciences, broad", "Universities of Applied Sciences — practical, internship semester, many English master's", "Art/music — aptitude test".
- Then field (engineering, CS, natural sciences, business…), then filters the student cares about: teaching language, tuition for non-EU, state/city, application route.
- Output: a short list of cards (university · city · type · language · non-EU tuition · apply via) with "tell me more".

### S5 — Programme deep-dive & fit check
For a chosen programme: requirements (verbatim quotes with source links), language test minimums, deadlines for non-EU applicants, fees, application route, APS. Then **fit check** against the profile: each requirement marked **meets / gap / unclear — ask the university**, with the quote that decides it. Compare 2–3 side by side.

### S6 — Your plan
Backwards timeline from the target intake (WS starts ~1 Oct; e.g. Studienkolleg/bachelor: start 12–18 months ahead; APS Jan–Mar; applications Mar–Jun; visa July, ~2 months). Money: blocked account €11,904/year (2026), semester fee, non-EU tuition, rent ~€410/month avg, living €900–1,200/month. Visa documents list. Part-time work (140 full / 280 half days), 18-month job-seeker permit after graduation (to re-verify). Exportable as a PDF/shareable plan.

### Conversation rules (apply in every stage)
1. **Numbers only from tools.** If the KB doesn't have it: "I don't have a verified figure — here's the official page."
2. **Every fact shows source + "checked on" date.** Unreviewed/medium-confidence facts are visibly marked.
3. **No guarantees.** "Meeting this doesn't guarantee admission" wherever eligibility is discussed.
4. **One question at a time**, all optional; the profile panel lets the student fill or correct details directly.
5. **Plain English first**, German term in brackets once (Studienkolleg, Sperrkonto…).
6. **Escalate to the official office** for anything individual (anabin decisions, edge-case boards, gap years).

Example opening:
```
Agent: Hi! I help Indian students figure out studying in Germany — which route fits you,
       which universities, and what to do when. Where are you right now?
       [Class 11/12] [Finished Class 12] [Doing my bachelor's] [Finished bachelor's]
Student: Finished Class 12, I want engineering
Agent: Nice. One thing matters a lot for Germany: your Class 12 overall percentage.
       Since March 2026, the usual routes need at least 70%. Do you know yours? (optional)
```

---

## 2. Part two — how we build it technically

### 2.1 Approaches considered

| | Approach | Trade-off | Verdict |
|---|---|---|---|
| A | **Plain vector RAG** — chunk every scraped page, embed, retrieve top-k, generate | Fastest to build. But numbers from different universities get mixed in one context; "English-taught, no tuition, in Bavaria" is a filter, not a similarity search; no way to say "we don't know". | ✗ for facts |
| B | **Structured-first, tool-calling ("agentic") hybrid RAG** — LLM agent calls typed tools: SQL over structured facts for anything numeric/filterable, hybrid keyword+vector search over curated guide text for explanations, deterministic fit-checker | Slightly more build work (tools + schema). Exact numbers, filtering, citations and "unknown" all fall out naturally. Matches `scraping/01-DATA-MODEL.md` principle "separate FACTS from TEXT". | ✓ **recommended** |
| C | **Scripted decision tree** with LLM only for wording | Most predictable, but students ask free-form questions; rigid. | Use *inside* B as stage playbooks |
| D | **GraphRAG / knowledge graph** | University→programme→requirement relations are already relational; graph adds infra for no gain at 17 universities / 34 programmes. | ✗ for now |

### 2.2 Recommended architecture (B)

```
 Student ──► web (chat UI + profile panel)
                 │  SSE stream
                 ▼
            api: Orchestrator
            ├─ session state: {track, stage, profile, open_questions}
            ├─ stage playbook (system-prompt section per stage S0–S6)
            └─ LLM with tools:
                 search_guide(query, stage?)          → hybrid BM25+vector over guide cards & official-page chunks
                 find_programmes(filters)             → SQL (field, level, language, state, type, non-EU tuition, route)
                 get_programme(id) / get_university(id) → structured facts + verbatim evidence + source/date
                 compare_programmes(ids, fields)
                 check_fit(profile, programme_id)     → deterministic rules → meets/gap/unclear + deciding quote
                 get_constant(name)                   → policy constants (blocked account, work days, BW tuition…)
                 update_profile(fields)               → writes to session profile (with student-visible confirmation)
                 │
                 ▼
            App KB (Postgres + pgvector)  ◄── ingest ◄── published KB release from scraper/
```

- **Guide layer (text):** ~40–80 curated *guide cards* (one topic each: HZB, 70% rule, Studienkolleg, APS, uni types…), written from official pages, each with source URLs, `checked_at`, `valid_from`, confidence. Plus chunks of the official pages themselves for long-tail questions. Retrieval: hybrid (Postgres full-text + pgvector) with metadata filter on stage/topic, then rerank.
- **Fact layer (structured):** institutions, programmes, structured facts, requirement quotes, policy constants — all from the scraper's **published** release only (never staging).
- **Fit checker:** plain code, not the LLM. The LLM explains its output.
- **Answer contract:** the model's response carries `citations[]` referring to fact/card IDs returned by tools; the UI renders them. A post-check rejects any number in the answer that didn't come from a tool result (simple regex vs. tool payload).
- **Models:** provider abstraction (like the scraper's OpenRouter/Groq layer). A capable model for the orchestrator, a small cheap one for stage detection / profile extraction. Picked by the eval below, cost-capped since the launch is free.
- **Evaluation:** a golden set of ~60 questions across S0–S6 (incl. traps: "Is Germany free?", "Can I join TUM after 12th?", "I have 65%") with expected facts; automatic checks for correct numbers + citation present + no-guarantee language.
- **Privacy:** anonymous sessions by default; profile stored per session; logs minimised; explicit consent for keeping transcripts.

### 2.3 Monorepo layout

```
career-discovery-platform/
├── scraper/                  ← today's data-engine/ (git mv; Python/uv, unchanged internals)
│   └── exports a versioned KB release (SQLite/JSONL) — the ONLY interface to the app
├── app/
│   ├── api/                  Python · FastAPI · agent orchestrator, tools, retrieval, ingest
│   └── web/                  Next.js · chat UI, profile panel, citation cards, plan export
├── packages/
│   └── kb-contract/          JSON Schema + pydantic models of the KB release (shared by both)
├── content/
│   └── guide/                curated guide cards (Markdown + front-matter: sources, checked_at)
├── docs/                     specs (this file); optionally move 00-intake…06-validation, product-workspace, scraping/ here
├── pyproject.toml            uv workspace: scraper, app/api, packages/kb-contract
└── package.json              pnpm workspace: app/web
```
Rule: `app/` never imports `scraper/` code or reads its staging DB. It ingests a published release that validates against `kb-contract`.

---

## 3. Part three — data we still need (prioritised)

Current state (2026-11-13): 34 CS programmes / 17 universities; ~1,500 claims; structured facts for 25 of 34 programmes and very uneven (Passau M.Sc. 47, LMU/Bochum/TU Darmstadt B.Sc. 0); **0 human-approved, 13 published structured facts**. No Germany-level, university-level or Studienkolleg data.

**P0 — needed before the first student session**
1. **Review & publish** the existing CS slice (the app reads published data only).
2. **Guide content (S1–S3, S6):** scrape + curate from the official pages listed in Appendix B; turn into guide cards.
3. **Policy constants table:** blocked account €11,904 (2026), BW non-EU tuition €1,500, 140/280 work days, 70% Class XII rule (from 15 Mar 2026), APS fee, dMAT start, etc. — each with source, `valid_from`.
4. **University profiles (17):** type, TU9, city/state, non-EU tuition, semester contribution, application route (uni-assist / direct / VPD+portal), Studienkolleg used, APS statement, international-applicants URL. Seed in Appendix A (needs verification).
5. **Studienkolleg directory:** each college, courses (T/M/W/G/S), host, which universities feed it, German level, entrance-exam timing, fees (some now charge, e.g. Leipzig from WS 2026/27), application route.

**P1 — makes S4/S5 useful beyond CS**
6. **More subjects:** mechanical, electrical, civil engineering; physics, chemistry, biology; data science; business — the user's "engineering colleges, scientific colleges" ask.
7. **Universities of Applied Sciences (HAW/FH):** none in the registry today; add ~10 with English-taught master's.
8. **Per-programme fields missing today:** teaching language (reliably), non-EU deadlines with year, application route per programme, intake semesters, minimum grade, subject-ECTS minimums, 3-year-degree acceptance, GRE/dMAT applicability, restricted vs open admission, curriculum/module list (for master's fit).

**P2 — later**
9. City cost of living & dorm rents (Studierendenwerk), scholarships (DAAD), career outcomes.

---

## 4. Open questions / conflicts the advisor must surface, not hide
1. 70% rule: confirmed on APS India; anabin text not checked; applicability to JEE Advanced holders unknown.
2. Studienkolleg German level B1 vs B2 differs per college.
3. 3-year degrees (180/210/240 ECTS): only blog evidence — per programme.
4. APS fee ₹18,000, dMAT fee/dates: blogs only.
5. FAU non-EU tuition from SS 2027 and TUM amounts: unverified on official pages.

## 5. What's left to the builder
Exact tables for ingest, prompt wording per stage, UI styling, hosting, auth — all decided in the implementation plan.

## 6. Decisions needed from the founder
1. **Which slice does v1 launch with?** (CS only, polished — or wait for engineering + sciences + HAWs.)
2. Approve approach B and the monorepo layout (incl. renaming `data-engine/` → `scraper/`).
3. Model/provider and monthly cost cap for the free launch.

---

## Appendix A — University profile seed (research agents, 2026-11-13; **unverified, re-scrape before use**)

| University | Type / TU9 | State | Non-EU tuition | Semester contribution | Apply via (non-EU) | Studienkolleg | APS stated |
|---|---|---|---|---|---|---|---|
| TUM | TU · TU9 | BY | yes, per programme (≈€2–3k B / €4–6k M; ↑ WS27/28) — medium | ? | uni-assist VPD → TUMonline | Studienkolleg München | — |
| LMU | Uni | BY | not found | €97 (Studierendenwerk, WS26/27) | VPD (from SS27) → LMU portal | Studienkolleg München | — |
| RWTH Aachen | TU9 | NRW | none (unconfirmed) | ≈€375 (unverified) | direct portal (secondary source) | — | — |
| TU Darmstadt | TU · TU9 | HE | not stated | €402.68 (WS26/27) | TUCaN direct | own (Studienkolleg Darmstadt, G/T) | ✓ |
| KIT | TU9 | BW | €1,500 ✓ | €151.20 official part | direct | KIT page (operator unconfirmed) | — |
| Tübingen | Uni | BW | €1,500 ✓ | €194.80 (WS26/27) | direct (no uni-assist ✓) | Heidelberg (secondary) | — |
| FAU | Uni | BY | €1–3k from SS27 (unverified, site blocked) | ≈€82 (unverified) | direct (campo) | — | — |
| Bonn | Uni | NRW | none | €363.07 (WS26/27) | university | none public | — |
| Heidelberg | Uni | BW | €1,500 (state rule) | ≈€189.80 | heiCO direct | own (Studienkolleg Heidelberg) | — |
| Stuttgart | Uni · TU9 | BW | €1,500 ✓ | €184 | C@MPUS direct | via Heidelberg/Karlsruhe | — |
| TU Dresden | TU · TU9 | SN | none stated | ≈€360 | uni-assist | Leipzig (fees from WS26/27) / TUDIAS (paid) | ✓ |
| FU Berlin | Uni | BE | not confirmed | ≈€376.80 (unverified) | uni-assist VPD → FU portal | own (via uni-assist) | ✓ |
| Bochum | Uni | NRW | — | ≈€300 (unverified) | RUB portal | — | ✓ |
| Freiburg | Uni | BW | €1,500 ✓ | €190 | HISinOne direct | Heidelberg | — |
| Hamburg | Uni | HH | not found | €402 (WS26/27) | university portal (bonus-point selection) | Studienkolleg Hamburg | — |
| Saarland | Uni | SL | — | €412.30 (WS26/27) | uni-assist VPD → SIM portal | none — VSI prep year | — |
| Passau | Uni | BY | — | €134 (SS27) | uni-assist or portal (varies) | Studienkolleg München | ✓ |

Notable: Passau's English-taught bachelor is AI, not CS; Saarland's CS B.Sc. is English-taught (B2).

## Appendix B — Official pages to scrape for the guide layer
To become a "guide" registry in `scraper/config/`. Stage = conversation stage served; change = how often to re-check.

| URL | Stage | Change |
|---|---|---|
| https://aps-india.de/news (and main/fees/FAQ pages) | S2B, S2M, S3 | often |
| https://www.daad.in/en/study-research-in-germany/studying-in-germany/bachelor-studies/ | S2B, S6 | yearly |
| https://www.daad.in/en/study-research-in-germany/studying-in-germany/master-studies/ | S2M, S6 | yearly |
| https://www.daad.de/en/studying-in-germany/requirements/admission-database/ | S2B, S2M | rarely |
| https://www.daad.de/en/studying-in-germany/requirements/overview/ | S2–S3 | yearly |
| https://www.daad.de/en/studying-in-germany/living-in-germany/finances/ | S1, S6 | yearly |
| https://india.diplo.de/in-en/service/2756350-2756350 (study visa, APS, language) | S6 | often |
| https://india.diplo.de/in-en/service/2546328-2546328 (national visa FAQ) | S6 | often |
| https://www.make-it-in-germany.com/en/study-vocational-training/studying-in-germany/requirements | S2–S3 | yearly |
| https://www.make-it-in-germany.com/en/visa-residence/types/job-search-qualified | S6 | rarely |
| https://anabin.kmk.org (India → Hochschulzugang; manual lookup) | S2B, S2M | rarely, but changed 15 Mar 2026 |
| https://www.uni-assist.de/en/ (how to apply, deadlines, VPD) | S2M, S3, S6 | yearly |
| https://www.study-in-germany.de | S1, S6 | yearly |
| https://www.hochschulkompass.de/en/ | S1, S4 | often |
| https://www2.daad.de/deutschland/studienangebote/international-programmes/en/ | S4 | often |
| https://www.studienkollegs.de | S2B | yearly |
| https://www.hochschulstart.de | S6 | yearly |
| https://www.testdaf.de · https://www.goethe.de | S3 | yearly |
| https://www.gast.de (dMAT) | S2M, S3 | often |
| https://www.auswaertiges-amt.de (study visa, blocked account) | S6 | yearly |
| https://www.studierendenwerke.de | S6 | yearly |
| https://www.daad.de/en/studying-in-germany/scholarships/ | S6 | yearly |
| https://www.tum.de/en/studies/tuition-fees | S1, S4 | yearly |
