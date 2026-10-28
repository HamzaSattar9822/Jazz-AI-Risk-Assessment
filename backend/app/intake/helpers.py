"""Guided helper probes so AIRA can fill form fields with short questions."""

from __future__ import annotations

import re
from typing import Any, Callable

from app.intake.catalog import SEGMENTS, SLOTS_BY_ID, VALUE_DRIVERS

_HELP_RE = re.compile(
    r"\b(don'?t know|do not know|not sure|unsure|help me|can you (help|estimate|calculate)|"
    r"how (do|can) i|no idea|rough(ly)?|guess|estimate|calculate|figure out|"
    r"what should|need help|walk me through|let'?s (calculate|figure)|together)\b",
    re.I,
)
_CANCEL_RE = re.compile(r"\b(skip|cancel|stop|never ?mind|i('ll| will) (enter|type|fill) it)\b", re.I)
_DIRECT_RE = re.compile(
    r"(?:(?:value|amount|cost|roi|estimate|answer|it)\s*(?:is|=|:)\s*|"
    r"(?:use|set(?:\s+it)?\s+to)\s+)"
    r"[\$]?\s*([\d,]+\.?\d*%?(?:\s*(?:USD|hours?(?:\s*/\s*year)?)?)?|"
    r"Yes|No|[A-Za-z][A-Za-z0-9 \-/]{2,40})",
    re.I,
)
_NUM = re.compile(r"(\d+(?:[.,]\d+)?)")


def wants_help(text: str) -> bool:
    return bool(_HELP_RE.search(text or ""))


def _first_number(text: str, default: float | None = None) -> float | None:
    m = _NUM.search(text or "")
    if not m:
        return default
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return default


def _pct(text: str, default: float = 30.0) -> float:
    n = _first_number(text, default)
    if n is None:
        return default
    return min(max(n, 0.0), 100.0)


def _money(n: float) -> str:
    if n >= 1000:
        return str(int(round(n / 100.0) * 100))
    return str(int(round(n)))


def _estimate_annual_value(answers: dict[str, str]) -> tuple[str, str]:
    queries = _first_number(answers.get("q1", ""), 0) or 0
    nums = [float(x.replace(",", "")) for x in _NUM.findall(answers.get("q2", ""))]
    people = nums[0] if nums else 0.0
    hours = nums[1] if len(nums) >= 2 else (_first_number(answers.get("q2", ""), 0) or 0)
    if len(nums) == 1:
        # Single number in q2 — treat as people if phrasing mentions people, else hours.
        q2 = answers.get("q2", "").lower()
        if any(w in q2 for w in ("people", "employee", "staff", "agent", "person")):
            people, hours = nums[0], 5.0
        else:
            people, hours = 1.0, nums[0]
    pct = _pct(answers.get("q3", ""), 40.0)
    monthly_cost = _first_number(answers.get("q4", ""), 0) or 0
    gain = (answers.get("q5", "") or "").lower()

    annual_cost_save = monthly_cost * 12 * (pct / 100.0)
    annual_hours = (
        people * hours * 52 * (pct / 100.0)
        if people and hours
        else queries * 0.25 * 12 * (pct / 100.0)
    )
    productivity = annual_hours * 25
    total = max(annual_cost_save, productivity, queries * 2 * 12 * (pct / 100.0), 1000.0)
    if any(w in gain for w in ("service", "experience", "cx")):
        total *= 1.1
    note = (
        f"rough estimate from ~{int(queries)} monthly queries, "
        f"{pct:.0f}% automation, and your cost/effort inputs"
    )
    return _money(total), note


def _estimate_investment(answers: dict[str, str]) -> tuple[str, str]:
    people = _first_number(answers.get("q1", ""), 2) or 2
    months = _first_number(answers.get("q2", ""), 3) or 3
    vendor = _first_number(answers.get("q3", ""), 0) or 0
    total = people * months * 4000 + vendor
    return _money(total), f"estimate from {people:g} people × {months:g} months + vendor {vendor:g}"


def _estimate_hours(answers: dict[str, str]) -> tuple[str, str]:
    people = _first_number(answers.get("q1", ""), 1) or 1
    hours_week = _first_number(answers.get("q2", ""), 5) or 5
    pct = _pct(answers.get("q3", ""), 50.0)
    annual = people * hours_week * 52 * (pct / 100.0)
    return f"{int(round(annual))} hours / year", (
        f"from {people:g} people, {hours_week:g} h/week, {pct:.0f}% automatable"
    )


def _estimate_spending(answers: dict[str, str]) -> tuple[str, str]:
    spent = _first_number(answers.get("q1", ""), 0)
    if spent is None:
        return "0", "no spend stated; defaulted to 0"
    return _money(spent), "from amount spent so far"


