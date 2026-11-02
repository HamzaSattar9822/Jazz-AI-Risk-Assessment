# JazzWorld AIRA Risk Scoring & Tiers (One-Pager)

**Methodology:** AIRA-DDA-1.0 · Official scores are calculated by fixed rules — not by the AI chatbot.  
**What decides approval:** **Residual risk** only. Inherent risk is shown for context.

---

## How the score is calculated

Reviewers score each factor from **1 (best / lowest risk) to 5 (worst / highest risk)**. Screening answers (sensitive data? decisions? actions?) change how much weight each area gets.

| Step | What is measured | Result |
| --- | --- | --- |
| **1. Impact** | Three groups: **Business**, **People & Data**, and **AI** factors (each 1–5). Group averages are combined with screening-based weights. | **Impact score** (scale 3–15) |
| **2. Inherent likelihood** | **Occurrence** (how often / how exposed) + **Feasibility** (how easy to cause harm or misuse), each 1–5, then averaged and scaled. | **Inherent likelihood** (scale 3–15) |
| **3. Controls** | Strength of preventive, detective, oversight, governance, and validation controls (1–5). Converted to a multiplier: `0.5 + 0.1 × control strength`. | **Control multiplier** |
| **4. Residual likelihood** | Inherent likelihood × control multiplier (floored at 3). Stronger controls reduce likelihood; weak controls leave more residual chance. | **Residual likelihood** |
| **5. Risk scores (0–100)** | `Risk = round( (Impact × Likelihood) / 225 × 100 )`, clamped to 1–100. | **Inherent risk** uses inherent likelihood; **Residual risk** uses residual likelihood |

**In plain terms:** How bad would it be if something went wrong (**impact**), how likely is that without relying on controls (**inherent**), and how much do existing controls bring that likelihood down (**residual**). The residual number sets the tier.

---

## Residual risk tiers (what they mean)

| Residual score | Tier | Severity | Who must approve | What it typically requires |
| --- | --- | --- | --- | --- |
| **1–25** | **Tier 1** | Low | Self-review | Baseline controls, clear owner, keep the assessment, routine monitoring |
| **26–59** | **Tier 2** | Medium | Line Manager (L4 / L3) | Documented mitigation for material gaps, owner, target date; specialist review if triggered |
| **60–79** | **Tier 3** | High | Head of Department / Function (L5) | Formal treatment plan, specialist review, enhanced controls, residual risk reassessed, **RAIO** governance review |
| **80–100** | **Tier 4** | Critical | C-Suite (L6) | Formal treatment plan, mandatory RAIO + specialist review, material risk reduction expected, residual risk reassessed, **explicit senior acceptance** |

---

## Quick notes for requesters & reviewers

- The chatbot helps **collect** answers; it does **not** invent the official residual score or tier.
- Fill screening honestly — it changes weights (e.g. sensitive data raises People & Data emphasis).
- **Accept / Reduce / Transfer / Avoid** treatment options apply within the authority of the residual tier.
- Higher tier = stricter approval and more evidence before go-live.

*Source: JazzWorld AIRA-DDA-1.0 engine (`backend/app/methodology`).*
