FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY AIMS_final.html ./static/index.html
COPY aira_risk_framework.json ./static/aira_risk_framework.json

# Writable data dir for OpenShift PVC (SQLite). Render keeps using /tmp via env.
RUN mkdir -p /data && chmod 0777 /data

ENV PYTHONUNBUFFERED=1
ENV DATABASE_URL=sqlite:////tmp/aira.db

EXPOSE 8000
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
