# Intake Brief — Study-Abroad Counselor Copilot

**Phase:** 1 — Intake (re-run after pivot)
**Project:** career-discovery-platform *(directory name retained from pre-pivot iteration; product is no longer general career discovery — see Pivot Notes)*
**Date:** 2026-05-13
**Confidence:** Medium-High on idea shape (informed by founder's counselor conversations); Low-Medium on willingness-to-pay and competitive intensity (deferred to Phase 3).

---

## The Idea (one paragraph)

A **B2B AI tool for India-based study-abroad counselors and mid-size agencies** that automates the 2–3 hour "discovery session" a head counselor currently runs personally with each student-and-parent pair. The counselor inputs the student's profile and context; the tool generates a take-home **PDF report** covering: eligibility filtering, country fit (with situation-aware recommendation), country pros/cons, college-type options, tuition + living costs, visa restrictions and timelines, a realistic admit-path strategy, and a closing section that **explains the counselor's own service package and how it adds value to the journey from here**. The product replaces the *entirety* of the head counselor's discovery work, freeing them to focus on application execution, visa, and closing. Beachhead destinations: **Germany + Australia**. Source market: **India only** at launch.

## What It Is NOT

- Not direct-to-consumer (parents/students do not buy the tool — counselors do)
- Not a general career-discovery or "what should I do with my life" tool *(this is the pre-pivot product, now retired)*
- Not US/UK/Canada at launch — Germany + Australia only
- Not a CRM, not a visa-filing tool, not an application-management platform — it stops at the report and the counselor handoff
- Not a tool the family operates themselves; it is run by the counselor

## Core Differentiator (intended)

**Compresses a head counselor's 2–3 hour discovery session into a structured PDF the counselor can ship in minutes, while reinforcing (not undermining) the counselor's role.** The "explains the counselor's package" section inside the report is the load-bearing UX choice: it converts the AI's output into a sales asset *for* the counselor instead of a substitute for them. [Assumption — needs to be validated against actual counselor behavior in Phase 3 and design partner work; counselors might resent any tool that produces a polished take-home that the family could shop around.]

## Target Customer

- **Buyer:** Head counselor or owner of a study-abroad consultancy / mid-size agency in India.
- **Operator:** The same head counselor (or a junior they trust the tool with).
- **End beneficiary:** The Indian student (typically 17–22) and their parents who receive the PDF.
- **Geography:** India outbound only at launch. Destinations narrowed to **Germany + Australia**, chosen because:
  - Germany: near-free public universities → strong ROI story for Indian middle-class parents; under-served by current Indian counselor tooling (which is US/UK-heavy).
  - Australia: second-largest destination for Indian outbound students after the US; well-understood visa regime; agencies already exist at scale.

## Founder & Team (unchanged from pre-pivot)

- **Founders:** 2 software engineers, side-project capacity (full-time jobs alongside).
- **Domain expertise:** None in study-abroad counseling, edtech, or B2B agency sales. Founder is "social, can do sales" but no formal sales experience.
- **Existing assets:** Counselor conversations (informal, exploratory) — no prototype, no waitlist, no signed LOIs, no design partners, no advisors.
- **Founder-market fit:** **Weak.** Path to strengthen: recruit one mid-size agency owner as a design partner with weekly time committed before any meaningful build investment. Mid-size agency owners in Delhi / Mumbai / Bangalore / Hyderabad are findable on LinkedIn; this is a tractable ask.

## Business Model (intent)

- **B2B SaaS, metered subscription.** Pricing intuition is **tiered by number of report generations per month** (i.e., per-student-served). Rationale: aligns price with value (each report = one student lifecycle worth ~₹50k–₹2L in counselor fees), easy to start small for solo consultants, easy to upsell mid-size agencies.
- **Pricing point: undefined.** [Open question — Phase 7 must benchmark against actual agency revenue per student and willingness-to-pay.]
- **Revenue model:** subscription only. No transaction-take on counselor fees, no commission from universities, no parent-side monetization at launch.

## Tech & Constraints

- **Form factor:** Web app for the counselor; PDF output for the family.
- **LLM choice:** Undecided.
- **Privacy / compliance:** **Materially simpler than pre-pivot.** Counselor is the user, counselors are adult professionals — no minor-consent, COPPA, FERPA, or DPDP-for-minors load. The student PII passes through the system but never has a direct user account, which simplifies auth and consent UX. India DPDP for adults still applies; standard SaaS posture is sufficient at the build-1 stage. [To revisit in Phase 6.]

## Customer Conversations (so far)

- Founder has spoken with some India-based study-abroad counselors. Pain confirmed: head counselor personally absorbs 2–3 hours per student-parent discovery session and cannot delegate it because the conversation is consultative and context-sensitive.
- Counselor reaction to the idea: **"Excited but not serious until it's functional."** [Yellow Flag — this is the standard polite-curiosity tell. Real validation = pre-payment, signed LOI, or design-partner agreement with weekly time committed. None of those exist yet.]

## Hard-Question Answers (revised post-pivot, verbatim where possible)

| Question | Founder's answer | Honest read |
|---|---|---|
| Why you, specifically? Unfair advantage? | (Unchanged from pre-pivot — "tech edge, none yet.") | Founder-market fit still must be deliberately constructed via design partner. The pivot does not fix this. |
| Well-funded competitor launches tomorrow — your move? | (Unchanged — early mover, success stories, domain advisor.) | Stronger here than pre-pivot: agency-tool space is much less crowded than school edtech, especially in Germany/Australia counseling. But Leverage Edu, IDP, ApplyBoard, Y-Axis, etc. have internal counselor stacks they could open up — platform-risk is real. |
| Strongest argument *against* the idea? | The "AI slop" objection is **less fatal here**: country/college research is a structured information problem, not a life-purpose problem. The new strongest objection: **"once the family has the PDF, why do they need the counselor?"** | This is the central design tension — the report must be a sales asset for the counselor, not a replacement. Yellow Flag on positioning. |
| Have you talked to potential customers? | Yes — some India-based counselors. Reaction: excited but uncommitted. | Material improvement over pre-pivot (was zero). Still soft validation. Phase 3 customer-voice work + design-partner recruitment is the next milestone. |
| What would make you walk away? | (Unchanged — "if no innovation / user harm.") | Concrete kill criteria deferred to Phase 8. Easier here than pre-pivot: counselor B2B revenue is measurable (renewal rate, paid pilot conversion), so kill criteria can be quantitative. |

## Realistic Timeline (reset after pivot)

- **Month 1:** Recruit 1 design-partner agency. Build pivot's first prototype against their actual student pipeline.
- **Months 2–3:** Working prototype generating real reports for the design partner's live students. Iterate on report content with weekly counselor feedback.
- **Months 4–6:** Paid pilot with the design partner + 2–3 more agencies. First revenue.
- **Months 7–12:** 10–15 paying agencies on the platform; revenue model and pricing validated; expansion case for adding a third destination (UK or Canada) evaluated.

The compression vs. pre-pivot timeline (which had "1 paid pilot by month 12") reflects the much shorter sales cycle of mid-size Indian agencies vs. K-12 schools.

## Success Metrics (to firm up in Phase 7)

- **6-month goal:** 1 design partner running real student reports + 2–3 paid pilots.
- **12-month goal:** 10–15 paying agencies; clear retention signal (renewals or expansions on tier).
- **3-year goal:** TBD in Phase 7.

## Open Questions Carried into Research (Phase 3)

1. **Agency willingness-to-pay**: what does a mid-size Indian study-abroad agency actually spend on internal tooling today? Per-counselor seat cost? Per-student-serviced cost? — anchors pricing.
2. **Competitive landscape**: ApplyBoard agency tools, Leverage Edu's internal stack, BridgeU, Cialfo, Edvoy, Univariety counselor-side. Who serves Indian agencies specifically vs. global counselor SaaS?
3. **Counselor "ChatGPT today" baseline**: how many Indian agency counselors are already running this discovery session through ChatGPT / Claude with copy-paste prompts? That is the zero-cost incumbent.
4. **Indian outbound student volume to Germany + Australia**: actual numbers, growth rates, agency-served share. Anchors TAM.
5. **PDF report = sales asset or disintermediation risk?** What does counselor behavior data say about how families currently shop counselors?
6. **Visa-policy data freshness**: country visa rules change frequently. How does the tool source and update visa info — manual curation, web scrape, partnership?

## Pivot Notes (2026-05-13)

Founder pivoted from a **broad "AI career discovery for all 16–18 year-olds, sold to schools"** concept to **"counselor copilot for Indian study-abroad agencies focused on Germany + Australia."**

Drivers of the pivot:
- Founder did customer development with study-abroad counselors (which the pre-pivot version had not done with anyone) and surfaced a concrete, repeatable, time-quantified pain (2–3 hours per discovery session, personally absorbed by the head counselor).
- The "unknown unknowns" / serendipitous-discovery thesis from pre-pivot has been **dropped entirely**. The new product is straightforward research-and-shortlist with structured outputs.
- Buyer changed from schools (long sales cycles, no domain access) → study-abroad agencies (shorter cycles, founder has nascent access).
- Compliance load dropped — adult users only.

Materially downgraded red flags from pre-pivot:
- ✓ "Zero customer conversations" — now: at least informal counselor conversations.
- ✓ "Under-18 compliance load" — now: adult B2B users only.
- ✓ "B2B school sales as a side project" — now: B2B agency sales, weeks-to-months cycle.

Unchanged red flag from pre-pivot:
- ✗ Founder-market fit still weak. Mid-size agency design partner is the single most valuable action.

Old brief preserved at `00-intake/brief.pre-pivot.md`. Old brainstorm preserved at `00-intake/brainstorm.pre-pivot.md`.

---

## Flags

**Red Flags:**
- **No design-partner agency yet.** Counselor "excitement" is not validation. Without one agency committed to weekly time and a paid pilot, the product spec is guesswork dressed as confidence.
- **Founder-market fit still weak.** Same 2-SDE side-project team, no edu/counseling domain background. Materially the same risk as pre-pivot; the pivot does not address it.

**Yellow Flags:**
- **Disintermediation tension.** The PDF report is so close to what the family currently pays the counselor for that "the counselor's package" section is doing a lot of load-bearing work. If that section is weak, the tool may accelerate counselor churn rather than augment it.
- **Visa / cost / admission data freshness.** Two destination countries' rules change every cycle; mistakes in the PDF directly damage the counselor's reputation with their client. This is an operational risk, not just a content risk.
- **Platform risk from large agency-platforms.** Leverage Edu, IDP, ApplyBoard, AECC each have internal counselor stacks. Any could open a similar feature to their network and zero-out the standalone tool. Mitigation = build deep loyalty with mid-size independents who would not switch to a single-vendor platform.
- **Soft validation signal.** "Excited but not serious until functional" needs to be converted into a written commitment (design-partner agreement) before serious build.

## Sources

- Founder intake interview round 1 (2026-04-26) — pre-pivot scope.
- Founder pivot conversation (2026-05-13) — current scope.
- Founder's informal counselor conversations (timing unspecified; verbatim quotes not captured) — primary source for the 2–3hr pain estimate.
- All market sizing, competitor positioning, agency willingness-to-pay claims above are flagged as **[Open Question]** and will be sourced in Phase 3.
