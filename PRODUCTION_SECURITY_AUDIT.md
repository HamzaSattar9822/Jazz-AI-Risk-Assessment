# JazzWorld AIRA — Production Readiness, Scalability & Security Assessment

**Document type:** Deployment verification + scalability + safety / security assessment  
**Date:** 5 November 2026  
**System:** JazzWorld AI Risk Assessment (AIRA)  
**Environment:** OpenShift project `ai-risk` on `ocpv2.jazz.com.pk`  
**Live URL:** `https://jazz-ai-risk-assessment-ai-risk.apps.ocpv2.jazz.com.pk/`  
**Methodology version:** AIRA-DDA-1.0  
**Scope:** Live cluster health, OpenShift manifests, FastAPI backend, portal packaging, LLM integration, authz, and operational limits  
**Classification:** Internal — suitable as source material for a formal readiness / security pack  

**Overall judgement**

| Dimension | Rating | Summary |
| --- | --- | --- |
| Production deploy health | **Good** | Live, healthy, serving latest portal |
| Functional safety (risk process) | **Strong foundation** | Deterministic scoring; LLM cannot set official risk |
| Application security | **Pilot-grade** | Hardened demo; Critical/High items before full go-live |
| Scalability / HA | **Limited by design today** | Single replica + SQLite; fine for pilot, not multi-AZ scale |

---

## Table of contents

