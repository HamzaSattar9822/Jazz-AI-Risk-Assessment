"""Persist a request, block near-duplicates, and record the RAIO assessment."""

from __future__ import annotations

import re
import secrets
import string
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings
from app.intake.duplicates import compare_submissions
from app.intake.catalog import (
    SLOTS_BY_ID,
    active_slots,
    comparable_from,
    effective_answer,
    flags_for,
    has_value,
    initial_state,
    missing_slots,
    route_for,
    validate_answer,
    values_of,
)
from app.methodology.engine import (
    METHODOLOGY_VERSION,
    calculate_assessment,
    calculate_risk,
    get_weight_profile,
    incomplete_score_paths,
)
from app.methodology.provenance import ProvenanceError
from app.models import Submission, User, utcnow
from app.services.emailer import decision_notice, notify, submission_notice

_REF = re.compile(r"^AIRA-\d{8}-[A-Z0-9]{5}$")
_ALPHABET = string.ascii_uppercase + string.digits
_FINAL = {"approved", "approved_with_conditions", "rejected"}


class SubmissionError(Exception):
    def __init__(self, message: str, status_code: int = 400, extra: dict | None = None):
        self.message = message
        self.status_code = status_code
        self.extra = extra or {}


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_reference(db: Session, preferred: str | None = None) -> str:
    if preferred:
        if not _REF.match(preferred):
            raise SubmissionError("Reference must look like AIRA-YYYYMMDD-XXXXX.", 422)
        taken = db.scalar(select(Submission.id).where(Submission.reference_id == preferred))
        if taken is not None:
            raise SubmissionError("That reference is already in use.", 409, {"code": "reference_taken"})
        return preferred
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    for _ in range(8):
        suffix = "".join(secrets.choice(_ALPHABET) for _ in range(5))
        reference = f"AIRA-{today}-{suffix}"
        taken = db.scalar(select(Submission.id).where(Submission.reference_id == reference))
        if taken is None:
            return reference
    raise SubmissionError("Could not allocate a reference. Try again.", 500)


def build_payload(state: dict, description: str, reference: str, submitted_at: datetime, intake_mode: str) -> dict:
    values = values_of(state)
    screening = {
        "data": values.get("sensitive") or "",
        "decision": values.get("decision") or "",
        "action": values.get("action") or "",
    }
    effective = {key: effective_answer(value) for key, value in screening.items()}
    triage = {
        "sensitive": effective["data"],
        "decision": effective["decision"],
        "action": effective["action"],
    }
    provenance = {}
    for slot in active_slots(state):
        entry = state["slots"][slot.id]
        provenance[slot.id] = {
            "value": entry["value"],
            "source": entry["source"],
            "confirmedByRequester": entry["status"] == "confirmed",
        }
    filled = sum(
        1
        for slot in active_slots(state)
        if state["slots"][slot.id]["status"] == "confirmed"
        and state["slots"][slot.id]["source"] in ("description", "llm")
    )
    category = values.get("category")
    conditional: dict = {}
    if category == "AI For Us":
        conditional["aiForUs"] = {
            "toolOrPlatform": values.get("forTool") or "",
            "accessMethod": values.get("forAccess") or "",
        }
    if category == "AI Against Us":
        conditional["aiAgainstUs"] = {"threatTypes": values.get("threatTypes") or []}
    if values.get("sensitive") == "Yes":
        conditional["data"] = {"externalProcessing": values.get("dataExternal") or ""}
    if values.get("decision") == "Yes":
        conditional["decision"] = {"humanReview": values.get("humanReview") or ""}
    if values.get("action") == "Yes":
        conditional["action"] = {"autonomy": values.get("autonomy") or ""}
    conditional["businessValue"] = {
        "segment": values.get("segment") or "",
        "valueDriver": values.get("valueDriver") or "",
        "annualValue": values.get("annualValue") or "",
        "investmentCost": values.get("investmentCost") or "",
        "spendingToDate": values.get("spendingToDate") or "",
        "hoursSaved": values.get("hoursSaved") or "",
    }
    return {
        "referenceId": reference,
        "submittedAt": _iso(submitted_at),
        "category": category,
        "screening": screening,
        "screeningEffective": effective,
        "aiSystem": {
            "name": values.get("name") or "",
            "businessOwner": values.get("owner") or "",
            "businessUnit": values.get("businessUnit") or "",
            "summary": values.get("summary") or "",
            "description": description.strip(),
        },
        "conditionalInformation": conditional,
        "provenance": provenance,
        "intake": {
            "mode": intake_mode,
            "questionsAsked": state.get("asked") or 0,
            "fieldsFilledFromDescription": filled,
            "extractor": state.get("extractor") or "keyword",
        },
        "governance": {
            "indicativeRouting": route_for(values),
            "earlyFlags": flags_for(values),
            "riskMethodologyVersion": METHODOLOGY_VERSION,
            "backendWeightProfile": get_weight_profile(triage),
        },
    }


