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


## Approved knowledge assistant (RAG)

The existing authenticated intake chat can answer AIRA policy and methodology
questions using the approved knowledge corpus. This integration is deliberately
limited to the chat path: ordinary use-case descriptions continue through the
existing intake workflow, and knowledge turns are saved to the transcript without
being appended to the use-case description or used to populate intake slots.

### Architecture

1. `app.rag.ingest` extracts approved source documents into bounded passages.
2. SQLite FTS5 performs read-only keyword retrieval at chat time.
3. Only passages with `status=current` and authority `official` or `supporting`
   are eligible for retrieval.
4. The configured Jazz Gemma-compatible endpoint generates a concise answer from
   those passages only.
5. The application, not the model, attaches the source document and locator list.
6. If retrieval finds no evidence, or generation fails, the assistant abstains
   rather than filling gaps with general knowledge.

The RAG assistant does not calculate risk scores, assign official risk tiers,
approve/reject systems, or change the AIRA-DDA-1.0 methodology. Those operations
remain with the deterministic assessment engine and authorised human reviewers.

### Knowledge governance

Place approved reference documents in `knowledge_base/source_docs/` and register
each filename in `knowledge_base/manifest.json`. Only explicitly manifested
documents with `authority` set to `official` or `supporting` and `status` set to
`current` or `superseded` are considered by ingestion. Superseded documents are
retained for traceability but excluded from retrieval. Unlisted files, drafts,
unclassified documents, and the restricted operational use-case inventory are
not indexed.

The supplied corpus includes the approved AIRA standard, field reference,
governance/control matrix, final impact/likelihood/control scales, and supporting
calculator reference. The V2 scales workbook is marked superseded. Confirm
document ownership, classification, version, and approval status with RAIO before
production use; the manifest is a deployment control, not a substitute for formal
document approval.

### Build or rebuild the index

```bash
cd backend
python -m pip install -r requirements.txt
python -m app.rag.ingest
```

The builder validates the manifest, rejects unsafe/unlisted source files, builds
a temporary SQLite database, checks its row counts, and atomically replaces the
active index only after a successful build. Retrieval opens the index read-only.
Rebuild and deploy the index through a controlled release process whenever an
approved source changes; do not expose ingestion as a public API.

### Configuration

```env
RAG_ENABLED=true
RAG_INDEX_PATH=knowledge_base/aira_knowledge.sqlite3
RAG_TOP_K=5
RAG_MIN_TERM_COVERAGE=1
RAG_TIMEOUT_SECONDS=35
RAG_VERIFY_SSL=true
```

`RAG_VERIFY_SSL=true` should remain enabled in production. If the internal Jazz
model endpoint uses a private certificate authority, install the approved
corporate CA certificate into the runtime trust store; do not disable TLS
verification as a workaround. `LLM_VERIFY_SSL` remains a separate setting used
by the existing intake extraction workflow.

### Security and operational controls

- The chat route continues to require the existing authenticated session and
  session-ownership check.
- User input and retrieved passages are treated as untrusted data; the prompt
  explicitly prohibits following instructions embedded in either.
- FTS query syntax is generated from tokenised terms rather than raw user input.
- The model receives bounded question/context sizes, a bounded output budget,
  a finite timeout, and no redirect following.
- Runtime retrieval is read-only. Only current, allowlisted source passages can
  support an answer.
- Source labels and locators are attached by application code; model-generated
  citation labels are discarded.
- No retrieval evidence means abstention. Model/network failures return a safe
  fallback and do not affect intake state.
- RAG does not expose document upload, index rebuild, scoring, approval, or
  decision capabilities.

User questions and retrieved passages are sent to the configured LLM endpoint;
confirm that the Jazz endpoint is approved for the classification of every
indexed source. Before production deployment, additionally enforce
organisation-wide controls at the platform boundary: managed secrets, HTTPS ingress, least-privilege
database/filesystem permissions, network egress allowlisting to the approved
model endpoint, centralised audit logging, dependency scanning, backup/restore
testing, and load/rate-limit testing. These depend on the deployment platform
and cannot be guaranteed by application code alone.

### Health and tests

`GET /health` reports `ragEnabled` and `ragIndexReady`; it does not expose
document contents. Run:

```bash
cd backend
pytest
```

The RAG tests cover approved-source retrieval, exclusion of superseded/untrusted
content, abstention, and the guarantee that knowledge questions do not pollute
the intake description.
