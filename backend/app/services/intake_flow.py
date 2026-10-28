"""Conversational intake session transitions."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.config import Settings
from app.intake.agent import (
    llm_agent_turn,
    match_prior_for_reuse,
    offline_intent_extractions,
    wants_recall,
)
from app.intake.catalog import (
    EXAMPLES,
    SLOTS_BY_ID,
    active_slots,
    apply_extractions,
    classify_category,
    display_value,
    effective_answer,
    empty_slot_state,
    flags_for,
    has_value,
    initial_state,
    keyword_extract,
    make_summary,
    missing_slots,
    route_for,
    set_summary,
    validate_answer,
    values_of,
)
from app.intake.helpers import (
    HELPERS,
    continue_helper,
    detect_helper_slot,
    empty_helper_ids,
    next_empty_helper_slot,
    start_helper,
    wants_help,
)
from app.intake.llm import llm_extract
from app.methodology.engine import METHODOLOGY_VERSION, get_weight_profile, js_math_round
from app.models import IntakeSession, Submission, User


class IntakeError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code


def _merge_extractions(keyword: dict, model: dict | None) -> dict:
    """Keyword fill-in, then LLM — but never let N/A placeholders wipe real finds."""
    from app.intake.llm import is_placeholder_value

    found = dict(keyword or {})
    if not model:
        return found
    for slot_id, guess in model.items():
        if not isinstance(guess, dict):
            continue
        value = guess.get("value")
        if is_placeholder_value(value):
            continue
        # Keep richer keyword hours text if the model returns a bare number.
        if (
            slot_id == "hoursSaved"
            and slot_id in found
            and re.fullmatch(r"\d[\d,]*", str(value or "").strip())
            and re.search(r"hour|fte", str(found[slot_id].get("value") or ""), re.I)
        ):
            continue
        found[slot_id] = guess
    return found


def _extract(description: str, settings: Settings) -> tuple[dict, str]:
    keyword = keyword_extract(description)
    model = llm_extract(description, settings)
    if not model:
        found = _merge_extractions(keyword, None)
        extractor = "keyword"
    else:
        found = _merge_extractions(keyword, model)
        extractor = "llm"
    # Category is a governance fork — never let a biased LLM default wipe By Us / Against Us.
    classified = classify_category(description)
    if classified:
        llm_cat = (model or {}).get("category") or {}
        source = (
            llm_cat.get("source") or "llm"
            if llm_cat.get("value") == classified["value"]
            else "description"
        )
        found["category"] = {
            "value": classified["value"],
            "why": classified["why"],
            "source": source,
        }
    # Drop category-gated fields the model sometimes invents outside their route.
    cat = (found.get("category") or {}).get("value")
    if cat != "AI For Us":
        found.pop("forTool", None)
        found.pop("forAccess", None)
    if cat != "AI Against Us":
        found.pop("threatTypes", None)

    # Prefer model summary; otherwise a concise offline rewrite — never the raw prompt paste.
    summary_hit = (model or {}).get("summary") if model else None
    if summary_hit and summary_hit.get("value"):
        found["summary"] = summary_hit
    else:
        found["summary"] = {
            "value": make_summary(description),
            "why": "concise summary of your description",
            "source": "auto",
        }
    return found, extractor


def _apply_summary(state: dict, found: dict) -> None:
    hit = found.get("summary") or {}
    value = hit.get("value")
    if not value:
        return
    source = hit.get("source") or "auto"
    # Keep llm/auto distinction for the panel tag.
    if source not in ("llm", "auto", "description"):
        source = "llm"
    set_summary(state, value, source=source, why=hit.get("why") or "")


def extract_description(description: str, settings: Settings) -> dict:
    """Run Gemma (when configured) plus keyword fill-in for the portal UI."""
    text = description.strip()
    if len(text) < 15:
        raise IntakeError("Describe the request in at least 15 characters.", 422)
    found, extractor = _extract(text, settings)
    return {
        "extractor": extractor,
        "llmConfigured": settings.llm_configured,
        "extractions": found,
    }


def _options(slot) -> list[dict]:
    options = []
    for option in slot.options:
        if isinstance(option, tuple):
            options.append({"value": option[0], "label": option[1]})
        else:
            options.append({"value": option, "label": option})
    return options


def _slot_view(slot, entry: dict, *, include_question: bool = False) -> dict:
    view = {
        "id": slot.id,
        "label": slot.label,
        "group": slot.group,
        "kind": slot.kind,
        "value": entry["value"],
        "display": display_value(slot, entry["value"]) if has_value(slot, entry["value"]) else "",
        "status": entry["status"],
        "source": entry["source"],
        "why": entry["why"] or "",
    }
    if include_question or entry["status"] != "confirmed":
        view["question"] = slot.question
        view["placeholder"] = slot.placeholder
        view["options"] = _options(slot)
    return view


def _announce(state: dict, values: dict) -> list[dict]:
    fresh = []
    announced = set(state.get("announced") or [])
    for flag in flags_for(values):
        if flag["level"] == "info" or flag["title"] in announced:
            continue
        announced.add(flag["title"])
        fresh.append(flag)
    state["announced"] = sorted(announced)
    return fresh


def _say(state: dict, role: str, text: str, *, meta: dict | None = None) -> None:
    entry = {
        "role": role,
        "text": text,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    if meta:
        entry["meta"] = meta
    state.setdefault("transcript", []).append(entry)


def _slot_snapshot(state: dict) -> dict:
    values = values_of(state)
    out = {}
    for slot_id, value in values.items():
        if value in (None, "", []):
            continue
        slot = SLOTS_BY_ID.get(slot_id)
        if slot is None or slot.profile:
            continue
        out[slot_id] = value
    return out


def build_user_memory(db: Session, user: User, *, exclude_session_id: str | None = None) -> dict:
    """Compact prior chats + submissions for agent recall."""
    sessions = list(
        db.scalars(
            select(IntakeSession)
            .where(IntakeSession.user_id == user.id)
            .order_by(IntakeSession.updated_at.desc())
            .limit(8)
        ).all()
    )
    prior_sessions = []
    for row in sessions:
        if exclude_session_id and row.id == exclude_session_id:
            continue
        state = row.state or {}
        transcript = state.get("transcript") or []
        values = _slot_snapshot(state)
        prior_sessions.append(
            {
                "sessionId": row.id,
                "status": row.status,
                "name": values.get("name") or "",
                "category": values.get("category") or "",
                "summary": (state.get("slots") or {}).get("summary", {}).get("value") or "",
                "values": values,
                "recentTranscript": transcript[-6:],
                "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
                "submissionReference": row.submission_reference,
            }
        )

    submissions = list(
        db.scalars(
            select(Submission)
            .where(Submission.requester_id == user.id)
            .order_by(Submission.submitted_at.desc())
            .limit(8)
        ).all()
    )
    prior_submissions = []
    for row in submissions:
        payload = row.payload or {}
        system = payload.get("aiSystem") or {}
        screening = payload.get("screening") or {}
        business = (payload.get("conditionalInformation") or {}).get("businessValue") or {}
        values = {
            "category": row.category,
            "name": system.get("name") or "",
            "summary": system.get("summary") or "",
            "sensitive": screening.get("data") or "",
            "decision": screening.get("decision") or "",
            "action": screening.get("action") or "",
            **{k: business.get(k) or "" for k in (
                "segment", "valueDriver", "annualValue", "investmentCost", "spendingToDate", "hoursSaved"
            )},
        }
        values = {k: v for k, v in values.items() if v not in (None, "", [])}
        prior_submissions.append(
            {
                "referenceId": row.reference_id,
                "status": row.status,
                "name": values.get("name") or "",
                "category": row.category,
                "summary": values.get("summary") or "",
                "values": values,
                "submittedAt": row.submitted_at.isoformat() if row.submitted_at else None,
            }
        )
    return {"priorSessions": prior_sessions, "priorSubmissions": prior_submissions}


def list_sessions_for(db: Session, user: User) -> list[dict]:
    rows = list(
        db.scalars(
            select(IntakeSession)
            .where(IntakeSession.user_id == user.id)
            .order_by(IntakeSession.updated_at.desc())
            .limit(20)
        ).all()
    )
    out = []
    for row in rows:
        state = row.state or {}
        values = _slot_snapshot(state)
        out.append(
            {
                "id": row.id,
                "status": row.status,
                "name": values.get("name") or "",
                "category": values.get("category") or "",
                "summary": (state.get("slots") or {}).get("summary", {}).get("value") or "",
                "messageCount": len(state.get("transcript") or []),
                "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
                "submissionReference": row.submission_reference,
            }
        )
    return out


def view_session(draft: IntakeSession) -> dict:
    state = draft.state
    values = values_of(state)
    active = active_slots(state)
    pending = [
        _slot_view(slot, state["slots"][slot.id], include_question=True)
        for slot in active
        if state["slots"][slot.id]["status"] == "inferred"
    ]
    nxt = next((slot for slot in active if state["slots"][slot.id]["status"] == "empty"), None)
    confirmed = sum(1 for slot in active if state["slots"][slot.id]["status"] == "confirmed")
    total = len(active)
    screening = {
        "sensitive": values.get("sensitive") or "",
        "decision": values.get("decision") or "",
        "action": values.get("action") or "",
    }
    effective = {key: effective_answer(value) for key, value in screening.items()}
    return {
        "id": draft.id,
        "status": draft.status,
        "description": draft.description,
        "extractor": state.get("extractor") or "keyword",
        "readyToSubmit": draft.status == "active" and not pending and nxt is None and total > 0,
        "progress": {
            "confirmed": confirmed,
            "total": total,
            "percent": int(js_math_round(confirmed / total * 100)) if total else 0,
            "questionsAsked": state.get("asked") or 0,
            "filledFromDescription": sum(
                1
                for slot in active
                if state["slots"][slot.id]["status"] == "confirmed"
                and state["slots"][slot.id]["source"] in ("description", "llm")
            ),
        },
        "pendingConfirmation": pending,
        "nextQuestion": None
        if pending or nxt is None
        else _slot_view(nxt, state["slots"][nxt.id], include_question=True),
        "slots": [_slot_view(slot, state["slots"][slot.id]) for slot in active],
        "summary": state["slots"]["summary"]["value"],
        "flags": flags_for(values),
        "routing": route_for(values),
        "weightProfile": get_weight_profile(effective) if all(effective.values()) else None,
        "methodologyVersion": METHODOLOGY_VERSION,
        "transcript": state.get("transcript") or [],
        "memory": state.get("memory") or {},
        "submissionReference": draft.submission_reference,
    }


def _touch(draft: IntakeSession, state: dict) -> None:
    draft.state = state
    flag_modified(draft, "state")


def _guard_open(draft: IntakeSession) -> None:
    if draft.status != "active":
        raise IntakeError("This request has already been submitted.", 409)


def create_session(db: Session, user: User, description: str, settings: Settings) -> IntakeSession:
    description = description.strip()
    if len(description) < 15:
        raise IntakeError("Describe the request in at least 15 characters.", 422)
    state = initial_state(user.name, user.business_unit, description)
    found, extractor = _extract(description, settings)
    state["extractor"] = extractor
    apply_extractions(state, found)
    _apply_summary(state, found)
    values = values_of(state)
    unit = user.business_unit
    if found:
        intro = (
            f"I read that. Signed in as {user.name} ({unit}) — owner and unit are set. "
            "I'll help fill the rest with short questions. "
            "If you don't know a number, say \"help me estimate\" and we'll work it out."
        )
    else:
        intro = (
            f"Thanks. Signed in as {user.name} ({unit}) — owner and unit are set. "
            "I'll ask short questions to fill the form. "
            "Say \"help me estimate\" anytime for annual value, cost, or hours."
        )
    _say(state, "user", description)
    _say(state, "assistant", intro)
    for flag in _announce(state, values):
        _say(state, "assistant", f"Heads up: {flag['title']}. {flag['why']} This won't stop you from submitting.")
    draft = IntakeSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
        description=description,
        state=state,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def get_owned(db: Session, user: User, session_id: str) -> IntakeSession:
    draft = db.get(IntakeSession, session_id)
    if draft is None or draft.user_id != user.id:
        raise IntakeError("Intake session not found.", 404)
    return draft


def confirm_slots(db: Session, draft: IntakeSession, slot_ids: list[str] | None) -> IntakeSession:
    _guard_open(draft)
    state = draft.state
    active = {slot.id: slot for slot in active_slots(state)}
    targets = slot_ids
    if targets is None:
        targets = [
            slot_id
            for slot_id, slot in active.items()
            if state["slots"][slot_id]["status"] == "inferred"
        ]
    if not targets:
        raise IntakeError("There is nothing waiting to be confirmed.", 422)
    for slot_id in targets:
        if slot_id not in active:
            raise IntakeError(f"'{slot_id}' is not an active question.", 422)
        entry = state["slots"][slot_id]
        if entry["status"] == "empty" or not has_value(SLOTS_BY_ID[slot_id], entry["value"]):
            raise IntakeError(f"'{active[slot_id].label}' has no value to confirm.", 422)
        entry["status"] = "confirmed"
    _say(state, "user", "Looks right")
    _after_change(state)
    _touch(draft, state)
    db.commit()
    db.refresh(draft)
    return draft


def answer_slot(db: Session, draft: IntakeSession, slot_id: str, value) -> IntakeSession:
    _guard_open(draft)
    slot = SLOTS_BY_ID.get(slot_id)
    if slot is None or (slot.auto and slot.id != "summary"):
        raise IntakeError("That field cannot be answered directly.", 422)
    state = draft.state
    if slot.id != "summary" and not any(active.id == slot_id for active in active_slots(state)):
        raise IntakeError(f"'{slot.label}' is not part of this request yet.", 422)
    try:
        cleaned = validate_answer(slot, value)
    except ValueError as exc:
        raise IntakeError(str(exc), 422) from exc
    entry = state["slots"][slot_id]
    was_empty = entry["status"] == "empty"
    entry["value"] = cleaned
    entry["status"] = "confirmed"
    entry["source"] = "you"
    entry["why"] = ""
    if was_empty:
        state["asked"] = int(state.get("asked") or 0) + 1
    _say(state, "user", display_value(slot, cleaned))
    _after_change(state)
    _touch(draft, state)
    db.commit()
    db.refresh(draft)
    return draft


def add_message(db: Session, draft: IntakeSession, text: str, settings: Settings) -> IntakeSession:
    _guard_open(draft)
    text = text.strip()
    if not text:
        raise IntakeError("Enter a message first.", 422)
    state = draft.state
    user = draft.user
    if user is None:
        user = db.get(User, draft.user_id)
    memory = build_user_memory(db, user, exclude_session_id=draft.id) if user else {
        "priorSessions": [],
        "priorSubmissions": [],
    }
    state["memory"] = {
        "priorSessionCount": len(memory.get("priorSessions") or []),
        "priorSubmissionCount": len(memory.get("priorSubmissions") or []),
    }

    draft.description = (draft.description + "\n" + text).strip()
    # Keep an LLM summary stable; only refresh the offline auto rewrite when needed.
    if state["slots"]["summary"]["source"] == "auto":
        set_summary(state, make_summary(draft.description), source="auto")

    _say(state, "user", text)
    applied: list[str] = []
    reply = ""
    recall_meta = None

    # ---- Guided form helper (short discovery questions → estimate field) ----
    helper_handled = False
    if state.get("helper"):
        result = continue_helper(state, text)
        reply = result.get("reply") or ""
        if result.get("extraction"):
            applied = apply_extractions(
                state,
                result["extraction"],
                allow_update=True,
                mark_confirmed=True,
            )
        helper_handled = True
    else:
        empty_ids = empty_helper_ids(state)
        target = detect_helper_slot(text, empty_ids)
        if target and (wants_help(text) or target in empty_ids):
            # If user already pasted answers with the ask, start then continue in one turn.
            reply = start_helper(state, target)
            # Same message may already include answers under the help request.
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if wants_help(text) and len(lines) >= 2:
                answer_blob = "\n".join(lines[1:] if wants_help(lines[0]) else lines)
                if answer_blob.strip() and (
                    re.search(r"\d", answer_blob) or len(answer_blob.splitlines()) >= 1
                ):
                    result = continue_helper(state, answer_blob)
                    reply = result.get("reply") or reply
                    if result.get("extraction"):
                        applied = apply_extractions(
                            state,
                            result["extraction"],
                            allow_update=True,
                            mark_confirmed=True,
                        )
            helper_handled = True
            recall_meta = {"helper": target}

    if not helper_handled:
        transcript = list(state.get("transcript") or [])
        current_values = _slot_snapshot(state)
        empty_ids = empty_helper_ids(state)

        agent = llm_agent_turn(
            latest_message=text,
            transcript=transcript[:-1],
            current_values=current_values,
            memory=memory,
            settings=settings,
            empty_helper_ids=empty_ids,
        )

        if agent:
            reply = (agent.get("reply") or "").strip()
            if agent.get("recallNote"):
                recall_meta = {"recallNote": agent["recallNote"]}
            if agent.get("startHelper") and agent["startHelper"] in HELPERS:
                reply = start_helper(state, agent["startHelper"])
                helper_handled = True
                recall_meta = {**(recall_meta or {}), "helper": agent["startHelper"]}
            elif agent.get("extractions"):
                applied = apply_extractions(
                    state,
                    agent["extractions"],
                    allow_update=True,
                    mark_confirmed=True,
                )
                state["extractor"] = "llm"

        if not helper_handled and not applied:
            reused = match_prior_for_reuse(text, memory) if wants_recall(text) else None
            if reused and reused.get("values"):
                prior_found = {
                    slot_id: {
                        "value": value,
                        "why": f"reused from {reused.get('referenceId') or reused.get('sessionId') or 'prior request'}",
                        "source": "you",
                    }
                    for slot_id, value in (reused.get("values") or {}).items()
                    if slot_id in SLOTS_BY_ID and not SLOTS_BY_ID[slot_id].profile
                }
                applied = apply_extractions(
                    state,
                    prior_found,
                    allow_update=True,
                    mark_confirmed=True,
                )
                if not reply:
                    ref = reused.get("referenceId") or reused.get("name") or "your earlier request"
                    reply = (
                        f"I reused details from {ref}"
                        + (f": {', '.join(SLOTS_BY_ID[i].label for i in applied)}." if applied else ".")
                    )
                recall_meta = {
                    **(recall_meta or {}),
                    "reusedFrom": reused.get("referenceId") or reused.get("sessionId"),
                }
            else:
                intent = offline_intent_extractions(text)
                if intent:
                    applied = apply_extractions(
                        state,
                        intent,
                        allow_update=True,
                        mark_confirmed=True,
                    )
                from_message, msg_extractor = _extract(text, settings)
                for slot_id in apply_extractions(
                    state,
                    from_message,
                    allow_update=True,
                    mark_confirmed=True,
                ):
                    if slot_id not in applied:
                        applied.append(slot_id)
                found, extractor = _extract(draft.description, settings)
                state["extractor"] = msg_extractor if applied else extractor
                for slot_id in apply_extractions(state, found, allow_update=False):
                    if slot_id not in applied:
                        applied.append(slot_id)

        if not reply:
            if applied:
                labels = ", ".join(SLOTS_BY_ID[slot_id].label for slot_id in applied)
                reply = f"Updated: {labels}."
                nxt = next_empty_helper_slot(empty_helper_ids(state))
                if nxt and nxt in HELPERS:
                    reply += f" Next we can fill {HELPERS[nxt]['label']} — say \"help me estimate\" if you don't know it yet."
            else:
                nxt = next_empty_helper_slot(empty_helper_ids(state))
                if nxt and wants_help(text):
                    reply = start_helper(state, nxt)
                elif nxt:
                    reply = (
                        f"Noted. For {HELPERS[nxt]['label']}, tell me the value "
                        f"or say \"help me estimate\" and I'll ask a few short questions."
                    )
                else:
                    reply = "Noted — saved to the conversation and your description."

    _say(state, "assistant", reply, meta=recall_meta)
    _after_change(state)
    _touch(draft, state)
    db.commit()
    db.refresh(draft)
    return draft


def _after_change(state: dict) -> None:
    values = values_of(state)
    for flag in _announce(state, values):
        _say(
            state,
            "assistant",
            f"Heads up: {flag['title']}. {flag['why']} This won't stop you from submitting.",
        )
    active = active_slots(state)
    pending = any(state["slots"][slot.id]["status"] == "inferred" for slot in active)
    empty = any(state["slots"][slot.id]["status"] == "empty" for slot in active)
    if pending or empty:
        state["completionNoted"] = False
        return
    if not state.get("completionNoted"):
        filled = sum(
            1
            for slot in active
            if state["slots"][slot.id]["source"] in ("description", "llm")
            and state["slots"][slot.id]["status"] == "confirmed"
        )
        _say(
            state,
            "assistant",
            (
                f"That's everything I need. I filled {filled} of {len(active)} answers "
                f"from your description and asked you {state.get('asked') or 0}."
            ),
        )
        state["completionNoted"] = True


def reset_slot(db: Session, draft: IntakeSession, slot_id: str) -> IntakeSession:
    """Clear one answer so the requester can change an inferred value."""
    _guard_open(draft)
    slot = SLOTS_BY_ID.get(slot_id)
    if slot is None or slot.auto or slot.profile:
        raise IntakeError("That field cannot be cleared.", 422)
    state = draft.state
    state["slots"][slot_id] = empty_slot_state(slot)
    state["completionNoted"] = False
    _touch(draft, state)
    db.commit()
    db.refresh(draft)
    return draft


def examples() -> list[str]:
    return list(EXAMPLES)