1. [Executive summary](#1-executive-summary)  
2. [Production deployment check](#2-production-deployment-check)  
3. [System architecture](#3-system-architecture)  
4. [How safe is the system](#4-how-safe-is-the-system)  
5. [How scalable is the system](#5-how-scalable-is-the-system)  
6. [Security audit findings](#6-security-audit-findings)  
7. [AuthZ matrix](#7-authz-matrix)  
8. [External dependency — Jazz Gemma](#8-external-dependency--jazz-gemma)  
9. [ServiceNow integration posture](#9-servicenow-integration-posture)  
10. [Capacity & scaling roadmap](#10-capacity--scaling-roadmap)  
11. [Go-live readiness checklist](#11-go-live-readiness-checklist)  
12. [Conclusion for document owners](#12-conclusion-for-document-owners)  

---

## 1. Executive summary

JazzWorld AIRA is deployed and operating on OpenShift. The latest intake portal (`AIMS_final.html`), backend intake safeguards, and risk framework JSON are live. Health checks pass, Jazz Gemma on AIOps is reachable for drafting intake fields, and outbound mail is safely set to **log-only**.

**Safety (process & scoring):** The system is designed so that **official residual risk, tier, and approval level come only from the fixed AIRA-DDA-1.0 engine**, after a reviewer confirms factor scores. The chatbot / Gemma path may pre-fill or draft answers, but it is not the authority for governance scores. Screening answers that drive risk cannot be casually overridden from chat. Duplicate similarity checks (90% threshold) reduce near-duplicate submissions.

**Safety (cyber / appsec):** Platform hardening on OpenShift is in place (TLS edge Route, non-root, dropped capabilities, JWT via Secret). However, **demo credentials, Secure-cookie gaps, SQLite on `/tmp`, and LLM TLS verification off** mean this should be described as a **controlled internal pilot**, not a full production identity/security posture, until those items are closed.

**Scalability:** The current topology is **one pod**, **Recreate** rollout, and **SQLite** (ReadWriteOnce PVC semantics). That is appropriate for early RAIO pilot volume. It is **not** horizontally scalable as-is. Scaling to many concurrent users or multi-site HA requires a shared database, multiple replicas (or active/passive with failover), and treating Gemma capacity as a separate bottleneck.

---

## 2. Production deployment check

### Verdict: **Good — deploy succeeded**

| Check | Result |
| --- | --- |
| OpenShift project | `ai-risk` |
| Deployment | `1/1` ready; rollout successful |
| Pod | Running, Ready, current image after redeploy |
| Service | ClusterIP port `8000` |
| Route | Edge TLS + redirect HTTP → HTTPS |
| PVC `aira-db` | Bound (`1Gi`, RWO) |
| `GET /health` | `200` — `status: ok`, methodology `AIRA-DDA-1.0` |
| LLM | `llmConfigured: true`, model `gemma-3-12b-dpo-apr-merged-aws` |
| Mail | Provider `log` (no live SMTP/Graph) |
| Portal | Latest AIMS UI (`pre-filled…`, `Get AIRA`, `chooseMode`) |
| Framework | `GET /aira_risk_framework.json` → `200` |
| Image | `…/jazz-ai-risk-assessment:latest` (internal registry) |

### This release included

- Portal packaged from `AIMS_final.html`
- `aira_risk_framework.json` in the image
- Intake/chat hardening (money grounding, screening guards, assist/manual mode)
- Redeploy via `openshift/deploy.sh` plus rollout restart so `:latest` was applied

### Operational residual risks

1. SQLite path still `/tmp` while PVC mounts `/data` — data can be lost on pod recycle.  
2. Mutable `:latest` tag — weaker audit/rollback than digest pins.  
3. Demo accounts seed on empty DB — pilot only.

---

## 3. System architecture

```
Users / RAIO reviewers
        │
        ▼
OpenShift Route (TLS edge)
        │
        ▼
AIRA FastAPI pod  (project ai-risk, ocpv2)  ←── 1 replica today
        │
        ├── SQLite (currently /tmp; PVC at /data available)
        ├── JWT auth (requester vs reviewer)
        ├── AIRA-DDA-1.0 scoring engine (in-process, deterministic)
        │
        └── HTTPS → Jazz Gemma on AIOps (external)
              gemma-3-12b-dpo-apr-merged-aws-teknosys-ai.apps.aiops.jazz.com.pk/v1
```

**Trust boundaries**

| Boundary | What crosses it | Who controls it |
| --- | --- | --- |
| Browser → AIRA Route | Auth, intake text, submissions | AIRA / OpenShift |
| AIRA → SQLite | Users, sessions, submissions, decisions | AIRA pod local disk / PVC |
| AIRA → AIOps Gemma | Description / chat for field extraction | Jazz AIOps platform |
| AIRA → Mail (future) | Decision/submission notices | Graph / SMTP when enabled |
| ServiceNow → AIRA (planned) | Final decision vs reference ID | Reviewer API + integration account |

---

## 4. How safe is the system

“Safe” here covers **governance safety** (wrong approvals / invented risk) and **cyber safety** (abuse, data exposure, integrity).

### 4.1 Governance & decision safety (strong by design)

| Control | How it works | Why it matters |
| --- | --- | --- |
| Deterministic scoring | Residual risk / tier / approval from AIRA-DDA-1.0 only | LLM cannot quietly raise or lower official risk |
| Human score confirmation | Assessment path requires human-approved provenance | AI-suggested numbers cannot become official without review |
| Screening lock in chat | Sensitive / decision / action answers cannot be changed from chat once set | Stops prompt-injection style “set sensitive to No” |
| Grounded extraction | Invented money/hours/threat categories dropped unless supported by user text | Reduces fabricated business case numbers |
| Assist vs manual mode | User chooses guided questions or form fill; can switch later | Clear human control of how the form is completed |
| Duplicate check | Similarity ≥ 90% flagged against prior submissions | Reduces re-submit / copy-paste abuse |
| Indicative vs official | Portal shows indicative risk; RAIO confirms official assessment | Users are not led to treat chatbot scores as final |
| Decision API gated | Only reviewer/governance/admin can record outcomes | Requesters cannot self-approve |

### 4.2 Application & platform safety (good baseline, pilot gaps)

**Already good**

- HTTPS only via OpenShift Route (edge TLS + redirect).  
- Pod runs as non-root; all Linux capabilities dropped; RuntimeDefault seccomp.  
- Passwords stored with PBKDF2-HMAC-SHA256 (120k iterations), salted, compared in constant time.  
- JWT algorithm pinned; **role taken from database on each request**, not blindly from token claims.  
- Requester data isolation for intake sessions and submissions.  
- Mail default `log` — no accidental mass email from the cluster until Graph/SMTP is deliberately enabled.  
- Secrets for JWT via OpenShift Secret (`aira-secrets`); `.env` not committed.

**Must fix before full production identity**

- Shared demo password and HTML auto-login (Critical).  
- Session cookie not marked Secure; bearer token also returned to JS (High).  
- DB on `/tmp` (High) — integrity/availability of approval records.  
- LLM TLS verification disabled by default (High) for data in transit to AIOps.  
- OpenAPI docs and rich `/health` still public on the Route (Medium).

### 4.3 Data safety

| Data type | Where stored / processed | Sensitivity | Notes |
| --- | --- | --- | --- |
| Use-case descriptions | SQLite + sent to Gemma for extraction | Business confidential | May include personal/financial context typed by requester |
| Screening & form answers | SQLite | Confidential | Drive routing and risk |
| Official scores & decisions | SQLite | Governance record | Must persist on PVC / managed DB for audit |
| JWT sessions | Cookie + optional bearer | Auth | 12h default lifetime |
| Mail content | Log provider today | N/A until Graph/SMTP | Keep log-only until DLP/allowlist ready |

### 4.4 Safety statement suitable for a formal pack

> AIRA separates **assistance** (Jazz Gemma drafting intake fields) from **authority** (AIRA-DDA-1.0 scoring and RAIO decisions). That separation is the primary safety property of the system. Platform controls (TLS Route, non-root pods, role-based APIs) provide a solid OpenShift baseline. Remaining gaps are mainly **identity hardening**, **durable storage**, and **verified TLS to AIOps**, which should be closed before enterprise-wide go-live and ServiceNow write-back at scale.

---

## 5. How scalable is the system

### 5.1 Current capacity profile

| Layer | Current design | Scalability implication |
| --- | --- | --- |
| App replicas | **1** | No horizontal scale; single point of failure during pod death |
| Rollout strategy | **Recreate** | Brief downtime on deploy; required while using RWO SQLite PVC |
| Database | **SQLite** (file) | One writer; not suitable for multi-pod concurrent write |
| PVC | **1Gi RWO** | Cannot attach read-write to multiple pods |
| CPU / memory | Request `100m` / `256Mi`; limit `1` CPU / `1Gi` | Small pilot footprint; LLM wait is usually network-bound |
| LLM calls | Sync HTTP, ~60s timeout | Throughput limited by AIOps Gemma concurrency, not only AIRA |
| Intake payload caps | Description ≤ 8000 chars; chat message ≤ 6000 | Protects memory/LLM context size |
| Auth sessions | Stateless JWT | Scales with app instances once DB is shared |
| Duplicate scan | Compares against stored submissions | Cost grows with submission count (in-process scan) |

### 5.2 What the system scales well for today

- Internal RAIO pilot / controlled departmental rollout.  
- Low-to-moderate concurrent browser users (tens, not thousands), as long as Gemma responds.  
- Read-heavy reviewer lookups of a modest submission catalogue.  
- Stateless API auth (JWT) once a shared DB exists.

### 5.3 What does not scale without redesign

| Bottleneck | Why | Direction if volume grows |
| --- | --- | --- |
| Single replica | Pod/node failure = full outage | 2+ replicas behind Service (needs shared DB) |
| SQLite | File locking; RWO PVC | PostgreSQL / enterprise DB on Jazz platform |
| Recreate deploys | Downtime window | Rolling updates after shared DB |
| Gemma on AIOps | Shared platform capacity & latency | Queue / async jobs; cache; rate limits; dedicated quota |
| Duplicate compare | Linear scan in app | Indexed search / background job |
| Local disk DB on `/tmp` | Lost on restart | PVC path or managed DB (mandatory) |

### 5.4 Scalability statement suitable for a formal pack

> AIRA is **architecturally simple and fit for a pilot**: one OpenShift Deployment, one Service, one Route, one SQLite store, and an external LLM. That simplicity improves operability and reduces attack surface, but **horizontal scalability and high availability are not present today**. For enterprise scale, move persistence to a shared database, run multiple app replicas, pin images, and capacity-plan Jazz Gemma separately. Scoring itself remains cheap (CPU-bound in-process math) and is not the primary scale bottleneck — **I/O, LLM latency, and single-instance storage** are.

### 5.5 Target architecture (recommended evolution)

```
Route (TLS)
  → N AIRA pods (RollingUpdate)
       → Shared PostgreSQL (HA)
       → AIOps Gemma (quota / circuit breaker)
       → Mail Graph (async)
       → ServiceNow decision webhook / API client
```

---

## 6. Security audit findings

### 6.1 Critical / High

| ID | Severity | Area | Finding | Evidence | Recommendation |
| --- | --- | --- | --- | --- | --- |
| S-01 | Critical | Identity | Shared demo password and HTML auto-login. | `seed.py`, portal HTML, docs | Disable seed in prod; IdP; remove hardcoded logins. |
| S-02 | High | Cookie | JWT cookie not `Secure`. | `api/router.py` | `secure=True` in production. |
| S-03 | High | Tokens | Bearer `accessToken` exposed to JS. | Login JSON + portal | Cookie-only browser auth; CSP. |
| S-04 | High | Secrets | Weak default JWT if Secret missing. | `config.py`, `02-secret.yaml` | Fail closed on weak secret. |
| S-05 | High | Persistence | DB on `/tmp`; PVC unused. | `03-deployment.yaml` | `sqlite:////data/aira.db` or managed DB. |
| S-06 | High | LLM TLS | `llm_verify_ssl=false` by default. | `config.py`, `llm.py` | Verify with corporate CA. |

### 6.2 Medium / Low / Info

| ID | Severity | Area | Finding | Recommendation |
| --- | --- | --- | --- | --- |
| S-07 | Medium | CORS | `*.onrender.com` regex still active. | Remove for OpenShift-only builds. |
| S-08 | Medium | Exposure | `/docs` + detailed `/health`. | Disable docs; minimize health. |
| S-09 | Medium | Session | 12h JWT; no logout/rate limit. | Shorter TTL; logout; rate-limit login. |
| S-10 | Medium | Mail | Reviewer mail-test to arbitrary `to`. | Allowlist; keep log-only. |
| S-11 | Medium | Supply chain | `:latest` mutable tag. | Pin digest. |
| S-12 | Medium | Secrets | Only JWT in Secret today. | Put mail/LLM secrets in Secret objects. |
| S-13 | Low | Disclosure | Duplicate preview may show peer summary. | Redact for requesters. |
| S-14 | Low | AuthZ | Governance = full reviewer powers. | Split duties if required. |
| S-15 | Info | Network | No NetworkPolicy. | Egress allowlist to AIOps/mail. |

### 6.3 Controls already in place

- PBKDF2 password hashing; JWT algorithm allow-list.  
- Role from DB each request.  
- Requester isolation; reviewer-gated assess/decide.  
- LLM cannot author official scores.  
- OpenShift TLS Route, non-root, drop caps, seccomp, ClusterIP, JWT Secret, mail `log`.  
- `.env` gitignored.

---

## 7. AuthZ matrix

| Capability | Requester | Reviewer / governance / admin |
| --- | --- | --- |
| Login / me | Yes | Yes |
| Own intake sessions | Yes | Own only |
| List/create submissions | Own | All |
| Get by reference | Own | Any |
| Assessment / decision | No | Yes |
| Mail status / test | No | Yes |
| Official methodology calculate | No | Yes |

---

## 8. External dependency — Jazz Gemma

| Item | Detail |
| --- | --- |
| Where hosted | Jazz AIOps — **not** inside the AIRA OpenShift app |
| URL | `https://gemma-3-12b-dpo-apr-merged-aws-teknosys-ai.apps.aiops.jazz.com.pk/v1` |
| Model | `gemma-3-12b-dpo-apr-merged-aws` |
| Used for | Intake field extraction / chat assistance |
| Not used for | Official residual risk, tier, or approval authority |
| Auth | No API key by default (network trust) |
| TLS verify | Off by default today — must harden for production |
| Failure mode | Keyword / offline extraction fallback |

**Safety implication:** Even with a compromised or biased LLM response, grounded filters + human confirmation + DDA engine limit the blast radius on **formal risk outcomes**. The remaining risk is mainly **confidential data leaving the AIRA pod toward AIOps**, which needs TLS verification, network allowlisting, and clear DLP classification.

---

## 9. ServiceNow integration posture

Agreed direction: action button on existing AIMS RITM posts final RAIO decision back to AIRA by **reference ID**.

| Item | Status |
| --- | --- |
| Read submission | `GET /api/v1/submissions/{referenceId}` — available |
| Auth | `POST /api/v1/auth/login` → Bearer token (reviewer account) |
| Decision write | `POST /api/v1/submissions/{referenceId}/decision` — available |
| Outcomes | `approved`, `approved_with_conditions`, `rejected`, `needs_information` |
| RITM field | Planned (`serviceNowTicket`) — not in payload yet |
| Scale note | Decision API is light; volume will be ticket-driven, not chatbot-driven |

---

## 10. Capacity & scaling roadmap

### Phase A — Pilot (current)

- 1 replica, SQLite, Gemma on AIOps, demo or limited users.  
- Goal: validate UX, RAIO process, ServiceNow contract.  
- Accept brief deploy downtime (Recreate).

### Phase B — Production hardening (required before wide rollout)

- Durable DB on PVC or PostgreSQL.  
- Disable demo seed; enterprise login / SSO.  
- Secure cookies, TLS-verify LLM, pin image digest, NetworkPolicy.  
- Monitoring/alerts on `/health`, error rate, LLM latency.

### Phase C — Scale-out

- Shared DB + 2–N replicas + RollingUpdate.  
- Async LLM or queue if AIOps saturates.  
- Indexed duplicate detection.  
- HA mail and audited ServiceNow service account.

---

## 11. Go-live readiness checklist

### Deploy / function

- [x] HTTPS Route live  
- [x] Health OK; latest portal features  
- [x] Gemma configured  
- [x] Mail log-only  
- [ ] Durable DB path (PVC or managed)  
- [ ] Image digest pin  

### Safety / security

- [ ] Demo seed & HTML credentials removed  
- [ ] Secure session cookies  
- [ ] LLM TLS verification on  
- [ ] Docs disabled / health minimized  
- [ ] Login rate limit + logout  
- [ ] NetworkPolicy egress allowlist  
- [ ] SSO / real identity (recommended)  

### Integration

- [ ] ServiceNow decision contract finalized  
- [ ] `serviceNowTicket` field (if required)  
- [ ] Reviewer service account for ServiceNow  

### Scale

- [ ] Shared DB decision  
- [ ] Multi-replica plan  
- [ ] Gemma capacity agreement with AIOps  

---

## 12. Conclusion for document owners

**Production went well.** AIRA is live on OpenShift with the latest portal, healthy probes, framework JSON, and Gemma connectivity.

**How safe is it?**  
- **Governance-safe by design** for scoring authority (DDA engine + human confirmation + chat screening locks).  
- **Cyber-safe enough for a controlled pilot** with OpenShift hardening, but **not yet full production identity / transport / persistence posture** until Critical/High findings S-01–S-06 are closed.

**How scalable is it?**  
- **Fit for pilot and early RAIO load.**  
- **Not horizontally scalable today** because of single replica + SQLite/RWO. Scale requires shared database and multi-replica design; Gemma capacity must be planned with AIOps separately.

**Recommended wording for an external/formal summary**

> JazzWorld AIRA is successfully deployed on OpenShift and ready for controlled internal use. Its safety model keeps AI assistance separate from official risk authority. Scalability is intentionally conservative (single instance, SQLite) and should be evolved with a shared database and multi-replica topology before enterprise-wide adoption.

---

*Source: live OpenShift verification on 5 Nov 2026 and static review of repository code/manifests. No secret values are included in this document. Suitable as input for a Word/PDF readiness or security pack.*