def _require_complete(state: dict) -> None:
    missing = [slot.label for slot in missing_slots(state)]
    if missing:
        raise SubmissionError(
            "Still needed: " + ", ".join(missing),
            422,
            {"missing": missing},
        )


def preview_duplicate(db: Session, state: dict, description: str, settings: Settings) -> dict | None:
    return _closest(db, comparable_from(state, description), settings)


def _closest(db: Session, comparable: dict, settings: Settings) -> dict | None:
    rows = db.scalars(select(Submission)).all()
    best = None
    best_score = -1
    for row in rows:
        score = compare_submissions(comparable, row.comparable or {})
        if score > best_score:
            best_score = score
            best = row
    if best is None:
        return None
    return {
        "referenceId": best.reference_id,
        "similarity": best_score,
        "blocked": best_score >= settings.duplicate_threshold,
        "name": (best.comparable or {}).get("name") or "",
        "summary": (best.comparable or {}).get("summary") or "",
        "submittedAt": _iso(best.submitted_at),
        "threshold": settings.duplicate_threshold,
    }


def _block_if_duplicate(match: dict | None) -> None:
    if match and match["blocked"]:
        raise SubmissionError(
            f"Submission blocked: {match['similarity']}% similar to {match['referenceId']}.",
            409,
            {"code": "duplicate", "match": match},
        )


def _store(db: Session, user: User, payload: dict, comparable: dict, settings: Settings, match: dict | None) -> Submission:
    moment = datetime.now(timezone.utc)
    payload = dict(payload)
    payload["submittedAt"] = _iso(moment)
    row = Submission(
        reference_id=payload["referenceId"],
        requester_id=user.id,
        status="submitted",
        category=payload["category"],
        payload=payload,
        comparable=comparable,
        submitted_at=moment,
    )
    db.add(row)
    db.flush()
    subject, body = submission_notice(payload, user.name, user.email)
    notify(db, settings, row, user.email, "requester", subject, body)
    if settings.governance_email and settings.governance_email.lower() != user.email.lower():
        notify(db, settings, row, settings.governance_email, "governance", subject, body)
    db.commit()
    loaded = db.scalar(
        select(Submission)
        .where(Submission.id == row.id)
        .options(selectinload(Submission.requester), selectinload(Submission.notifications))
    )
    loaded.duplicate_check = match
    return loaded


def submit_state(db: Session, user: User, state: dict, description: str, settings: Settings, reference: str | None, mode: str) -> Submission:
    _require_complete(state)
    comparable = comparable_from(state, description)
    match = _closest(db, comparable, settings)
    _block_if_duplicate(match)
    reference = _new_reference(db, reference)
    payload = build_payload(state, description, reference, utcnow(), mode)
    return _store(db, user, payload, comparable, settings, match)


