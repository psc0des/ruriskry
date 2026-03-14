# RuriSkry Demo Video — Final Script

**Runtime: 1:55**
**Voice: Your own narrative, generated via ElevenLabs or Azure AI Speech**
**Pace: Calm, confident, conversational — like explaining to a colleague, not presenting to a board**

---

## PRE-RECORDING CHECKLIST

Before you start screen recording:
- [ ] Browser: Edge or Chrome, full-screen, bookmarks bar hidden, zoom 110%
- [ ] Dashboard loaded: `https://polite-mud-0fe04b810.6.azurestaticapps.net`
- [ ] Slack open in a separate browser tab (the `#ruriskry-alerts` channel)
- [ ] Have a completed scan in history (so Decisions page has data)
- [ ] Have at least one execution record (APPROVED with plan visible)
- [ ] Screen recorder ready: OBS or Win+G (1920x1080)

---

## THE SCRIPT

### Section 1 — The Why (0:00 – 0:25)
**~70 words | Pace: deliberate, personal**

**SCREEN:** Start on the architecture diagram (full screen, clean background). Hold for 3 seconds, then slow zoom or pan across it.

> I've been a Cloud Engineer and SRE for eight years. In every organisation I've worked in, production changes go through a CAB — a Change Advisory Board. Every infrastructure change needs a four-eyes review. Someone senior signs off before anything touches production. That's the standard. But when AI agents start managing infrastructure — who reviews them? Sure, there are guardrails — token limits, permission scopes, hardcoded rules. But guardrails only say what an agent can't do. Nobody's simulating what happens if it does. Nobody's scoring the blast radius before the action runs.

**SCREEN NOTE:** Keep the architecture diagram visible the entire time. No clicks. Let the voiceover carry this section.

---

### Section 2 — What We Built (0:25 – 0:42)
**~50 words | Pace: slightly faster, building energy**

**SCREEN:** Cut to the Overview dashboard. Let the NumberTicker animations play (they animate on page load — make sure you navigate to the page fresh so the count-up is visible). Mouse slowly over the SRI trend chart. Show the execution metrics card and alerts activity card.

> That's why I built RuriSkry. It's a CAB for AI. Before any agent action touches Azure — whether it's deleting a resource, modifying a firewall rule, or restarting a service — it goes through four governance agents that produce a Skry Risk Index. Infrastructure blast radius. Policy compliance. Historical patterns. Financial impact. One composite score. One verdict.

**SCREEN NOTE:** Don't click anything. Just let the Overview breathe. Viewers need to absorb the dashboard quality.

---

### Section 3 — Live Scan (0:42 – 1:07)
**~55 words | Pace: steady, narrating what's happening on screen**

**SCREEN:**
- 0:42 — Navigate to the **Agents** page. Pause 2 seconds to show the agent cards.
- 0:46 — Click **"Run Scan"** on the Deploy Agent card. Card turns amber.
- 0:49 — Click **"Live Log"** button that appears. The SSE log panel slides in from the right.
- 0:51–1:07 — Let the live stream run. Events flow in real-time: discovery, analysis, reasoning, proposals, evaluations, verdicts. Don't touch anything — let it stream.

> Let me show you a live scan. The Deploy Agent is now auditing nine security domains across our Azure environment — NSG rules, storage, database config, Key Vault, Defender for Cloud assessments, Azure Policy compliance. Every finding streams live. Hardcoded rules catch the obvious. Microsoft APIs act as a safety net. And the LLM reasons over anything the deterministic layers missed. Three layers. No blind spots.

**SCREEN NOTE:** The streaming log is visually impressive — let it run for at least 15 seconds. Don't rush past it.

---

### Section 4 — Governance Verdict (1:07 – 1:24)
**~40 words | Pace: measured, explanatory**

**SCREEN:**
- 1:07 — Navigate to the **Decisions** page. Show the table of verdicts with colour-coded badges.
- 1:10 — Click on a **DENIED** row. The Evaluation Drilldown opens.
- 1:12 — Scroll slowly through: SRI dimensional bars, decision explanation, counterfactual analysis.
- 1:20 — Pause on the counterfactual section ("what would change this outcome?").

> Every verdict is fully explainable — just like a CAB decision has documented rationale. Four risk dimensions, a plain-English explanation from the LLM, and counterfactual analysis — what would need to change to flip this denial into an approval. No black boxes. Full auditability.

