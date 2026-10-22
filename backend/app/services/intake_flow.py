"""Conversational intake session transitions."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.config import Settings
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
    validate_answer,
    values_of,
)
from app.intake.llm import llm_extract
from app.methodology.engine import METHODOLOGY_VERSION, get_weight_profile, js_math_round
from app.models import IntakeSession, User


class IntakeError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code


def _extract(description: str, settings: Settings) -> tuple[dict, str]:
    keyword = keyword_extract(description)
    model = llm_extract(description, settings)
    if not model:
        found = dict(keyword)
        extractor = "keyword"
    else:
        found = dict(keyword)
        found.update(model)
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
    return found, extractor


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


def _say(state: dict, role: str, text: str) -> None:
    state.setdefault("transcript", []).append({"role": role, "text": text})


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
    values = values_of(state)
    unit = user.business_unit
    if found:
        intro = (
            f"I read that. Signed in as {user.name} ({unit}), "
            "so I've filled in the owner and business unit for you."
        )
    else:
        intro = (
            "Thanks. I couldn't pick out much from that, so I'll ask a few short questions. "
            f"Signed in as {user.name} ({unit}), so I've filled in the owner and business unit."
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
    draft.description = (draft.description + "\n" + text).strip()
    if state["slots"]["summary"]["source"] == "auto":
        state["slots"]["summary"]["value"] = make_summary(draft.description)
    # Prefer facts from the latest chat turn so corrections update the live form.
    from_message, msg_extractor = _extract(text, settings)
    applied = apply_extractions(
        state,
        from_message,
        allow_update=True,
        mark_confirmed=True,
    )
    # Still fill any remaining empty slots from the full description.
    found, extractor = _extract(draft.description, settings)
    state["extractor"] = msg_extractor if applied else extractor
    for slot_id in apply_extractions(state, found, allow_update=False):
        if slot_id not in applied:
            applied.append(slot_id)
    _say(state, "user", text)
    if applied:
        labels = ", ".join(SLOTS_BY_ID[slot_id].label for slot_id in applied)
        _say(
            state,
            "assistant",
            f"Updated the form from your message: {labels}. Check the summary on the right.",
        )
    else:
        _say(state, "assistant", "Noted. I added that to your description.")
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