def state_from_portal(body, user: User) -> tuple[dict, str]:
    system = body.aiSystem
    description = (system.description or "").strip()
    if len(description) < 15:
        raise SubmissionError("Description must be at least 15 characters.", 422)
    screening = body.screening
    ci = body.conditionalInformation or {}
    for_us = ci.get("aiForUs") or {}
    against = ci.get("aiAgainstUs") or {}
    data = ci.get("data") or {}
    decision = ci.get("decision") or {}
    action = ci.get("action") or {}
    business_value = ci.get("businessValue") or {}
    raw = {
        "category": body.category,
        "name": system.name,
        "summary": system.summary or "",
        "owner": system.businessOwner or user.name,
        "businessUnit": system.businessUnit,
        "segment": business_value.get("segment") or "",
        "valueDriver": business_value.get("valueDriver") or "",
        "annualValue": business_value.get("annualValue") or "",
        "investmentCost": business_value.get("investmentCost") or "",
        "spendingToDate": business_value.get("spendingToDate") or "",
        "hoursSaved": business_value.get("hoursSaved") or "",
        "sensitive": screening.data,
        "decision": screening.decision,
        "action": screening.action,
        "forTool": for_us.get("toolOrPlatform") or "",
        "forAccess": for_us.get("accessMethod") or "",
        "threatTypes": against.get("threatTypes") or [],
        "dataExternal": data.get("externalProcessing") or "",
        "humanReview": decision.get("humanReview") or "",
        "autonomy": action.get("autonomy") or "",
    }
    state = initial_state(raw["owner"], raw["businessUnit"], description)
    state["extractor"] = (body.intake or {}).get("extractor") or "portal"
    state["asked"] = (body.intake or {}).get("questionsAsked") or 0
    for slot_id, value in raw.items():
        slot = SLOTS_BY_ID[slot_id]
        if slot.auto or not has_value(slot, value):
            continue
        try:
            cleaned = validate_answer(slot, value)
        except ValueError as exc:
            raise SubmissionError(str(exc), 422) from exc
        state["slots"][slot_id] = {
            "value": cleaned,
            "status": "confirmed",
            "source": "you",
            "why": "",
        }
    if raw["summary"]:
        try:
            summary = validate_answer(SLOTS_BY_ID["summary"], raw["summary"])
        except ValueError as exc:
            raise SubmissionError(str(exc), 422) from exc
        state["slots"]["summary"] = {
            "value": summary,
            "status": "confirmed",
            "source": "you",
            "why": "",
        }
    return state, description


def submit_portal(db: Session, user: User, body, settings: Settings) -> Submission:
    state, description = state_from_portal(body, user)
    client_governance = body.governance or {}
    row = submit_state(
        db,
        user,
        state,
        description,
        settings,
        body.referenceId,
        (body.intake or {}).get("mode") or "portal",
    )
    match = getattr(row, "duplicate_check", None)
    if client_governance:
        payload = dict(row.payload)
        payload["submittedGovernance"] = client_governance
        row.payload = payload
        db.commit()
        row = db.scalar(
            select(Submission)
            .where(Submission.id == row.id)
            .options(selectinload(Submission.requester), selectinload(Submission.notifications))
        )
        row.duplicate_check = match
    return row


def public_submission(row: Submission, match: dict | None = None) -> dict:
    payload = row.payload or {}
    system = payload.get("aiSystem") or {}
    assessment = row.assessment or None
    result = (assessment or {}).get("result") or {}
    return {
        "referenceId": row.reference_id,
        "status": row.status,
        "category": row.category,
        "name": system.get("name") or "",
        "businessUnit": system.get("businessUnit") or "",
        "requester": {
            "name": row.requester.name if row.requester else "",
            "email": row.requester.email if row.requester else "",
        },
        "submittedAt": _iso(row.submitted_at),
        "routing": (payload.get("governance") or {}).get("indicativeRouting") or [],
        "earlyFlags": (payload.get("governance") or {}).get("earlyFlags") or [],
        "residualRiskScore": result.get("residualRiskScore"),
        "residualRiskGovernance": result.get("residualRiskGovernance"),
        "payload": payload,
        "assessment": assessment,
        "decision": row.decision,
        "notifications": [
            {
                "recipient": note.recipient,
                "role": note.role,
                "subject": note.subject,
                "status": note.status,
                "createdAt": _iso(note.created_at),
            }
            for note in (row.notifications or [])
        ],
        "duplicateCheck": match,
    }