def _pick_segment(answers: dict[str, str]) -> tuple[str, str]:
    t = " ".join(answers.values()).lower()
    if any(x in t for x in ("customer", "consumer", "subscriber", "public", "billing")):
        return "Consumer-Facing AI", "from audience described"
    if any(x in t for x in ("enterprise", "b2b", "corporate client")):
        return "Enterprise AI", "from audience described"
    if any(x in t for x in ("employee", "internal", "ops", "back office", "finance team")):
        return "Internal Operations", "from audience described"
    if "corporate" in t:
        return "Corporate AI", "from audience described"
    return "Other", "from short description"


def _pick_value_driver(answers: dict[str, str]) -> tuple[str, str]:
    t = " ".join(answers.values()).lower()
    mapping = [
        (("revenue", "sales", "uplift"), "Revenue Uplift"),
        (("cost", "save money", "reduc"), "Cost Reduction"),
        (("customer", "experience", "cx", "nps", "service"), "Customer Experience"),
        (("govern", "risk", "compliance", "audit"), "Governance"),
        (("efficien", "faster", "throughput"), "Efficiency"),
        (("productiv", "time", "fte", "hours", "free"), "Productivity"),
    ]
    for keys, label in mapping:
        if any(k in t for k in keys):
            return label, "from the outcome you described"
    return "Productivity", "defaulted to Productivity"


def _yes_no_from_answer(answers: dict[str, str]) -> tuple[str, str]:
    t = " ".join(answers.values()).lower()
    if re.search(r"\b(no|none|not really|n)\b", t):
        return "No", "from your answer"
    return "Yes", "from your answer"


HELPERS: dict[str, dict[str, Any]] = {
    "annualValue": {
        "label": "estimated annual value",
        "cue": "Answer these and I'll estimate annual savings, productivity gains, and operating cost impact for the form.",
        "questions": [
            ("q1", "How many queries or cases do you handle each month?"),
            ("q2", "How many people handle them, and about how many hours per week each?"),
            ("q3", "What percentage could the AI resolve or speed up?"),
            ("q4", "Rough monthly staff or vendor cost to handle this today (USD)?"),
            ("q5", "Main gain: cut costs, free employee time, or improve service?"),
        ],
        "estimate": _estimate_annual_value,
    },
    "investmentCost": {
        "label": "estimated investment",
        "cue": "Share build effort and vendor cost and I'll estimate investment for the form.",
        "questions": [
            ("q1", "How many people will build or implement it?"),
            ("q2", "For how many months?"),
            ("q3", "Any vendor or licence cost (USD), or 0?"),
        ],
        "estimate": _estimate_investment,
    },
    "hoursSaved": {
        "label": "hours saved",
        "cue": "Share effort today and I'll estimate annual hours saved.",
        "questions": [
            ("q1", "How many people do this work today?"),
            ("q2", "Hours per week each on this work?"),
            ("q3", "What percentage could AI take or speed up?"),
        ],
        "estimate": _estimate_hours,
    },
    "spendingToDate": {
        "label": "spending to date",
        "cue": "Tell me spend so far and I'll put it on the form.",
        "questions": [
            ("q1", "How much has been spent so far (USD)? Use 0 if none."),
        ],
        "estimate": _estimate_spending,
    },
    "segment": {
        "label": "segment",
        "cue": "Tell me who it serves and I'll set the segment.",
        "questions": [
            ("q1", "Who is this mainly for: customers, employees, enterprise clients, or corporate teams?"),
        ],
        "estimate": _pick_segment,
        "allowed": list(SEGMENTS),
    },
    "valueDriver": {
        "label": "value driver",
        "cue": "Tell me the main outcome and I'll set the value driver.",
        "questions": [
            ("q1", "Main outcome: productivity, revenue, cost reduction, customer experience, efficiency, or governance?"),
        ],
        "estimate": _pick_value_driver,
        "allowed": list(VALUE_DRIVERS),
    },
    "sensitive": {
        "label": "sensitive information",
        "cue": "One yes/no sets the sensitive-data field.",
        "questions": [
            ("q1", "Will it use customer, employee, financial, or confidential data? Yes or No."),
        ],
        "estimate": _yes_no_from_answer,
    },
    "decision": {
        "label": "decision impact",
        "cue": "One yes/no sets whether it affects decisions.",
        "questions": [
            ("q1", "Will outputs affect eligibility, pricing, ranking, credit, or approvals? Yes or No."),
        ],
        "estimate": _yes_no_from_answer,
    },
    "action": {
        "label": "actions / messaging",
        "cue": "One yes/no sets whether it can act or talk to people.",
        "questions": [
            ("q1", "Will it talk to people directly or update systems on its own? Yes or No."),
        ],
        "estimate": _yes_no_from_answer,
    },
}

HELPER_ORDER = (
    "segment",
    "valueDriver",
    "annualValue",
    "investmentCost",
    "spendingToDate",
    "hoursSaved",
    "sensitive",
    "decision",
    "action",
)


