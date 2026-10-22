# JazzWorld AI Approval API

Python API for the Responsible AI Office approval portal. It accepts a request in conversation or as the portal's submission payload, blocks near-duplicates, notifies the requester and Governance & Compliance, and scores residual risk with methodology **AIRA-DDA-1.0**.

> Full product docs, architecture diagrams, and the live demo link are in the [root README](../README.md).

The scoring math, screening questions, early flags, reviewer routing, and **90%** duplicate rule are the same ones embedded in `Ai_risk_assessment_icon_toggle.html`.

## Run

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Docs: http://127.0.0.1:8000/docs

Demo sign-in (password `JazzDemo-2026`):

| Email | Role |
| --- | --- |
| ayesha.khan@jazz.example | Requester (Technology) |
| rahim.qureshi@jazz.example | RAIO reviewer |
| sana.malik@jazz.example | Governance & Compliance |

Change `JWT_SECRET` before any shared deployment. These accounts exist so the service can be tried locally.

## What a request goes through

1. The requester describes the use case. Extraction uses Jazz AIOps Gemma (`LLM_BASE_URL`) when configured; otherwise the keyword extractor fills the same slots as the portal prototype. Keywords still fill any fields the model omits.
2. The requester confirms or corrects each answer. "Not sure" on the three screening questions is kept on the record and treated as "Yes" for routing and weights.
3. Early flags and indicative reviewers are calculated on the server (RAIO, privacy, cybersecurity, legal, architecture, procurement).
4. Submit checks every stored request, not just one browser. At 80% similarity or above the API returns `409` and does not save the request.
5. The requester and `GOVERNANCE_EMAIL` each get a notice with the reference (`AIRA-YYYYMMDD-XXXXX`) and the full request. Mail goes through the Outlook framework in `app/mail/` (`MAIL_PROVIDER=auto|smtp|graph|log`). Until SMTP or Graph credentials are set, notices are stored with status `logged`.

## Outlook mail (submit notifications)

On submit (and on decision), the API emails the requester and governance contact.

| Mode | When to use | Config |
| --- | --- | --- |
| `log` | Local demo | Default if nothing else is set |
| `smtp` | Outlook / Microsoft 365 SMTP | `SMTP_HOST=smtp.office365.com`, user, password, from |
| `graph` | Production (recommended) | Entra app with `Mail.Send` + `GRAPH_*` values |

Check: `GET /api/v1/mail/status` · Test send: `POST /api/v1/mail/test` `{"to":"you@jazz.com.pk"}` (reviewer login). See `.env.example`.
6. A reviewer confirms every impact, likelihood, and control score (1–5). Control 1 is strong and 5 is weak or absent. Official residual risk, tier, and approval level are calculated only by the deterministic **AIRA-DDA-1.0** engine — never by the LLM. AI-suggested values cannot become official inputs until marked `HUMAN_CONFIRMED` / `HUMAN_ENTERED` / `HUMAN_EDITED` and `humanReview.status = APPROVED`.
7. The reviewer records approved, approved with conditions, rejected, or needs information. The requester is notified of that outcome.

Risk bands (from **residual** risk only): 1–25 Low / self-review, 26–59 Medium / line manager, 60–79 High / head of department, 80–100 Critical / C-suite.

Official calculator: `POST /api/v1/methodology/assess` (returns scores, weights, contradictions, treatment requirements, and a calculation trace).

## Portal contract

`POST /api/v1/submissions` accepts the JSON body the prototype already builds (`referenceId`, `category`, `screening`, `aiSystem`, `conditionalInformation`, and the rest). Send `Authorization: Bearer <accessToken>` from `POST /api/v1/auth/login`. The sign-in cookie `aira_session` is also accepted when the browser calls this host with credentials.

Routing, flags, and the weight profile in the response are recomputed here. A `governance` object sent by the browser is stored as `submittedGovernance` and is not the routing that reviewers see.

Set the prototype endpoint with:

```html
<script>
  window.JazzWorldConfig = {
    submissionEndpoint: "http://127.0.0.1:8000/api/v1/submissions"
  };
</script>
```

The prototype page does not sign in, so that call succeeds only after the portal sends the bearer token or cookie above.

## Useful routes

- `POST /api/v1/intake/sessions` — start from a description
- `POST /api/v1/intake/sessions/{id}/confirm` — accept inferred answers
- `POST /api/v1/intake/sessions/{id}/answers` — answer or edit one slot
- `POST /api/v1/intake/sessions/{id}/submit`
- `GET /api/v1/submissions` and `GET /api/v1/submissions/{reference}`
- `POST /api/v1/submissions/{reference}/assessment` — reviewer scores
- `POST /api/v1/submissions/{reference}/decision`
- `GET /api/v1/methodology` — factor names for the score form

## Tests

```bash
pytest
```

Score tests compare this engine with results produced by the prototype's JavaScript methodology.