def list_for(db: Session, user: User, status: str | None, category: str | None) -> list[Submission]:
    query = select(Submission).options(selectinload(Submission.requester), selectinload(Submission.notifications))
    if user.role == "requester":
        query = query.where(Submission.requester_id == user.id)
    if status:
        query = query.where(Submission.status == status)
    if category:
        query = query.where(Submission.category == category)
    query = query.order_by(Submission.submitted_at.desc())
    return list(db.scalars(query).all())


def get_visible(db: Session, user: User, reference: str) -> Submission:
    row = db.scalar(
        select(Submission)
        .where(Submission.reference_id == reference)
        .options(selectinload(Submission.requester), selectinload(Submission.notifications))
    )
    if row is None:
        raise SubmissionError("Request not found.", 404)
    if user.role == "requester" and row.requester_id != user.id:
        raise SubmissionError("Request not found.", 404)
    return row


def _triage(payload: dict) -> dict:
    effective = payload.get("screeningEffective") or {}
    screening = payload.get("screening") or {}
    return {
        "sensitive": effective.get("data") or effective_answer(screening.get("data")),
        "decision": effective.get("decision") or effective_answer(screening.get("decision")),
        "action": effective.get("action") or effective_answer(screening.get("action")),
    }


def save_assessment(
    db: Session,
    user: User,
    row: Submission,
    scores: dict,
    notes: str,
    *,
    provenance: dict | None = None,
    human_review: dict | None = None,
    context: dict | None = None,
    mandatory_requirements: dict | None = None,
) -> Submission:
    if row.status in _FINAL:
        raise SubmissionError("This request already has a final decision.", 409)
    missing = incomplete_score_paths(scores)
    if missing:
        raise SubmissionError(
            "Every factor needs a score from 1 to 5.",
            422,
            {"missing": missing},
        )
    triage = _triage(row.payload or {})
    screening = {
        "data": triage["sensitive"] == "Yes",
        "decision": triage["decision"] == "Yes",
        "action": triage["action"] == "Yes",
    }
    review = dict(human_review or {})
    review.setdefault("status", "APPROVED")
    review.setdefault("reviewedBy", user.email)
    review.setdefault("reviewedAt", _iso(utcnow()))
    try:
        result = calculate_assessment(
            {
                "screening": screening,
                "scores": scores,
                "provenance": provenance or {},
                "humanReview": review,
                "context": context or {},
                "mandatoryRequirements": mandatory_requirements or {},
            },
            enforce_human_approval=True,
        )
    except ProvenanceError as exc:
        raise SubmissionError(exc.message, 422, {"rejected": exc.rejected}) from exc
    if not result.get("complete"):
        raise SubmissionError(
            "Assessment inputs are incomplete or invalid.",
            422,
            {"errors": result.get("errors") or []},
        )
    row.assessment = {
        "methodologyVersion": METHODOLOGY_VERSION,
        "scores": scores,
        "provenance": provenance or {},
        "humanReview": review,
        "result": result,
        "notes": notes.strip(),
        "assessedBy": user.email,
        "assessedAt": _iso(utcnow()),
        "engine": "AIRA-DDA-1.0-deterministic",
    }
    row.status = "in_review"
    db.commit()
    db.refresh(row)
    return row


def save_decision(db: Session, user: User, row: Submission, outcome: str, conditions: str, notes: str, settings: Settings) -> Submission:
    if row.status in _FINAL:
        raise SubmissionError("This request already has a final decision.", 409)
    if row.assessment is None:
        raise SubmissionError("Score the request before recording a decision.", 422)
    row.decision = {
        "outcome": outcome,
        "conditions": conditions.strip(),
        "notes": notes.strip(),
        "decidedBy": user.email,
        "decidedAt": _iso(utcnow()),
    }
    row.status = outcome
    db.flush()
    subject, body = decision_notice(row)
    requester = row.requester
    if requester is not None:
        notify(db, settings, row, requester.email, "requester", subject, body)
    if settings.governance_email and (requester is None or settings.governance_email.lower() != requester.email.lower()):
        notify(db, settings, row, settings.governance_email, "governance", subject, body)
    db.commit()
    db.refresh(row)
    return row
