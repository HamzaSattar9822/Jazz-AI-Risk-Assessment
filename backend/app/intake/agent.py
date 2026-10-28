"""Memory-aware AIRA agent turn: reply + optional field updates from chat history."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.config import Settings
from app.intake.catalog import SLOTS_BY_ID, validate_answer
from app.intake.llm import _parse_content, _slot_guide

logger = logging.getLogger(__name__)

_RECALL_HINT = re.compile(
    r"\b(previous|prior|earlier|last\s+time|same\s+as|like\s+(the|my|our)|"
    r"before|already\s+(said|told|mentioned)|remember|recall|reuse|"
    r"from\s+(my|the)\s+(last|previous)|again)\b",
    re.I,
)


def wants_recall(text: str) -> bool:
    return bool(_RECALL_HINT.search(text or ""))


def _accept(slot_id: str, raw_value, why: str) -> dict | None:
    slot = SLOTS_BY_ID.get(slot_id)
    if slot is None or slot.auto or slot.profile:
        return None
    try:
        value = validate_answer(slot, raw_value)
    except ValueError:
        return None
    return {
        "value": value,
        "why": str(why or "").strip()[:240] or "from conversation memory",
        "source": "llm",
    }


def llm_agent_turn(
    *,
    latest_message: str,
    transcript: list[dict],
    current_values: dict[str, Any],
    memory: dict[str, Any],
    settings: Settings,
    empty_helper_ids: list[str] | None = None,
) -> dict | None:
    """Ask the model for a reply and any slot updates, using chat + prior memory."""
    if not settings.llm_configured:
        return None

    history = []
    for turn in (transcript or [])[-24:]:
        role = turn.get("role") or "user"
        text = str(turn.get("text") or "").strip()
        if not text:
            continue
        history.append({"role": "assistant" if role == "assistant" else "user", "content": text[:1200]})

    system = (
        "You are AIRA, JazzWorld's AI Risk Assistant. Your job is to help fill the intake form. "
        "Be brief. Prefer short discovery questions over long explanations. "
        "When the user does not know a number (annual value, investment, hours), set startHelper "
        "to that field id instead of guessing. Closing line style: "
        "\"If you tell me X, I can estimate Y for the form.\" "
        "Use priorMemory when the user refers to earlier requests. Never invent facts. "
        "For choice fields, copy an allowed value exactly. "
        "Reply with JSON only. "
        'Schema: {"reply":"short message","extractions":[{"id":"...","value":"...","why":"..."}],'
        '"startHelper":"optional field id like annualValue|investmentCost|hoursSaved|segment|valueDriver|spendingToDate|sensitive|decision|action",'
        '"recallNote":"optional"}.'
    )
    user_payload = {
        "latestMessage": latest_message[:4000],
        "currentValues": current_values,
        "emptyHelperFields": empty_helper_ids or [],
        "priorMemory": memory,
        "fields": _slot_guide(),
        "rules": [
            "Keep reply under 40 words. Mention only the field(s) changed in this turn — never restate the whole form.",
            "If the user discusses one field, extract and confirm only that field.",
            "If user says don't know / help estimate a helper field, set startHelper and keep reply minimal.",
            "Update only fields clearly supported by latestMessage or recalled prior data.",
            "category: AI For Us | AI By Us | AI Against Us only.",
            "Yes/No fields must be exactly Yes or No.",
            "No em dashes.",
        ],
    }
    payload = {
        "model": settings.llm_model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system},
            *history,
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
    }
    if settings.llm_json_mode:
        payload["response_format"] = {"type": "json_object"}

    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"

    try:
        response = httpx.post(
            url,
            headers=headers,
            json=payload,
            timeout=settings.llm_timeout_seconds,
            verify=settings.llm_verify_ssl,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = _parse_content(content)
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("AIRA agent turn failed: %s", exc)
        return None

    if not isinstance(parsed, dict):
        return None

    found = {}
    for item in parsed.get("extractions") or []:
        if not isinstance(item, dict):
            continue
        accepted = _accept(str(item.get("id") or ""), item.get("value"), item.get("why") or "")
        if accepted:
            found[str(item["id"])] = accepted

    reply = str(parsed.get("reply") or "").strip()
    recall_note = str(parsed.get("recallNote") or "").strip()
    start_helper_id = str(parsed.get("startHelper") or "").strip()
    allowed_helpers = {
        "annualValue",
        "investmentCost",
        "hoursSaved",
        "spendingToDate",
        "segment",
        "valueDriver",
        "sensitive",
        "decision",
        "action",
    }
    if start_helper_id not in allowed_helpers:
        start_helper_id = ""
    return {
        "reply": reply,
        "extractions": found,
        "recallNote": recall_note,
        "startHelper": start_helper_id or None,
    }


def offline_intent_extractions(message: str) -> dict[str, dict]:
    """Lightweight chat intents when the LLM is unavailable."""
    raw = (message or "").strip()
    if not raw:
        return {}
    out: dict[str, dict] = {}
    m = re.search(
        r"(?:(?:change|update|set|rename)\s+(?:the\s+)?(?:name|title|use\s*case)\s+(?:to|as|:)\s*|"
        r"(?:call|name)\s+it\s+)[\"']?([^\"'\n.]+)[\"']?",
        raw,
        re.I,
    )
    if not m:
        m = re.search(r"^(?:name|title)\s*[:=]\s*[\"']?([^\"'\n.]+)[\"']?", raw, re.I)
    if m:
        out["name"] = {
            "value": m.group(1).strip(),
            "why": "name from your chat message",
            "source": "you",
        }
    t = raw.lower()
    def yn(slot_id: str, yes_re: str, no_re: str) -> None:
        if re.search(no_re, t, re.I):
            out[slot_id] = {"value": "No", "why": "from your chat message", "source": "you"}
        elif re.search(yes_re, t, re.I):
            out[slot_id] = {"value": "Yes", "why": "from your chat message", "source": "you"}

    yn(
        "sensitive",
        r"(sensitive|personal data).{0,40}(yes|true)| (yes|it does).{0,40}sensitive",
        r"(no|not|doesn't|does not|won't).{0,40}sensitive|sensitive.{0,20}(no|false)",
    )
    yn(
        "decision",
        r"(decision|affect).{0,40}(yes|true)|yes.{0,40}decision",
        r"(no|not|doesn't|won't).{0,40}decision|decision.{0,20}(no|false)",
    )
    yn(
        "action",
        r"(action|send|update).{0,40}(yes|true|can|will)|yes.{0,40}(act|send)",
        r"(no|not|cannot|can't|won't).{0,40}(act|action|send)|action.{0,20}(no|false)",
    )
    if re.search(r"\b(change|set|update|category|type)\b", t) and re.search(r"\bfor\s+us\b", t):
        out["category"] = {"value": "AI For Us", "why": "category from your chat", "source": "you"}
    if re.search(r"\b(change|set|update|category|type)\b", t) and re.search(r"\bby\s+us\b", t):
        out["category"] = {"value": "AI By Us", "why": "category from your chat", "source": "you"}
    if re.search(r"\b(change|set|update|category|type)\b", t) and re.search(r"\bagainst\s+us\b", t):
        out["category"] = {"value": "AI Against Us", "why": "category from your chat", "source": "you"}

    # Single-field clarifications: map explicit chat updates without reopening the form.
    segment_map = [
        (r"consumer(?:[-\s]?facing)?(?:\s+ai)?", "Consumer-Facing AI"),
        (r"corporate(?:\s+ai)?", "Corporate AI"),
        (r"enterprise(?:\s+ai)?", "Enterprise AI"),
        (r"internal(?:\s+operations?)?", "Internal Operations"),
        (r"\bother\b", "Other"),
    ]
    if re.search(r"\bsegment\b", t):
        for pattern, value in segment_map:
            if re.search(pattern, t, re.I):
                out["segment"] = {
                    "value": value,
                    "why": "segment from your chat message",
                    "source": "you",
                }
                break

    driver_map = [
        (r"productivity", "Productivity"),
        (r"revenue", "Revenue Uplift"),
        (r"cost\s*reduction|cut costs|saving cost", "Cost Reduction"),
        (r"customer experience|cx\b", "Customer Experience"),
        (r"efficiency", "Efficiency"),
        (r"governance", "Governance"),
    ]
    if re.search(r"value\s*driver|driver", t):
        for pattern, value in driver_map:
            if re.search(pattern, t, re.I):
                out["valueDriver"] = {
                    "value": value,
                    "why": "value driver from your chat message",
                    "source": "you",
                }
                break

    def money_field(slot_id: str, labels: str) -> None:
        m_money = re.search(
            rf"(?:(?:change|update|set)\s+)?(?:the\s+)?(?:{labels})\s*(?:to|as|:|=)\s*"
            rf"((?:USD\s*)?\$?\s?\d[\d,]*(?:\.\d+)?(?:\s*USD)?)",
            raw,
            re.I,
        )
        if m_money:
            out[slot_id] = {
                "value": m_money.group(1).replace(" ", "").strip(),
                "why": f"{slot_id} from your chat message",
                "source": "you",
            }

    money_field("annualValue", r"annual value|roi|value|benefit")
    money_field("investmentCost", r"investment(?:\s+cost)?|capex|budget|project cost|total cost")
    money_field("spendingToDate", r"spending(?:\s+to\s+date)?|spent(?:\s+to\s+date|\s+so\s+far)?")

    m_hours = re.search(
        r"(?:(?:change|update|set)\s+)?(?:the\s+)?(?:hours?\s*saved|time\s*saved)\s*(?:to|as|:|=)\s*"
        r"([^\n.]+)",
        raw,
        re.I,
    )
    if m_hours:
        out["hoursSaved"] = {
            "value": m_hours.group(1).strip(),
            "why": "hours saved from your chat message",
            "source": "you",
        }

    return out


def match_prior_for_reuse(message: str, memory: dict[str, Any]) -> dict | None:
    """Offline fallback: match prior submission/session by name tokens when user asks to reuse."""
    if not wants_recall(message):
        return None
    text = (message or "").lower()
    best = None
    best_hits = 0
    for row in (memory.get("priorSubmissions") or []) + (memory.get("priorSessions") or []):
        name = str(row.get("name") or "").lower()
        summary = str(row.get("summary") or "").lower()
        hay = f"{name} {summary}"
        tokens = [t for t in re.findall(r"[a-z0-9]{4,}", name) if t not in {"jazz", "with", "from", "that"}]
        hits = sum(1 for t in tokens if t in text) + (1 if name and name in text else 0)
        if "last" in text or "previous" in text or "earlier" in text:
            hits += 1  # prefer most recent when generic recall
        if hits > best_hits:
            best_hits = hits
            best = row
    if best and best_hits > 0:
        return best
    # Generic "same as last" → most recent prior with values
    if wants_recall(message):
        for row in memory.get("priorSubmissions") or memory.get("priorSessions") or []:
            if row.get("values"):
                return row
    return None