def detect_helper_slot(text: str, empty_slot_ids: list[str]) -> str | None:
    """Pick which field the user wants help with."""
    t = (text or "").lower()
    aliases = [
        ("annualValue", r"annual value|roi|value estimate|business case|savings|worth"),
        ("investmentCost", r"investment|build cost|implementation cost|budget"),
        ("hoursSaved", r"hours saved|time saved|fte"),
        ("spendingToDate", r"spent|spending to date|spent so far"),
        ("segment", r"\bsegment\b|who (is|will) it (serve|for)"),
        ("valueDriver", r"value driver|main benefit|outcome"),
        ("sensitive", r"sensitive|personal data|confidential"),
        ("decision", r"\bdecision\b|eligib|approv"),
        ("action", r"\baction\b|send messages|update records|chatbot replies"),
    ]
    for slot_id, pattern in aliases:
        if re.search(pattern, t) and slot_id in HELPERS:
            return slot_id
    if wants_help(t):
        for slot_id in HELPER_ORDER:
            if slot_id in empty_slot_ids and slot_id in HELPERS:
                return slot_id
    return None


def format_helper_prompt(slot_id: str) -> str:
    spec = HELPERS[slot_id]
    body = "\n".join(f"- {q}" for _, q in spec["questions"])
    return f"{body}\n\n{spec['cue']}"


def start_helper(state: dict, slot_id: str) -> str:
    if slot_id not in HELPERS:
        return "I can help fill the form. Which field do you want to work on?"
    state["helper"] = {"slotId": slot_id, "answers": {}}
    return format_helper_prompt(slot_id)


def next_empty_helper_slot(empty_ids: list[str]) -> str | None:
    for slot_id in HELPER_ORDER:
        if slot_id in empty_ids and slot_id in HELPERS:
            return slot_id
    return None


def continue_helper(state: dict, text: str) -> dict:
    """
    Process a helper turn.
    Returns {done, reply, extraction?}
    """
    helper = state.get("helper") or {}
    slot_id = helper.get("slotId")
    if not slot_id or slot_id not in HELPERS:
        state.pop("helper", None)
        return {"done": True, "reply": "Let's continue with the form."}

    if _CANCEL_RE.search(text or ""):
        state.pop("helper", None)
        label = SLOTS_BY_ID[slot_id].label if slot_id in SLOTS_BY_ID else slot_id
        return {
            "done": True,
            "reply": f"Okay — enter {label} when you have it, or say \"help me estimate\" anytime.",
        }

    direct = _DIRECT_RE.search(text or "")
    if direct and not wants_help(text):
        raw = direct.group(1).strip()
        state.pop("helper", None)
        label = SLOTS_BY_ID[slot_id].label if slot_id in SLOTS_BY_ID else slot_id
        return {
            "done": True,
            "reply": f"Got it. I set {label} to {raw}.",
            "extraction": {
                slot_id: {"value": raw, "why": "value you provided", "source": "you"},
            },
        }

    spec = HELPERS[slot_id]
    questions = spec["questions"]
    answers = dict(helper.get("answers") or {})
    unanswered = [(k, q) for k, q in questions if k not in answers]

    if not answers and len(questions) > 1:
        parts = [p.strip(" -•\t") for p in re.split(r"[\n;]+", text or "") if p.strip()]
        numbered = re.findall(
            r"(?:^|\n)\s*(?:\d+[.)]|[-•])\s*(.+?)(?=(?:\n\s*(?:\d+[.)]|[-•])\s*)|$)",
            text or "",
            re.S,
        )
        chunks = [c.strip() for c in numbered if c.strip()] or parts
        if len(chunks) >= len(questions):
            for (key, _), part in zip(questions, chunks):
                answers[key] = part
        else:
            answers[questions[0][0]] = (text or "").strip()
    elif unanswered:
        answers[unanswered[0][0]] = (text or "").strip()
    else:
        answers[questions[-1][0]] = (text or "").strip()

    still = [(k, q) for k, q in questions if k not in answers or not str(answers.get(k) or "").strip()]
    if still:
        helper["answers"] = answers
        state["helper"] = helper
        rest = "\n".join(f"- {q}" for _, q in still)
        return {
            "done": False,
            "reply": f"Thanks — a bit more helps.\n{rest}\n\n{spec['cue']}",
        }

    estimate: Callable[..., tuple[str, str]] = spec["estimate"]
    value, why = estimate(answers)
    allowed = spec.get("allowed")
    if allowed and value not in allowed:
        value = allowed[0]
    state.pop("helper", None)
    label = SLOTS_BY_ID[slot_id].label if slot_id in SLOTS_BY_ID else slot_id
    return {
        "done": True,
        "reply": f"Got it. I set {label} to {value} ({why}).",
        "extraction": {
            slot_id: {"value": value, "why": why, "source": "you"},
        },
    }


def empty_helper_ids(state: dict) -> list[str]:
    out = []
    for slot in active_slots_safe(state):
        entry = (state.get("slots") or {}).get(slot.id) or {}
        if entry.get("status") == "empty":
            out.append(slot.id)
    return out


def active_slots_safe(state: dict):
    from app.intake.catalog import active_slots

    return active_slots(state)
