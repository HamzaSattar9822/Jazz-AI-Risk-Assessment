# Deploy on Render

## One-service setup

This repo deploys as a **single Docker web service**:

- Portal UI at `/` (and `/app`)
- API at `/api/v1`
- Health check at `/health`
- Docs at `/docs`

## Steps

1. Push latest `main` to GitHub.
2. Open [Render Dashboard](https://dashboard.render.com) → **New** → **Blueprint**.
3. Connect `HamzaSattar9822/Jazz-AI-Risk-Assessment` and apply `render.yaml`.
4. After deploy, open the service URL (e.g. `https://jazz-ai-risk-assessment.onrender.com`).

### Manual (without Blueprint)

1. **New Web Service** → connect the GitHub repo.
2. Runtime: **Docker** (root `Dockerfile`).
3. Set env vars:
   - `JWT_SECRET` = long random string
   - `DATABASE_URL` = `sqlite:////tmp/aira.db` (demo only)
   - `MAIL_PROVIDER` = `log`
4. Health check path: `/health`

## Demo login

| Email | Password | Role |
| --- | --- | --- |
| ayesha.khan@jazz.example | JazzDemo-2026 | Requester |
| rahim.qureshi@jazz.example | JazzDemo-2026 | Reviewer |

## Notes

- Free tier spins down after idle; first request can take ~30–60s.
- SQLite on `/tmp` is **ephemeral** (data resets on redeploy/restart). For real persistence, add Render Postgres and set `DATABASE_URL` to the Postgres URL (add `psycopg2-binary` when you do).
- Jazz LLM calls from Render only work if Render can reach the Jazz AIOps endpoint.
