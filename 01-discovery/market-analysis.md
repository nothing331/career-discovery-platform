# Market Analysis — Indian Study-Abroad Counselor Tooling (Germany + Australia Beachhead)

**Phase:** 3 — Discovery / Research
**Project:** career-discovery-platform (post-pivot: Study-Abroad Counselor Copilot)
**Date:** 2026-05-25
**Confidence:** Overall: **Medium**. TAM/destination-volume data is High (Tier 1 govt/DAAD/MEA sources). SAM/SOM and per-agency tooling-spend remain Medium-Low — these depend on agency counts and budget tolerances that no public dataset cleanly enumerates. Geographic ranking is Medium-High after AAERI directory deduplication.

---

## Executive Summary

The Indian study-abroad agency-tooling market is **real but small and contracting at the headline**: TAM ~₹150–300 cr ($18–36M), realistic SAM ~₹5–7 cr ($670K) for a Germany+Australia-focused point tool, and a strictly-qualified primary segment of only **15–25 agencies** out of a deduplicated mid-size pool of ~120–150 [aggregated from `market-size.md` and `target-audience.md`]. Underlying Indian outbound student volume **declined 5.7% in 2025 to 1.254M** [Data — MEA via ICEF, Dec 2025] — the first contraction in three years — but the *destination mix is what matters for this product*: Germany Indian enrollment grew **+15.1% YoY** to 59,419, while Australia visa approvals are down **48% from the 2023 peak** [Data — DAAD Sept 2025; The Federal/Business Standard 2025]. The optimal beachhead is the **Delhi NCR + Chandigarh + Punjab corridor**, which holds 45–50 of the 120–150 deduplicated mid-size agencies in one drivable zone, with the highest AAERI density in the country. Timing is favorable — DPDP enforcement (May 2027) creates a forced-buy event, AI-aware students arrive at meetings AI-prepped while counselors are not, and no incumbent has productized a take-home discovery PDF for Indian agencies — but the window is **12–18 months** before Meritto's Mio AI suite ships a discovery-PDF bolt-on. India-only the company tops out around **₹1.5 Cr ARR sustainable / ₹3 Cr stretch**: a fundable seed business, not a Series A; geographic expansion (Nepal Month 13–15) is structurally required, not optional.

See `competitor-landscape.md` for incumbent-threat detail and `target-audience.md` for buyer persona.

### Critical reframe carried through this analysis

The product's founder-stated rationale — that the AI replaces a 2–3 hour head-counselor discovery session — is **NOT independently corroborated by customer voice** [see `target-audience.md` Pain Hierarchy and `confidence-dashboard.md` claim #6]. Independent voice (Reddit, Glassdoor, AAERI 2023 survey, Outlook India journalism) corroborates a *different* pain: **post-payment trust collapse** ("they ghosted us," "service deteriorates after the cheque clears," "we paid ₹4.5L and got nothing real"). The PDF deliverable is therefore best understood as a **trust-restoration artifact** — a branded, evidence-cited, family-shareable record the agency stands behind in writing — and only *secondarily* as a time-saver. This reframe runs through every section below. Where the market analysis discusses "buyer adoption," "competitive switching triggers," "pricing capture," and "GTM messaging," the underlying value proposition is the trust artifact; the time-saving angle is a hypothesis the founder must validate in the first 5 design-partner interviews [Yellow Flag carried to Flags section].

---

## Market Sizing

### TAM — Total Addressable Market

**Headline: ₹150–300 cr (~$18–36M)** [Estimate, Medium confidence — A1].