**SCREEN NOTE:** Zoom in (Ctrl+Plus) on the counterfactual section so viewers can read the score transitions.

---

### Section 5 — Execution (1:24 – 1:40)
**~35 words | Pace: confident, showing the payoff**

**SCREEN:**
- 1:24 — Show an APPROVED verdict's **Execution Status** panel. Show the structured plan table — operation, target, reason.
- 1:30 — Scroll down to show the **impact warning** and **rollback instructions**.
- 1:34 — Show the **live execution terminal** with timestamped steps streaming in.

> When the CAB approves, execution is still controlled. The LLM generates a step-by-step remediation plan. The human reviews it. Then it executes live — with a pre-computed rollback for every step. If anything goes wrong, one click reverses everything.

**SCREEN NOTE:** Make sure the execution terminal has the "Running..." badge visible. The green cursor blinking at the bottom is a nice visual.

---

### Section 6 — Slack (1:40 – 1:50)
**~30 words | Pace: quick, punchy**

**SCREEN:**
- 1:40 — Switch to the **Slack** browser tab showing `#ruriskry-alerts`.
- 1:41 — Scroll slowly through the messages. Show: a DENIED verdict notification, an Azure Monitor alert, an ESCALATED governance alert with the SRI badges, and an "Alert Investigated" resolution.
- 1:48 — Pause on a **"View in Dashboard"** button.

> And your team doesn't need to watch the dashboard. Every denied verdict, every escalated risk, every Azure Monitor alert — pushed to Slack in real-time with the full SRI breakdown and a direct link back to the dashboard.

**SCREEN NOTE:** Scroll at a steady pace. The Slack messages are visually rich — let viewers see the SRI badges and colour-coded sections.

---

### Section 7 — Close (1:50 – 2:00)
**~25 words | Pace: slow, deliberate, land the tagline**

**SCREEN:** Cut back to the **Overview** dashboard. Hold for 2 seconds. Then fade or cut to the architecture diagram or a clean title card: "RuriSkry — AI Action Governance Engine".

> Production changes have always needed a Change Advisory Board. Now, AI agents have one too. RuriSkry — built for Azure, built on Azure.

**SCREEN NOTE:** Let the last line land. Hold the final frame for 2-3 seconds of silence before the video ends.

---

## RECORDING PLAN

Record these **7 clips separately** (easier to re-do individual sections):

| Time | Where to be | What to do |
|------|------------|------------|
| 0:00–0:25 | Architecture diagram (browser tab, full screen) | Just hold. Let voiceover carry. |
| 0:25–0:42 | Overview dashboard (fresh load) | Let NumberTickers animate. Hover SRI chart. |
| 0:42–1:07 | Agents page | Run Scan → Live Log → let SSE stream ~15s |
| 1:07–1:24 | Decisions page | Click DENIED row → scroll drilldown slowly |
| 1:24–1:40 | Execution status panel | Show plan table → impact → terminal |
| 1:40–1:50 | Slack tab (`#ruriskry-alerts`) | Scroll through messages slowly |
| 1:50–2:00 | Back to Overview | Hold. Let tagline land. |

**Total: 2:00**

## VOICEOVER PLAN

1. Paste each section's script into ElevenLabs (or Azure AI Speech)
2. Generate each section separately — this lets you adjust pacing per section
3. Recommended ElevenLabs voices: **"Adam"** (calm, professional) or **"Daniel"** (British, authoritative)
4. Download as MP3

## EDITING (Clipchamp — built into Windows 11)

1. Open Clipchamp (search in Start menu)
2. Import all 7 screen recordings + 7 audio clips
3. Place on timeline: video track on top, audio track below
4. Align voiceover start to each clip — trim video if too long, add 0.5s cross-dissolve between clips
5. No background music needed — the voiceover + app visuals are strong enough
6. Export at 1080p
7. Upload to YouTube (Unlisted or Public)

## COPYRIGHT SAFETY

- Screen recordings of your own app = safe
- AI voice from ElevenLabs/Azure = you own the output, safe
- Architecture diagram is yours = safe
- Slack screenshots of your own channel = safe
- No third-party logos, music, or copyrighted material used
- If you want subtle background music: YouTube Audio Library (free, pre-cleared for YouTube)
