# Should I Start Building the Product?

**Date:** 2026-05-25
**Context:** Captured at the close of Phase 3 (Research) and Phase 3.5 (Research Gate). Founder asked whether the next step is to start building the product. Short answer: **no, not yet** — for the reasons below.

Related documents:
- [../01-discovery/research-gate.md](../01-discovery/research-gate.md) — the YELLOW-Conditional-Green verdict
- [../01-discovery/customer-discovery-plan.md](../01-discovery/customer-discovery-plan.md) — the 30-day playbook this document refers to
- [../PROGRESS.md](../PROGRESS.md) — full project state

---

## Short answer

**No.** Don't start building the product yet. That's the wrong instinct here, even though it's the natural one for two SDEs.

---

## Why building now is the wrong move

You have **zero design partners**, an **unvalidated core pain hypothesis** (the 2–3hr discovery-session claim was just refuted by independent customer voice in Phase 3), and an **unknown counselor-side ChatGPT adoption rate**. Three of the most expensive product decisions — what features the MVP includes, what the PDF actually looks like, what data sources you integrate first — all depend on answers you do not have yet.

If you spend the next 8–12 weeks building the MVP, here is the realistic outcome:

- You ship a tool optimized for *"save the counselor 2 hours"* (the founder hypothesis), then discover in week 13 that counselors care about **trust-restoration first and time-saving third** → you rebuild PDF templates and reposition messaging.
- You build APS / blocked-account / uni-assist Germany flow before talking to a single Germany-focused counselor → you discover they actually wanted Australia EL3 documentation depth first → you wasted 3 weeks on the wrong vertical depth.
- You build a counselor-facing web app, then the first counselor you demo to says *"we use Meritto, can it just plug in there?"* → architectural rework.
- Meritto ships Mio AI discovery-PDF in month 8. You are still pre-first-paying-customer. The window closes.

**You are a 2-SDE side-project team.** You have approximately **520 hours of focused work over the next 6 months** (10 hrs × 2 founders × 26 weeks). Spending 200–300 of those hours building the wrong thing is the single biggest risk to this project. Not Meritto. Not ChatGPT. **The wrong build.**

---

## What you should do this week, specifically

### Monday – Tuesday (4–6 hrs)
1. Subscribe to LinkedIn Sales Navigator (~₹8,200/mo).
2. Walk the AAERI directory (`aaeri.org.in/members-list`). Capture every agency into a Google Sheet. **Reconcile the 92-vs-117 arithmetic** — this closes Research Gate Condition #5 and takes ~4 hours.

### Wednesday (2–3 hrs)
3. Do the same for AIRC India (`airc-education.org`).
4. Apply the **first-30 filter** (NW India + Delhi + Chandigarh, G+A focus, owner on LinkedIn last 90 days, 6–50 employees, not a franchise sub-agent). End Wednesday with a tight list of 30 named outreach targets.

### Thursday (2–3 hrs)
5. Write your first LinkedIn post. Use the *"Germany +15.1%, Australia EL3 complexity"* template from [../01-discovery/customer-discovery-plan.md](../01-discovery/customer-discovery-plan.md).
6. Send your first 30 LinkedIn connection requests. **No pitch in the note** — just *"researching how Indian agencies handle student discovery, would value connecting."*

### Friday
7. Track who accepted. Plan Week 2's DM batch.

**That is the whole first week. No code.**

---

## What you CAN build right now that actually helps (≤ 2 weeks)

There are exactly two engineering tasks worth doing right now. Both serve customer discovery, not product launch.

### 1. A simple landing page (3–4 days for a 2-SDE team)

- Single page.
- Headline: *"DPDP-compliant discovery reports for Indian study-abroad agencies, focused on Germany + Australia."*
- Sub-headline: *"In 30-day pilot with select AAERI member agencies."*
- Email-capture form.
- A "what's coming" section that names the **trust-artifact framing** in plain English.
- No login, no app — just a credibility surface.

**Why this helps:** Every LinkedIn DM you send, the counselor will Google you. Right now they find nothing. With a landing page, they find a coherent project they can take seriously. **Conversion rate on cold outreach roughly doubles when the recipient can verify you exist.**

### 2. ONE mock PDF report (1 week)

- Pick a fictional or composite student profile.
- Manually generate the kind of PDF you envision — Germany country recommendation, 3 college options with admit-path, costs, visa, "counselor's package" section.
- Use ChatGPT + your own writing + DAAD-sourced data.
- Do NOT write any backend logic. Produce **one beautiful 8–12 page PDF as a static artifact.**

**Why this helps:** When you do counselor interviews (Week 2 of the plan), you have something concrete to put on the table at minute 35 of the conversation: *"Something like this — would this help your agency?"* Reactions to a real PDF are **10× more informative than reactions to a verbal description.** This is the single highest-ROI engineering work you can do in the next month.

### What NOT to build yet

- The LLM pipeline / prompt engineering work
- User auth, accounts, agency dashboards
- DPDP consent infrastructure
- Multi-PDF generation, templates, branding system
- Stripe / billing / subscription
- Integrations with Meritto or SmartX
- Anything else

All of those wait until you have one design partner. The design partner tells you what they need; you build it for them; if they pay at the end of the pilot, you have a starting point for a real MVP.

---

## The reframe

Think of the next 30 days as a **customer-development sprint with a tiny amount of engineering in service of it.** The deliverables at day 30 are not "an MVP." They are:

- ✅ A **signed design partner** (1, ideally 2–3)
- ✅ A **validated story** (trust-artifact framing confirmed, or refuted with a new framing)
- ✅ A **reconciled cold-list** (the real AAERI count + first-30 outreach sheet)
- ✅ **30+ ChatGPT-adoption survey responses**
- ✅ A **landing page** that lives at a real domain
- ✅ A **mock PDF** you can put in front of any counselor

That is the package that justifies building. Not the other way around.

---

## TL;DR

> **Don't start building the product.** Start the customer-discovery plan in [../01-discovery/customer-discovery-plan.md](../01-discovery/customer-discovery-plan.md). The only code worth writing in the next 2 weeks: a **landing page** and **one beautiful mock PDF.** Everything else is premature optimization on a product spec you don't have yet.
>
> Come back in 30 days with the validation data. **Then we build.**