| Layer | Value | Confidence | Source |
|---|---|---|---|
| Indian outbound students 2025 (tertiary, all destinations) | 1.254M | **High** | MEA via ICEF Monitor, Dec 2025 |
| Indian outbound to Germany (winter sem 2024/25) | 59,419 | **High** | DAAD, Sept 2025 |
| Indian outbound to Australia (2025) | 138,579 | **High** | MEA via ICEF, Dec 2025 |
| Combined G+A as share of total | ~16% of outbound | **High** | Derived |
| Indian study-abroad spending market (FY24→FY29) | $38B → $58B | **High** (RedSeer is Tier 1) | RedSeer 2024–25 |
| Approximate # of Indian study-abroad agencies (all sizes) | 10,000–15,000 | **Low** (no clean register) | Triangulated, A1 |
| Per-agency tooling spend (weighted avg) | ~₹1.5L/yr | **Low-Medium** | Estimated, A1 |
| **TAM math: 12,000 × ₹1.5L** | **₹180 cr** | **Medium** | Synthesis |
| Bullish ceiling (India's share of global $10.5B agency-services market × tooling%) | $14–42M | **Medium** | Verified Market Reports + derived |

**Cross-check:** The "India's slice of global agency services" path lands in the same ₹150–300 cr corridor. Internally consistent.

### SAM — Mid-Size Agencies, Germany + Australia Focus

**Headline: ₹15–20 cr all-destinations; ₹5–7 cr G+A-only** [Estimate, Low-Medium confidence].

A1 originally estimated the mid-size segment at 1,500–2,500 agencies. **C3 deduplicated that hard count against AAERI (~92–117 named members — see footnote in `target-audience.md`: reported headline is 92 but regional split sums to 117, gap pending founder reconciliation) + AIRC India (17–25) + non-association tail and landed at ~120–170 mid-size agencies that are realistic SaaS buyers.** This is the figure to plan against — the larger A1 number was an unfiltered industry estimate. The Year-1 SOM math (25 agencies) is comfortable under either 120 or 170 — does not change the conclusion.

- 2,000 mid-size agencies × ₹80K ACV midpoint = ₹16 cr all-destinations
- G+A-only haircut (~35% of perceived value because most mid-size agencies are multi-destination) = ~₹5.6 cr
- **Strictly-qualified primary segment (pure G+A focus): only 15–25 agencies** — 10–15% of the 120–150 deduplicated pool (C3). Most mid-size agencies are multi-destination by necessity.

This last number is load-bearing. The Year-1 SOM (25 paying agencies) effectively requires **majority capture of the strictly-qualified primary segment**. Year 2 growth requires either (a) expanding into the broader multi-destination 120–150 pool by adding UK/Canada coverage, or (b) cross-border expansion (Nepal first — see `target-audience.md` and Geographic section below).

### SOM — Year-1 Realistic Capture

**Headline: ₹15–50 lakh ARR (~$18–60K) by end of Year 1** [Estimate, Low-Medium confidence].

Anchored on three independent triangulations:

1. **Indian B2B SaaS seed-stage Year-1 ARR benchmarks:** $100K–$500K for niche verticals; Indian ACVs run 40–60% lower than global benchmarks (upGrowth 2026). For a 2-SDE side-project team substantially below normal seed staffing, the lower-end of this band is realistic.
2. **Pricing model derivation (C2 / `demand-signals.md`):** Tiered ARPU of ₹2,999 / ₹7,999 / ₹14,999 monthly. Blended ARPU of **₹6,500–₹8,500/mo** at the expected mix (60% solo, 35% mid, 5% large). 25 paying customers × ₹7,500 × 12 = **~₹22.5L ARR exiting Year-1**.
3. **Funnel realism (D1 / `channels.md`):** ~520 LinkedIn cold touches over 90 days → ~10 demos → 3–5 pilots → 2–4 paid by day 90. Steady state of 1–3 new paid logos/month for months 4–12. 25 logos by end of Year 1 is the realistic top of the cone; 15 is the floor.

Year-1 SOM **majority captures the strictly-qualified primary segment** of 15–25 G+A-focused agencies. The implication: Year 2 growth requires either expanding ICP (multi-destination agencies, UK/Canada coverage) or geographic expansion. Either path is non-trivial.

---

## Growth Trajectory

| Destination | 2025 Indian volume | YoY direction | Implication for product |
|---|---|---|---|
| **Germany** | 59,419 (winter sem 2024/25) | **+15.1% YoY**; doubled since 2020 (28,905) | Tailwind. Germany counselor-knowledge depth at mid-tier agencies is weakest of all major destinations — biggest counselor-value-add opportunity. |
| **Australia** | 138,579 (still #2 destination) | Visa apps **-48% vs 2023 peak**; H1 2025 visa apps ~half of 2023; Jan 2026 reclassified to Evidence Level 3 | Demand contracting BUT counselor workload per student rising (EL3 manual financial doc review, GTE statements, 8-week processing). Net: more counselor work per student is a tailwind for the *tool*, even as raw volume softens. |
| **Total Indian tertiary outbound** | 1.254M | **-5.7% YoY** (first contraction in 3 years; ~76,000-student drop) | Headline cooling. The "16% CAGR to 2M by 2027" RedSeer narrative is now in doubt. |
| **UK** | 173,190 | Cooling | Out of beachhead but bleeds into the multi-destination agency reality. |
| **Russia / Kyrgyzstan / Georgia** | 60K combined | Growing (low-cost medical) | Not in product scope but absorbs unfundable tier of demand. |

**The asymmetric pairing is defensible.** Germany alone is timing-right but underweights the cash-rich Australia use case (₹15–25L tuition, where counselor packages are largest). Australia alone would be timing-wrong. The combination gives the product *two distinct counselor pain points*: (a) Germany — counselor knowledge gap; (b) Australia — complexity surge (EL3, GTE, visa risk management).

**Forward outlook (2026–2029):** 5–10% CAGR for the agency tooling layer is realistic. Bull case 14% requires Indian outbound rebound; bear case flat-to-negative if Australia caps + US visa drag persist. The destination mix shift toward Germany is structural (rupee depreciation, US visa crackdown, Australia caps) and likely to continue regardless of the headline cooling.

---

## Market Maturity

**Call: Emerging-to-Growing, in a transitional moment.**

| Indicator | Reading |
|---|---|
| Category recognition by buyers | Low — "discovery PDF tooling" is not a budget line item; buyers have to be educated |
| Reference customers / case studies | Near-zero in this exact wedge — no incumbent has shipped this SKU |
| Investment activity in adjacent layers | High — H1 2025 Indian edtech rebounded to $120M / 11 deals (5× prior comparable); Leap $55M, Leverage profitable, Manifest Global consolidating (Inc42, Outlook Business) |
| Competitor maturity | Adjacent (Meritto, SmartX) is mature CRM; direct (discovery-PDF for Indian agencies) is unbuilt |
| Buyer technology readiness | 75% of Indian students already use AI tools for program research [Leap Scholar Beyond Borders 2025] — demand-side is mainstream; counselor-side is materially behind |

This is **not** a mature market for the specific product — there is no incumbent doing this exact thing. It is **emerging within an adjacent mature market** (study-abroad agency CRMs at SmartX/Meritto/LeadSquared have done the category-creation work of normalizing ₹5K–₹25K/mo Indian-vertical SaaS spending).

**Strategic implication:** the product does not need to teach buyers that SaaS is a real expense (SmartX has done that) — it needs to teach them this is a *separate* line item from CRM. That framing battle is the central GTM challenge.

---

## Unit Economics Benchmarks

| Metric | Range | Source / Notes |
|---|---|---|
| **Indian B2B SaaS ACV (₹10–30 cr ARR stage)** | ₹4–8L | upGrowth 2026; 40–60% lower than global benchmarks |
| **Niche SMB study-abroad agency ACV (Year-1 realistic)** | ₹50K–₹2L | A1 estimate; matches SmartX comp pricing |
| **CAC (Indian B2B SaaS, ₹10–30 cr ARR stage)** | ₹1.2–2.5L | upGrowth 2026 |
| **CAC (founder-led, this niche, Year 1)** | ₹30K–₹1L | A1 estimate; mostly founder-time |
| **LTV:CAC target** | 2.5–3× | Indian SaaS benchmark |
| **CAC payback** | 14–20 months | upGrowth 2026 |
| **SMB SaaS monthly churn** | 3–7% | = 31–58% annual; multiple SaaS benchmark reports 2025–26 |
| **First-90-days SMB customer-loss share** | 43% | 2025 SaaS benchmarks |
| **Plan for Year-1 gross annual churn** | 40–50% | Indian SMB pattern; aim to drive to 20–25% by Year 2 |

**Unit economics implication:** at ACV ₹80K, 40% annual churn, ~₹65K CAC → LTV ~₹2L, payback ~32 months. **Tight unit economics by global standards** but workable for a 2-SDE side-project team where founder-time is the binding constraint, not cash burn. Cross-reference: `competitor-landscape.md` derives the same conclusion from a different angle (the 6–12 month Meritto threat means there isn't time for a 2–3 year payback anyway).

---

## Regulatory Summary

The full picture is in the regulatory raw (`regulatory.md`) and reframed for product design in `industry-trends.md`. For market analysis specifically:

- **DPDP Rules notified Nov 13, 2025; full enforcement May 13, 2027** — 18-month phased rollout. Consent Manager framework operational Nov 13, 2026.
- **Compliance is a forced-buy lever, not a blocker.** Indian mid-size agencies will be asking vendors about DPDP in H2 2026 once consent-manager registration goes live. A SaaS arriving with India-residency + DPDP-aligned DPA + verifiable parental consent for minors is a default-superior choice over a counselor's homebrew ChatGPT workflow that logs all PII to US servers.
- **Cost to comply:** ₹4–8 lakh + 6–10 dev-weeks in Year 1 (A3 estimate). Not crushing for a 2-SDE team but not zero either. **This is the single biggest non-engineering line item in Year 1.**
- **No mandatory MEA registration** for study-abroad consultants today — the "education agent license" question is widely confused with the Emigration Act 1983 (which only covers labour recruitment). Counselor customers can operate today without any license.
- **Punjab state-level rules** require local municipality license + incorporation + GST. Punjab is the only Indian state with active enforcement. This is **net positive for SaaS adoption in Punjab** — pitch the product as "audit-ready" record-keeping (see `industry-trends.md` for the wedge framing).

---

## Geographic Analysis

The full deconstruction is in `geographic.md` (D2). Key synthesis for market analysis:

### Beachhead: Delhi NCR + Chandigarh + Punjab corridor

- **Density:** ~28 (Delhi NCR AAERI) + ~17 (Chandigarh AAERI) + 4–6 AIRC overlap + Punjab tail (Skybird Mohali, Jupiter Chandigarh, Abroad Gateway, APSA) = **~45–55 named mid-size agencies** in one 5-hour driving radius [regional counts pending founder reconciliation against the AAERI directory — see footnote in `target-audience.md`].
- **Why:** Highest AAERI density nationally; Australia-corridor heavy (matches half the beachhead); Delhi-based founder accessibility (3–4 in-person meetings/day in NCR, weekly Chandigarh trips); tight AAERI-Delhi WhatsApp circle (one warm intro opens 5–8 doors); Germany overlap (DAAD office, Goethe Max Mueller Bhavan, German Embassy visa section all in Delhi).
- **Win condition:** 8–12 paying customers in this corridor by Month 4 → product-market-fit signal for G+A agencies.

### Expansion sequence (within India)

| Phase | Metro | Trigger to enter | Estimated # ICP-qualifying agencies |
|---|---|---|---|
| Phase 1 (M1–M4) | Delhi NCR + Chandigarh + Punjab corridor | Day 0 | 75–90 (incl. non-association Punjab tail) |
| Phase 2 (M4–M6) | Mumbai + Pune | 10 paid in Phase 1 + ≥1 reference logo | ~25 |
| Phase 3 (M7–M9) | Hyderabad + Bangalore | ₹40–50L ARR (signals product survives without founder) | ~32 but G+A focus rate lowest in country |
| Phase 4 (M9–M12) | Ahmedabad + Surat + Tier-2 tail | Phase 3 proves out without founder in the room | ~15–20 |

### Year-2 international: Nepal-first

- Nepal: 200–400 outbound agencies (Kathmandu-dense); 7th-largest sender globally (~113K outbound 2025); AU is top destination, Germany secondary; Hindi/English overlap; NPR-INR near-peg; ECAN (Education Consultancy Association of Nepal) is the AAERI analog. **Lowest-friction international expansion path.**
- Plausibly adds ₹50–80L ARR by Year 2 end — this is the move that takes the company from "seed-stage feature-rich tool" to "Series-A regional infrastructure."

### India-only ARR ceiling

At ₹50K–₹2L ACV and ~120–150 deduplicated mid-size G+A agencies, the absolute India-only ceiling is **₹1.2–3 Cr ARR if you win 50% of ICP**. Call it **₹1.5 Cr ARR sustainable / ₹3 Cr stretch**. **Geo-expansion is structurally required, not optional**, if the founder targets a Series A.

---

## Timing Assessment

**Verdict: Optimal 12–18 month window.** [Synthesized from A1, A2, B1, B2, D1.]

| Signal | Direction | Source |
|---|---|---|
| Demand-side AI behavior already mainstream | Pro | 75% Indian students pre-screen with AI [Leap Scholar Beyond Borders 2025] |
| Counselor-side tooling adoption still early | Pro | No counselor-side AI adoption survey exists; estimated <20% for actual discovery work [C1, B2 inference] |
| Outbound volume intact at 1.254M despite 5.7% dip | Pro | MEA via ICEF Dec 2025 |
| Investor appetite for study-abroad sub-segment is strongest pocket within cooled edtech | Pro | Inc42 — Leap $55M, Leverage profitable, Manifest Global, Univalley.ai |
| Germany growth + Australia complexity creates 2 distinct counselor pain points | Pro | DAAD Sept 2025; AU EL3 Jan 2026 reclassification |
| DPDP compliance window forces tooling decisions H2 2026 → May 2027 | Pro | MeitY DPDP Rules Nov 2025 |
| Meritto Mio AI suite is **6–12 months** from a discovery-PDF bolt-on | **Con** | B2 inference from Meritto product pages + Mio AI marketing |
| SmartX 12–18 months behind Meritto | Con | B2 inference from SmartX product trajectory |
| Cialfo/Manifest India motion (Kaaiser investment) 18–24 months out | Con | PR Newswire, The PIE News 2025–26 |
| Yocket/Leap could pivot to B2B counselor tooling if B2C unit economics worsen | Con (12–24mo) | B1, B2 inference |

**Tailwinds outweigh headwinds, but the window is short.** The single biggest closing-the-gap risk is **Meritto** (12-month threat). The strategic implication is to ship vertical depth on Germany + Australia data and DPDP-compliant workflow *before* Meritto adds a discovery module — and to position from day 1 as "integrates with your Meritto/SmartX CRM," not "replaces it," to make the eventual Meritto threat a partnership conversation, not a head-to-head one.

### A reconciled contradiction

`market-size.md` (A1) said *"ramen profitability for two founders but not enough to support a venture-scale outcome."* `trends.md` (A2) said *"the wind is at your back, but the runway isn't infinite — 12–18 months."* These look contradictory but resolve cleanly:

- **A1 is correct on the structural ceiling** (India-only ARR caps at ~₹1.5 Cr; not venture-fundable at Series A as a single-country play).
- **A2 is correct on the entry window** (the wedge is open *now* and closes when Meritto ships).
- **The synthesis:** This is a real and addressable market for a side-project / bootstrapped / seed-funded team, with the explicit plan that Nepal expansion (Month 13–15) is what moves the company to Series-A scale. The founders should size their ambition accordingly.

---

## Strategic Implications

1. **Treat the 15–25 strictly-qualified primary segment as the entire Year-1 mission, not as a starting point.** Year-1 SOM of 25 paid customers is effectively majority capture. Build, sell, and ship with that constraint as the planning anchor — not the larger 1,500–2,500 mid-size pool that A1 referenced.

2. **Ship vertical depth before Meritto does.** Germany eligibility logic (APS, blocked account, Studienkolleg, uni-assist, IELTS waivers, TU9 matrix) and Australia complexity (GTE, EL3, CoE strategy, post-study work rights) are the moats. Generalist CRMs will not staff teams to build this — that is the asymmetric advantage. See `competitor-landscape.md` for the threat-by-threat ranking.

3. **DPDP is the wedge, not the burden.** Lead the GTM with "DPDP compliance for Indian agencies" content (D1's recommended whitepaper play). DPDP-ready data residency + verifiable parental consent + India-residency hosting are differentiated *now*, and table stakes in 12 months. Be early.

4. **Geo-expansion is non-negotiable.** Plan Nepal Month 13–15 from day one. India-only the company tops out at fundable-seed scale (₹1.5 Cr ARR). Without an explicit second-country motion, the company has no Series-A story.

5. **Position the destination-mix asymmetry, don't apologize for it.** Australia's headline decline is not a bug for this product — EL3 + 8-week processing + GTE statements *increases* per-student counselor workload, which is the work the tool supports. Frame "complexity helps the counselor charge more" rather than ducking the Australia headline.

---

## Data Gaps

1. **No clean public count of Indian study-abroad agencies.** Best proxy remains AAERI (92) + AIRC (17–25) + non-association tail (D2). The full 10,000–15,000 long-tail figure is triangulated, not measured. **Recommended primary research:** scrape Just Dial / Google Maps for "study abroad consultant" listings per city for empirical count.
2. **No India-specific Year-1 ARR benchmark for SMB B2B SaaS in the education vertical.** Global proxies adjusted 40–60% per upGrowth heuristic.
3. **No published "discovery tool" or "counseling-assist" tooling category data.** This is a category-creation product. Validate budget tolerance in first 5 design-partner conversations.
4. **No public count of "agencies that focus on Germany+Australia specifically."** C3 estimates 10–15% of mid-size segment (the 15–25 strictly-qualified primary). Founder-led mapping pass over the 92 AAERI websites would close this gap in 4–6 hours.
5. **Per-agency tooling-spend** is fully an estimate — no published "% of opex spent on software" figure for Indian education consultancies.
6. **Punjab India state-level statute text** — search returned a polluted set (Punjab-Pakistan Act 2025, sub-municipal travel-agent licenses). Need to pull actual notification PDF from Punjab India government gazette.

---

## Flags

**Red Flags:**
- The strictly-qualified primary segment is **only 15–25 agencies**. Year-1 SOM requires majority capture. If pilot conversion under-performs, there is *not* a wider segment to fall back on for Year 1.
- **Indian outbound turned negative in 2025 (-5.7%)** — the easy-growth narrative is over. Forecasts from RedSeer/etc. predating this dip are now suspect.
- **Australia's 48% visa-approval drop** + EL3 reclassification compresses one half of the beachhead. Net is manageable (more work per student is tool-positive) but headline is hostile.
- **Meritto Mio AI is 6–12 months from a discovery-PDF bolt-on.** This is the single biggest strategic-timing risk.
- **India-only the business tops out at ~₹1.5 Cr ARR sustainable.** Without explicit Nepal/Bangladesh expansion plan, there is no Series-A story.

**Yellow Flags:**
- **DPDP compliance cost** (₹4–8L + 6–10 dev-weeks Year 1) is real and front-loaded — a 2-SDE team has to take it seriously before Q3 2026.
- **Indian SMB churn** at 40–50% annual is brutal; first-90-days share of churn is 43%. Onboarding quality is the highest-leverage retention investment from day 1.
- **Punjab state regulation** could change overnight (history of mid-year notifications); both risk and opportunity.
- **Cialfo's Kaaiser investment** signals India intent at 18–24 months out — second-wave threat after Meritto.
- **Generalist LLMs (ChatGPT) close some workflow gaps for free** — the moat must come from verified data, branded delivery, DPDP compliance, and India-context (APS, blocked account, etc.), not from raw LLM output. See `competitor-landscape.md` ChatGPT-as-incumbent section.

## Sources (tiered)

**Tier 1 (govt / official statistics):**
- MEA India via ICEF Monitor (Dec 2025) — Indian outbound totals, destination counts
- DAAD India (Sept 2025) — Germany Indian-student enrollment, English-program counts, partnership data
- Australian DHA / Simplified Student Visa Framework — Australia caps, EL3 reclassification (Jan 2026)
- AAERI Members List (`aaeri.org.in/members-list`) — 92 named member agencies, 6-region breakdown
- AIRC Certified Agencies (India HQ) — 17–25 named agencies
- MeitY DPDP Rules notification (Nov 13, 2025)
- RedSeer Strategy Consultants — market value $38B→$58B, CAGR commentary

**Tier 2 (industry press / analyst):**
- ICEF Monitor (2025–26) — multi-source destination shifts, agent regime coverage
- The PIE News (2025–26) — AAERI coverage, Manifest Global acquisition
- University World News (Dec 2025) — Indian outbound decline confirmation
- Business Standard / The Federal (2025) — Australia visa caps, EL3 reclassification
- Inc42 Annual Indian Startup Trends Report 2025 — edtech funding totals, sector recovery
- TechCrunch India (Oct 2025) — Leverage Edu strategy, Univalley.ai launch
- upGrowth (2026) — Indian B2B SaaS CAC/ACV/LTV benchmarks
- Leap Scholar Beyond Borders report 2025 (via Careers360) — 75% student AI adoption

**Tier 3 (vendor / blog — used with caution):**
- SmartX CRM pricing pages (vendor self-report) — competitor pricing anchor
- Meritto / Cialfo / BridgeU vendor pages — feature & positioning
- Verified Market Reports — global agency-market value
- AbroBot, studyandworkabroad.in, Wikati Education — color/narrative

**Internal cross-references:** `competitor-landscape.md`, `target-audience.md`, `industry-trends.md`, `confidence-dashboard.md`, plus raw files in `01-discovery/raw/`.
