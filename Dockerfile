FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY Ai_risk_assessment_icon_toggle.html ./static/index.html

ENV PYTHONUNBUFFERED=1
ENV DATABASE_URL=sqlite:////tmp/aira.db

EXPOSE 8000
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
