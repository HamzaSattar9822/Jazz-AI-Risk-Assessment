"""Intake slots, keyword extraction, early flags, and reviewer routing.

The keyword extractor is the offline stand-in shipped in the prototype.
When an LLM is configured, its structured guesses are merged on top.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

BUSINESS_UNITS = [
    "Compliance",
    "CRA",
    "Cybersecurity",
    "Enterprise",
    "Finance",
    "GSM",
    "Internal Audit",
    "JazzCash",
    "JLV",
    "Legal",
    "MMBL",
    "P&O",
    "Strategy",
    "Technology",
    "Teknosys",
]

YNN = ["Yes", "No"]
CATEGORIES = ["AI For Us", "AI By Us", "AI Against Us"]

ACCESS_METHODS = [
    "JazzWorld enterprise / corporate account",
    "Supplier-managed enterprise service",
    "Public / free web service",
    "Individual / personal account",
    "API / system integration",
]
THREAT_TYPES = [
    "Phishing / social engineering",
    "Deepfake / impersonation",
    "Fraud / scam",
    "Malware / cyber attack",
    "Prompt / model abuse",
    "Other",
]
HUMAN_REVIEW = [
    "Always",
    "Sometimes / based on conditions",
    "No - AI output can determine the outcome",
]
AUTONOMY = [
    "Advisory only - it cannot take action",
    "Action requires human approval each time",
    "Can take limited actions within defined rules",
    "Can take actions automatically across a workflow",
]
SEGMENTS = [
    "Consumer-Facing AI",
    "Corporate AI",
    "Enterprise AI",
    "Internal Operations",
    "Other",
]
VALUE_DRIVERS = [
    "Productivity",
    "Revenue Uplift",
    "Cost Reduction",
    "Customer Experience",
    "Efficiency",
    "Governance",
    "Other",
]

EXAMPLES = [
    "We want to roll out Microsoft Copilot for our finance team on enterprise accounts to summarise contracts and draft board reports. It will read confidential contracts and financial figures. The team reviews everything before it is used.",
    'We\'re building a model called "Credit Line Recommender" that scores JazzCash customers and recommends credit limit increases. It will be trained on customer transaction history and hosted on Azure. Analysts review every recommendation before a limit is changed.',
    "We've seen voice-cloned calls impersonating senior executives and asking finance staff to approve urgent payments. We want to assess the risk of AI-enabled deepfake fraud against our employees and payment processes.",
]

_TOOLS = [
    (re.compile(r"microsoft copilot|copilot"), "Microsoft Copilot"),
    (re.compile(r"chatgpt"), "ChatGPT"),
    (re.compile(r"gemini"), "Google Gemini"),
    (re.compile(r"azure openai"), "Azure OpenAI"),
    (re.compile(r"openai"), "OpenAI"),
    (re.compile(r"claude"), "Claude"),
]


def is_on(value) -> bool:
    return value == "Yes"


def effective_answer(value):
    """Normalize screening answers. Legacy 'Not sure' is not offered anymore."""
    if value == "Not sure":
        return "No"
    return value


@dataclass(frozen=True)
class Slot:
    id: str
    group: str
    label: str
    kind: str  # single, multi, text
    question: str = ""
    placeholder: str = ""
    options: tuple = ()
    auto: bool = False
    profile: bool = False
    when: Callable[[dict], bool] | None = None

    @property
    def option_values(self) -> list:
        values = []
        for option in self.options:
            if isinstance(option, tuple):
                values.append(option[0])
            else:
                values.append(option)
        return values

    def option_label(self, value: str) -> str:
        for option in self.options:
            if isinstance(option, tuple) and option[0] == value:
                return option[1]
            if option == value:
                return option
        return value


def _when_for_us(values):
    return values.get("category") == "AI For Us"


def _when_for_us_sensitive(values):
    return values.get("category") == "AI For Us" and is_on(values.get("sensitive"))


def _when_against(values):
    return values.get("category") == "AI Against Us"


def _when_sensitive(values):
    return is_on(values.get("sensitive"))


def _when_decision(values):
    return is_on(values.get("decision"))


def _when_action(values):
    return is_on(values.get("action"))


SLOTS: list[Slot] = [
    Slot(
        "category",
        "about",
        "Type",
        "single",
        question="Which of these is closest to what you want to do?",
        options=(
            ("AI For Us", "Use a tool someone else provides"),
            ("AI By Us", "Build or deploy our own"),
            ("AI Against Us", "Assess a threat against us"),
        ),
    ),
    Slot(
        "name",
        "about",
        "Name",
        "text",
        question="What should we call this request?",
        placeholder="A short name people will recognise",
    ),
    Slot("summary", "about", "Summary", "text", auto=True),
    Slot("owner", "about", "Business owner", "text", profile=True),
    Slot(
        "businessUnit",
        "about",
        "Business unit",
        "single",
        options=tuple(BUSINESS_UNITS),
        profile=True,
    ),
    Slot(
        "segment",
        "value",
        "Segment",
        "single",
        question="Which segment does this AI use case serve?",
        options=tuple(SEGMENTS),
    ),
    Slot(
        "valueDriver",
        "value",
        "Value driver",
        "single",
        question="What is the main value driver for this use case?",
        options=tuple(VALUE_DRIVERS),
    ),
    Slot(
        "annualValue",
        "value",
        "Estimated annual value / ROI",
        "text",
        question="What is the estimated annual value or ROI (USD)?",
        placeholder="e.g. 20000 or 10% ROI",
    ),
    Slot(
        "investmentCost",
        "value",
        "Estimated investment / cost",
        "text",
        question="What is the estimated investment or cost (USD)?",
        placeholder="e.g. 50000",
    ),
    Slot(
        "spendingToDate",
        "value",
        "Spending done to date",
        "text",
        question="How much has been spent to date (USD)?",
        placeholder="e.g. 0 or 12000",
    ),
    Slot(
        "hoursSaved",
        "value",
        "Estimated hours saved (annual)",
        "text",
        question="How many hours do you expect to save each year?",
        placeholder="e.g. 500 hours / year",
    ),
    Slot(
        "sensitive",
        "screen",
        "Sensitive information",
        "single",
        question="Will the AI handle sensitive information, such as customer or employee data, financial details, contracts, or credentials?",
        options=tuple(YNN),
    ),
    Slot(
        "decision",
        "screen",
        "Affects decisions",
        "single",
        question="Will its output affect decisions about people or business outcomes, like eligibility, pricing, ranking, or approvals?",
        options=tuple(YNN),
    ),
    Slot(
        "action",
        "screen",
        "Interacts or acts",
        "single",
        question="Will the AI talk to people directly, or take actions in a system, like sending messages or updating records?",
        options=tuple(YNN),
    ),
    Slot(
        "forTool",
        "more",
        "Tool or service",
        "text",
        question="Which tool or service is it?",
        placeholder="Product or vendor name",
        when=_when_for_us,
    ),
    Slot(
        "forAccess",
        "more",
        "How it is accessed",
        "single",
        question="Because sensitive information is involved: how will people access it?",
        options=tuple(ACCESS_METHODS),
        when=_when_for_us_sensitive,
    ),
    Slot(
        "threatTypes",
        "more",
        "Type of threat",
        "multi",
        question="What kind of AI-enabled threat is this? Choose all that apply.",
        options=tuple(THREAT_TYPES),
        when=_when_against,
    ),
    Slot(
        "dataExternal",
        "more",
        "Data sent to an outside provider",
        "single",
        question="Will any of that information be sent to or processed by an outside provider?",
        options=tuple(YNN),
        when=_when_sensitive,
    ),
    Slot(
        "humanReview",
        "more",
        "Human review",
        "single",
        question="Will a person check the AI's output before a final decision or action?",
        options=tuple(HUMAN_REVIEW),
        when=_when_decision,
    ),
    Slot(
        "autonomy",
        "more",
        "How independently it acts",
        "single",
        question="How independently can it act?",
        options=tuple(AUTONOMY),
        when=_when_action,
    ),
]

SLOTS_BY_ID = {slot.id: slot for slot in SLOTS}
GROUPS = [
    ("about", "About the request"),
    ("value", "Business value"),
    ("screen", "Screening"),
    ("more", "Follow-up details"),
]


def _first(pattern: str, text: str):
    match = re.search(pattern, text)
    return match.group(0) if match else None


def _pick(pairs, text: str) -> list[str]:
    found = []
    for pattern, label in pairs:
        if re.search(pattern, text):
            found.append(label)
    return found


# Scored category signals. Higher score wins; Against > By Us > For Us on ties.
# Cloud/vendor hosting alone must NOT force "AI For Us" when we are building our own.
_CATEGORY_SIGNALS = {
    "AI Against Us": [
        (3, r"phishing|deepfake|impersonat|voice[- ]clon|social engineering"),
        (3, r"\b(ai against us|against us|threat (to|against)|adversar\w*|threat assess)"),
        (2, r"ransomware|malware|jailbreak|prompt injection|cyber[- ]?attack"),
        (2, r"\b(scam|fraud)\b.{0,40}\b(call|email|voice|executive|employee|staff)"),
        (2, r"\b(assess(ing)?|evaluate|monitor).{0,40}\b(threat|risk|attack|deepfake|fraud)"),
        (1, r"\b(threat|attack|abuse|exploit)\b"),
    ],
    "AI By Us": [
        (3, r"\b(we('re| are)?\s+)?(build|building|develop|developing|creating|created)\b"),
        (3, r"\b(train|trained|training|fine-?tun\w*|retrain)\b"),
        (3, r"\b(in[- ]house|our own|internally|custom model|model called|prototype)\b"),
        (2, r"\b(deploy(ing|ed)? (our|an? internal)|internal (ai|model|system|assistant))\b"),
        (2, r"\b(ml model|machine learning|score(?:s|ing)? customers|recommender)\b"),
        (1, r"\b(dataset|labelled data|feature store|model registry)\b"),
    ],
    "AI For Us": [
        (3, r"\b(microsoft copilot|copilot|chatgpt|google gemini|gemini|claude)\b"),
        (3, r"\b(vendor|third[- ]party|saas|off[- ]the[- ]shelf|procure|purchase|licen[cs]e|subscribe)\b"),
        (2, r"\b(roll ?out|adopt(ing|ion)?|buy|bought|supplier (tool|solution|platform))\b"),
        (2, r"\b(enterprise (account|licence|license)|corporate account)\b"),
        (1, r"\b(openai api|azure openai)\b(?!.{0,80}\b(build|building|train|trained|our own|in[- ]house))"),
    ],
}


def classify_category(description: str) -> dict | None:
    """Deterministic category pick for AI For Us / By Us / Against Us."""
    text = (description or "").lower()
    if not text.strip():
        return None
    scores = {label: 0 for label in _CATEGORY_SIGNALS}
    hits = {label: [] for label in _CATEGORY_SIGNALS}
    for label, rules in _CATEGORY_SIGNALS.items():
        for weight, pattern in rules:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                scores[label] += weight
                hits[label].append(match.group(0))
    # Building our own on Azure/OpenAI is still By Us, not vendor adoption.
    if scores["AI By Us"] and re.search(
        r"\b(hosted on|hosting on|using|via)\s+(azure|aws|gcp|openai|vertex)",
        text,
    ):
        scores["AI For Us"] = max(0, scores["AI For Us"] - 2)
    best = max(scores.values())
    if best <= 0:
        return None
    # Stable tie-break: threat assessment first, then build, then buy.
    for label in ("AI Against Us", "AI By Us", "AI For Us"):
        if scores[label] == best:
            tip = hits[label][0] if hits[label] else label
            return {"value": label, "why": f"category signals point to {label} (e.g. “{tip}”)"}
    return None


def _infer_category(text, _raw):
    return classify_category(text)


def _infer_name(_text, raw):
    match = re.search(
        r"(?:called|named)\s+[\"“']([^\"”']+)[\"”']",
        raw,
        re.IGNORECASE,
    ) or re.search(r"[\"“]([^\"”]{4,50})[\"”]", raw)
    if not match:
        return None
    return {"value": match.group(1), "why": "you named it"}


def _infer_sensitive(text, _raw):
    if re.search(r"no (personal|sensitive|customer) data|public data only|non-?sensitive", text):
        return {"value": "No", "why": "you said no sensitive data"}
    match = _first(
        r"customer|subscriber|personal|cnic|employee|salary|payment|financial|billing|account|kyc|password|credential|confidential|contract|transaction|health",
        text,
    )
    if match:
        return {"value": "Yes", "why": f"mentions “{match}”"}
    return None


def _infer_decision(text, _raw):
    match = _first(
        r"eligib\w*|credit (limit|score|line)|scor(e|es|ing)|reject\w*|shortlist\w*|rank(s|ing)?\b|prioriti[sz]\w*|pricing|recommend\w*|churn|collections",
        text,
    )
    if match:
        return {"value": "Yes", "why": f"mentions “{match}”"}
    return None


def _infer_action(text, _raw):
    match = _first(
        r"chatbot|customer-facing|automatically|ai agent|agentic|updat\w+ (the )?(crm|records?)|trigger\w*|initiat\w+|sends? (emails?|sms|messages?)",
        text,
    )
    if match:
        return {"value": "Yes", "why": f"mentions “{match}”"}
    return None


def _infer_tool(text, _raw):
    for pattern, label in _TOOLS:
        if pattern.search(text):
            return {"value": label, "why": "named in your description"}
    return None


def _infer_access(text, _raw):
    if re.search(r"enterprise|corporate account|business account", text):
        return {
            "value": "JazzWorld enterprise / corporate account",
            "why": "mentions enterprise accounts",
        }
    if re.search(r"personal account|free version|public chatgpt", text):
        return {
            "value": "Individual / personal account",
            "why": "mentions personal or free access",
        }
    return None


def _infer_threats(text, _raw):
    found = _pick(
        [
            (r"phishing|social engineering", "Phishing / social engineering"),
            (r"deepfake|impersonat|voice[- ]clon", "Deepfake / impersonation"),
            (r"fraud|scam", "Fraud / scam"),
            (r"malware|ransomware|cyber attack", "Malware / cyber attack"),
            (r"prompt injection|jailbreak|model abuse", "Prompt / model abuse"),
        ],
        text,
    )
    if not found:
        return None
    return {"value": found, "why": "from the threats you described"}


def _infer_external(text, _raw):
    if re.search(r"on-?prem|self-hosted|in-house servers|jazzworld-managed", text):
        return {"value": "No", "why": "you said it stays in-house"}
    match = _first(r"openai|chatgpt|azure|aws|google|gemini|copilot|vendor|third-party|saas|external", text)
    if match:
        return {"value": "Yes", "why": f"mentions “{match}”"}
    return None


def _infer_review(text, _raw):
    if re.search(
        r"without human|fully automat\w*|no human|automatically (decides?|approves?|rejects?)",
        text,
    ):
        return {
            "value": "No - AI output can determine the outcome",
            "why": "you described it as automatic",
        }
    if re.search(
        r"(agents?|staff|analysts?|humans?|managers?|people|team)\b.{0,30}\b(review\w*|approv\w*|check\w*|verif\w*)|human[- ]in[- ]the[- ]loop",
        text,
    ):
        return {"value": "Always", "why": "you said people review it"}
    return None


def _infer_autonomy(text, _raw):
    if re.search(r"automatically|autonomous|end-to-end", text):
        return {
            "value": "Can take actions automatically across a workflow",
            "why": "mentions acting automatically",
        }
    return None


def _infer_segment(text, _raw):
    if re.search(r"consumer[- ]facing|customer[- ]facing|customer care|b2c|end[- ]user", text):
        return {"value": "Consumer-Facing AI", "why": "mentions consumer or customer-facing use"}
    if re.search(r"enterprise ai|b2b|organisation[- ]wide|organization[- ]wide", text):
        return {"value": "Enterprise AI", "why": "mentions enterprise use"}
    if re.search(r"corporate ai|employees?|internal staff|back[- ]office", text):
        return {"value": "Corporate AI", "why": "mentions corporate or employee use"}
    if re.search(r"internal operations|ops team|operations team|non[- ]customer", text):
        return {"value": "Internal Operations", "why": "mentions internal operations"}
    return None


def _infer_value_driver(text, _raw):
    pairs = [
        (r"revenue uplift|increase revenue|upsell|cross[- ]sell|arpu", "Revenue Uplift"),
        (r"cost reduction|reduce cost|save cost|cost saving", "Cost Reduction"),
        (r"customer experience|cx\b|nps|satisfaction", "Customer Experience"),
        (r"\bgovernance\b|compliance oversight|control framework", "Governance"),
        (r"\befficiency\b", "Efficiency"),
        (r"productivity|hours saved|automate(s|d)? work|analyst effort", "Productivity"),
    ]
    for pattern, label in pairs:
        if re.search(pattern, text):
            return {"value": label, "why": f"mentions {label.lower()}"}
    return None


def _money_near(text: str, labels: str):
    """Pull a money/ROI phrase only when a value label is nearby."""
    match = re.search(
        rf"(?:{labels}).{{0,40}}?((?:usd\s*)?\$?\s?\d[\d,]*(?:\.\d+)?(?:\s*(?:usd|%|percent))?)",
        text,
        re.IGNORECASE,
    )
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip(" ,.")
    match = re.search(
        rf"((?:usd\s*)?\$?\s?\d[\d,]*(?:\.\d+)?(?:\s*(?:usd|%|percent))?).{{0,40}}?(?:{labels})",
        text,
        re.IGNORECASE,
    )
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip(" ,.")
    return None


def _infer_annual_value(text, _raw):
    value = _money_near(text, r"annual value|roi|return on investment|benefit(?:s)?|save(?:s|d)?")
    if value:
        return {"value": value, "why": "value or ROI amount found in the description"}
    return None


def _infer_investment_cost(text, _raw):
    value = _money_near(text, r"investment|capex|budget|project cost|estimated cost|total cost")
    if value:
        return {"value": value, "why": "investment or cost amount found in the description"}
    return None


def _infer_spending_to_date(text, _raw):
    value = _money_near(text, r"spent to date|spending to date|spent so far|already spent|opex to date")
    if value:
        return {"value": value, "why": "spending-to-date amount found in the description"}
    return None


def _infer_hours_saved(text, raw):
    match = re.search(
        r"(\d[\d,]*(?:\s*-\s*\d[\d,]*)?\s*(?:hours?|hrs?)(?:\s*(?:per|/)\s*(?:year|yr|month|week|day))?)",
        text,
        re.IGNORECASE,
    )
    if match and re.search(r"save|saving|saved|fte|effort", text):
        return {"value": match.group(1).strip(), "why": "hours-saved figure found in the description"}
    # Keep original casing from raw when possible
    match_raw = re.search(
        r"(\d[\d,]*(?:\s*-\s*\d[\d,]*)?\s*(?:hours?|hrs?)(?:\s*(?:per|/)\s*(?:year|yr|month|week|day))?)",
        raw,
        re.IGNORECASE,
    )
    if match_raw and re.search(r"save|saving|saved|fte|effort", text):
        return {"value": match_raw.group(1).strip(), "why": "hours-saved figure found in the description"}
    return None


_INFER = {
    "category": _infer_category,
    "name": _infer_name,
    "segment": _infer_segment,
    "valueDriver": _infer_value_driver,
    "annualValue": _infer_annual_value,
    "investmentCost": _infer_investment_cost,
    "spendingToDate": _infer_spending_to_date,
    "hoursSaved": _infer_hours_saved,
    "sensitive": _infer_sensitive,
    "decision": _infer_decision,
    "action": _infer_action,
    "forTool": _infer_tool,
    "forAccess": _infer_access,
    "threatTypes": _infer_threats,
    "dataExternal": _infer_external,
    "humanReview": _infer_review,
    "autonomy": _infer_autonomy,
}


def keyword_extract(description: str) -> dict[str, dict]:
    text = description.lower()
    found = {}
    for slot_id, infer in _INFER.items():
        result = infer(text, description)
        if result:
            found[slot_id] = {
                "value": result["value"],
                "why": result["why"],
                "source": "description",
            }
    return found


def values_of(state: dict) -> dict:
    return {slot_id: slot.get("value") for slot_id, slot in state["slots"].items()}


def slot_active(slot: Slot, values: dict) -> bool:
    if slot.auto:
        return False
    if slot.when is None:
        return True
    return bool(slot.when(values))


def active_slots(state: dict) -> list[Slot]:
    values = values_of(state)
    return [slot for slot in SLOTS if slot_active(slot, values)]


def has_value(slot: Slot, value) -> bool:
    if slot.kind == "multi":
        return isinstance(value, list) and len(value) > 0
    return bool(value)


def display_value(slot: Slot, value) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return "" if value is None else str(value)


def make_summary(description: str) -> str:
    """Offline concise summary — never paste the full user prompt verbatim."""
    compact = re.sub(r"\s+", " ", (description or "")).strip()
    if not compact:
        return ""
    stripped = re.sub(
        r"^(?:we(?:'d| would)? like to|we want to|i want to|we(?:'re| are) (?:going to|planning to)|"
        r"this (?:is|request is) (?:about|for)|looking to)\s+",
        "",
        compact,
        flags=re.I,
    ).strip() or compact
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", stripped) if p.strip()]
    chosen: list[str] = []
    for part in parts:
        trial = " ".join(chosen + [part]).strip()
        if chosen and len(trial) > 200:
            break
        chosen.append(part)
        if len(" ".join(chosen)) >= 90 and len(chosen) >= 1:
            break
        if len(chosen) >= 2:
            break
    summary = " ".join(chosen).strip() or stripped
    if len(summary) > 220:
        summary = re.sub(r"\s+\S*$", "", summary[:217]).rstrip(" ,;") + "…"
    if summary and summary[0].islower():
        summary = summary[0].upper() + summary[1:]
    if summary and summary[-1] not in ".!?…":
        summary = summary.rstrip(" ,;") + "."
    # If we barely shortened a short prompt, still rephrase lightly by dropping filler clauses.
    if summary.lower().rstrip(".") == compact.lower().rstrip(".") and len(compact) > 140:
        summary = re.sub(r"\s+\S*$", "", compact[:160]).rstrip(" ,;") + "…"
        if summary[0].islower():
            summary = summary[0].upper() + summary[1:]
    return summary[:280]


def set_summary(state: dict, value: str, *, source: str = "llm", why: str = "") -> None:
    """Write the auto summary slot (apply_extractions skips auto fields)."""
    text = str(value or "").strip()
    if not text:
        return
    if len(text) > 280:
        text = re.sub(r"\s+\S*$", "", text[:277]).rstrip(" ,;") + "…"
    state["slots"]["summary"] = {
        "value": text,
        "status": "confirmed",
        "source": source,
        "why": why or ("AI-generated concise summary" if source == "llm" else "concise summary of your description"),
    }


def empty_slot_state(slot: Slot) -> dict:
    return {
        "value": [] if slot.kind == "multi" else "",
        "status": "empty",
        "source": None,
        "why": "",
    }


def initial_state(owner: str, business_unit: str, description: str) -> dict:
    slots = {slot.id: empty_slot_state(slot) for slot in SLOTS}
    slots["owner"] = {
        "value": owner,
        "status": "confirmed",
        "source": "profile",
        "why": "",
    }
    unit = business_unit if business_unit in BUSINESS_UNITS else ""
    slots["businessUnit"] = {
        "value": unit,
        "status": "confirmed" if unit else "empty",
        "source": "profile" if unit else None,
        "why": "",
    }
    slots["summary"] = {
        "value": make_summary(description),
        "status": "confirmed",
        "source": "auto",
        "why": "",
    }
    return {"asked": 0, "announced": [], "slots": slots}


def _values_equal(left, right) -> bool:
    if isinstance(left, list) or isinstance(right, list):
        a = left if isinstance(left, list) else ([] if left in (None, "") else [left])
        b = right if isinstance(right, list) else ([] if right in (None, "") else [right])
        return sorted(str(x) for x in a) == sorted(str(x) for x in b)
    return str(left or "") == str(right or "")


def apply_extractions(
    state: dict,
    found: dict[str, dict],
    *,
    allow_update: bool = False,
    mark_confirmed: bool = False,
) -> list[str]:
    """Fill empty slots, or update existing ones when allow_update is True.

    Profile and auto slots are never overwritten. Returns active slot ids that changed.
    """
    values = values_of(state)
    applied = []
    for slot in SLOTS:
        guess = found.get(slot.id)
        current = state["slots"][slot.id]
        if not guess:
            continue
        if slot.profile or slot.auto:
            continue
        if current["status"] != "empty" and not allow_update:
            continue
        if current["status"] != "empty" and _values_equal(current.get("value"), guess["value"]):
            continue
        current["value"] = guess["value"]
        if mark_confirmed or current["status"] == "confirmed":
            current["status"] = "confirmed"
            current["source"] = guess.get("source") or ("you" if allow_update else "description")
        else:
            current["status"] = "inferred"
            current["source"] = guess.get("source") or "description"
        current["why"] = guess.get("why") or ""
        values[slot.id] = guess["value"]
        if slot_active(slot, values):
            applied.append(slot.id)
    return applied


def flags_for(values: dict) -> list[dict]:
    found = []

    def add(level, title, why):
        found.append({"level": level, "title": title, "why": why})

    if _when_for_us_sensitive(values) and values.get("forAccess") in (
        "Public / free web service",
        "Individual / personal account",
    ):
        add(
            "attention",
            "Sensitive information in a public or personal AI account",
            "Reviewers will check whether an enterprise-managed option should be used instead.",
        )
    if is_on(values.get("sensitive")) and values.get("dataExternal") == "Yes":
        add(
            "attention",
            "Sensitive information goes to an outside provider",
            "Reviewers will look at the provider's data handling and your contract terms. Naming the provider helps.",
        )
    human_review = str(values.get("humanReview") or "")
    if is_on(values.get("decision")) and human_review.startswith("No"):
        add(
            "attention",
            "No person checks the output before decisions are made",
            "Reviewers will want to know what protects people from a wrong outcome.",
        )
    if is_on(values.get("action")) and values.get("autonomy") == "Can take actions automatically across a workflow":
        add(
            "attention",
            "It can act automatically across a workflow",
            "Reviewers will look at limits, monitoring, and how to stop it.",
        )
    order = {"urgent": 0, "attention": 1, "info": 2}
    found.sort(key=lambda item: order[item["level"]])
    return found


def route_for(values: dict) -> list[str]:
    routing = ["RAIO"]
    if is_on(values.get("sensitive")):
        routing.extend(["Privacy / Data Protection", "Cybersecurity"])
    if is_on(values.get("decision")):
        routing.append("Legal / Compliance")
    if is_on(values.get("action")):
        routing.append("Technology / Cybersecurity")
    category = values.get("category")
    if category == "AI For Us":
        routing.append("Supplier / Procurement Review")
    elif category == "AI By Us":
        routing.append("Technology / Architecture")
    elif category == "AI Against Us":
        routing.append("Cybersecurity")
    deduped = []
    for team in routing:
        if team not in deduped:
            deduped.append(team)
    return deduped


def comparable_from(state: dict, description: str) -> dict:
    values = values_of(state)
    requirements = " | ".join(
        f"{slot.label}: {display_value(slot, values.get(slot.id))}"
        for slot in active_slots(state)
        if has_value(slot, values.get(slot.id))
    )
    screening = " | ".join(str(values.get(key) or "") for key in ("sensitive", "decision", "action"))
    return {
        "category": values.get("category") or "",
        "name": values.get("name") or "",
        "summary": values.get("summary") or "",
        "description": description.strip(),
        "requirements": requirements,
        "screening": screening,
    }


def missing_slots(state: dict) -> list[Slot]:
    values = values_of(state)
    missing = []
    for slot in active_slots(state):
        if not has_value(slot, values.get(slot.id)):
            missing.append(slot)
    return missing


def validate_answer(slot: Slot, value):
    if slot.kind == "multi":
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list) or not value:
            raise ValueError(f"Choose at least one option for {slot.label}.")
        cleaned = []
        for item in value:
            if item not in slot.option_values:
                raise ValueError(f"'{item}' is not a valid option for {slot.label}.")
            if item not in cleaned:
                cleaned.append(item)
        return cleaned
    if slot.kind == "single":
        if value not in slot.option_values:
            raise ValueError(f"'{value}' is not a valid option for {slot.label}.")
        return value
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Enter a value for {slot.label}.")
    if slot.id == "summary" and len(text) > 280:
        raise ValueError("Summary must be 280 characters or fewer.")
    if len(text) > 500:
        raise ValueError(f"{slot.label} must be 500 characters or fewer.")
    return text
