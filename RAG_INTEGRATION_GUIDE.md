# AIRA main-chat RAG integration — implementation guide

This completed project is based on the original `Jazz-AI-Risk-Assessment`
project. The only functional changes are the main intake-chat RAG path, its
configuration/packaging/health reporting, its knowledge corpus, and its tests.

## Files changed

| File | Change |
|---|---|
| `backend/app/config.py` | Adds RAG settings; keeps the existing LLM configuration intact |
| `backend/app/services/intake_flow.py` | Routes policy/methodology questions through RAG before intake parsing |
| `backend/app/main.py` | Adds non-sensitive RAG readiness fields to `/health` |
| `backend/requirements.txt` | Adds document parsers needed by the offline ingestion command |
| `backend/Dockerfile` | Packages the approved knowledge base and SQLite index |
| `backend/.env.example` | Documents RAG settings and secure TLS defaults |
| `backend/README.md` | Adds operating, governance, and security documentation |
| `backend/app/rag/service.py` | New read-only retrieval and grounded answer service |
| `backend/app/rag/ingest.py` | New allowlisted, atomic index builder |
| `backend/app/rag/__init__.py` | RAG package marker |
| `backend/knowledge_base/**` | Approved source documents, manifest, and generated index |
| `backend/tests/test_rag.py` | RAG isolation, allowlist, abstention, and routing tests |

No risk-engine, scoring, methodology, submission, email, user model, or portal
business logic was changed.

## Exact integration point

The integration is in:

`backend/app/services/intake_flow.py` → `add_message(...)`

The RAG branch executes before the existing code appends a message to the
use-case description or attempts to extract intake fields. If a message is
identified as an AIRA policy/methodology question, the assistant answer and
source metadata are saved to the existing transcript and the function returns.
All other messages continue through the original intake implementation.

No new public unauthenticated route is added. Existing authenticated
`POST /api/v1/intake/sessions/{session_id}/messages` remains the chat interface.

## What to add/change in an existing checkout

The easiest and safest path is to use this completed project as the replacement
working tree. If manually applying the integration, copy the files in the table
above from this archive, preserving all other original files. Do not copy the
whole previous RAG project over the original project: that would replace
unrelated project files and may introduce unrelated changes.

## Local setup

From the project root:

```bash
cd backend
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate

python -m pip install -r requirements.txt
cp .env.example .env
```

Set `JWT_SECRET` to a randomly generated secret of at least 32 bytes and
configure the approved Jazz Gemma endpoint. Keep `RAG_VERIFY_SSL=true`. If
the endpoint uses a private corporate CA, install that CA in the Python/container
trust store rather than disabling certificate validation.

The completed archive already includes a generated `knowledge_base/aira_knowledge.sqlite3`.
To rebuild it after a formally approved source-document change:

```bash
python -m app.rag.ingest
```

Then start the application:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Check `GET /health` for `ragEnabled: true` and `ragIndexReady: true`.
Sign in using the application's existing authentication, create an intake chat,
and ask a policy question such as:

`What are the AIRA risk tiers and their approval levels?`

Then send a normal use-case message and confirm it still follows the original
intake workflow.

## Deployment

The backend Dockerfile now copies `knowledge_base/` into the image. Build and
deploy the backend using the same deployment process as the original project.
Ensure the runtime image contains the generated SQLite index at the configured
`RAG_INDEX_PATH`.

For production, the platform team must provide HTTPS ingress, managed secret
injection, restricted network egress to the approved LLM endpoint, least-
privilege filesystem permissions, centralised logs, dependency/security scans,
and operational rate limits. The application-level RAG safeguards do not
replace those infrastructure controls.

## Validation performed

- Built the SQLite index from the manifest-approved sources: 149 passages.
- Confirmed representative queries retrieve the final scales workbook and
  current standard passages.
- Ran the full backend test suite: **79 passed**.
- The RAG test suite verifies that superseded and unclassified passages are
  not retrieved, retrieval failure abstains, and knowledge turns do not alter
  the use-case description.

The tests do not prove the quality of live Gemma responses or the organisation's
formal approval of the source corpus. User questions and retrieved passages are
sent to the configured LLM endpoint; production owners must confirm that this
Jazz endpoint is approved for the classification of every indexed document.
Those checks require testing against the live Jazz endpoint and confirmation
from the document owners/RAIO.
