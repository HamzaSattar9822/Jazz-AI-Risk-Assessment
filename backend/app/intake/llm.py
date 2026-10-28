"""Optional LLM extraction. Keyword extraction remains the fallback."""

from __future__ import annotations

import json
import logging
import re

import httpx

from app.config import Settings
from app.intake.catalog import SLOTS_BY_ID, validate_answer

logger = logging.getLogger(__name__)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _slot_guide() -> list[dict]:
    guide = []
    for slot_id in (
        "category",
        "name",
        "segment",
        "valueDriver",
        "annualValue",
        "investmentCost",
        "spendingToDate",
        "hoursSaved",
        "sensitive",
        "decision",
        "action",
        "forTool",
        "forAccess",
        "threatTypes",
        "dataExternal",
        "humanReview",
        "autonomy",
    ):
        slot = SLOTS_BY_ID[slot_id]
        entry = {
            "id": slot.id,
            "question": slot.question,
            "kind": slot.kind,
        }
        if slot.option_values:
            entry["allowedValues"] = slot.option_values
        guide.append(entry)
    return guide


def _parse_content(content: str) -> dict:
    text = content.strip()
    text = _FENCE.sub("", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("model did not return JSON")
    return json.loads(text[start : end + 1])


_PLACEHOLDER = re.compile(
    r"^(?:n/?a|na|none|null|nil|unknown|tbd|not\s+(?:stated|specified|mentioned|provided|available|"
    r"given|applicable|sure)|-+\.?|—|–)$",
    re.I,
)


def is_placeholder_value(raw_value) -> bool:
    """True for N/A-style filler the model should omit instead of writing into the form."""
    if raw_value is None:
        return True
    if isinstance(raw_value, list):
        return len(raw_value) == 0
    text = str(raw_value).strip()
    if not text:
        return True
    return bool(_PLACEHOLDER.match(text))


def _accept(slot_id: str, raw_value, why: str) -> dict | None:
    slot = SLOTS_BY_ID.get(slot_id)
    if slot is None or slot.profile:
        return None
    # Summary is auto-filled but we still accept an LLM-written concise version.
    if slot.auto and slot.id != "summary":
        return None
    if is_placeholder_value(raw_value):
        return None
    try:
        value = validate_answer(slot, raw_value)
    except ValueError:
        return None
    reason = str(why or "").strip()[:240] or "from your description"
    return {"value": value, "why": reason, "source": "llm"}


def llm_extract(description: str, settings: Settings) -> dict[str, dict] | None:
    if not settings.llm_configured:
        return None
    payload = {
        "model": settings.llm_model,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You extract fields for JazzWorld's Responsible AI approval intake. "
                    "Pull every field the description clearly supports. "
                    "Omit a field entirely when unsupported - never output N/A, Not stated, Unknown, or None. "
                    "Never invent a tool, a name, amounts, or a Yes. "
                    "For choice fields, copy an allowed value exactly. "
                    "Decide category carefully - do NOT default to AI For Us. "
                    "Always include a summary: 1-2 short sentences restating the request. "
                    "Do NOT copy the prompt verbatim. Max 200 characters for summary. "
                    "If the text is only a short correction, extract changed fields and omit summary. "
                    "Reply with JSON only. "
                    'Schema: {"extractions":[{"id":"...","value":"...","why":"short phrase"}]}.'
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "description": description[:8000],
                        "fields": _slot_guide()
                        + [
                            {
                                "id": "summary",
                                "question": "Write a concise 1-2 sentence summary of this AI request.",
                                "kind": "text",
                                "maxChars": 200,
                            }
                        ],
                        "rules": [
                            "Never use placeholder values (N/A, Not stated, Unknown). Omit the field instead.",
                            "summary: concise AI-written restatement, not a truncated copy of the prompt.",
                            "name: extract a product/use-case name when given (quoted, called/named, or clear proper name like Microsoft Copilot).",
                            "Treat short follow-up messages as corrections or additions; extract changed fields.",
                            "category has exactly three values: AI For Us, AI By Us, AI Against Us.",
                            "AI Against Us: assessing or defending against AI-enabled threats aimed at Jazz (deepfake, phishing, voice clone, prompt injection, adversarial fraud). Prefer this when the goal is threat/risk assessment, not deploying a product.",
                            "AI By Us: we build, train, fine-tune, or deploy our own model/system (in-house, prototype, model called X). Hosting on Azure/AWS/OpenAI still counts as AI By Us if we are building it.",
                            "AI For Us: we buy, license, subscribe, or roll out someone else's product (Copilot, ChatGPT, vendor SaaS). Prefer this only when the main act is adopting a third-party tool.",
                            "If build/train language and a cloud vendor both appear, choose AI By Us.",
                            "If threat/deepfake/phishing language is the purpose, choose AI Against Us even if tools are named.",
                            "sensitive is Yes when customer, employee, financial, contract, confidential, billing, or credential data is involved; No only if text clearly says no sensitive data.",
                            "decision is Yes when output affects eligibility, pricing, ranking, credit, approvals, or recommendations that change outcomes.",
                            "action is Yes for chatbots that talk to people, or systems that send messages / update records; No when it only drafts for humans with no send/update.",
                            "threatTypes is an array and applies only to AI Against Us.",
                            "forTool / forAccess apply only to AI For Us. forTool = product name (e.g. Microsoft Copilot).",
                            "segment: map audience — customers/B2C → Consumer-Facing AI; enterprise accounts/B2B → Enterprise AI; employees/finance team/corporate → Corporate AI; ops/internal agents → Internal Operations.",
                            "valueDriver: Productivity, Revenue Uplift, Cost Reduction, Customer Experience, Efficiency, Governance, or Other — pick the best match from goals like summarise, draft, automate, save time, revenue, cost.",
                            "annualValue / investmentCost / spendingToDate: extract when an amount or ROI is stated; keep USD/$/% as written.",
                            "hoursSaved: extract when hours/FTE savings are stated; keep units (e.g. 500 hours / year).",
                            "humanReview: Always / Sometimes / No - AI output can determine the outcome — when review language appears.",
                            "dataExternal: Yes when Azure/OpenAI/AWS/Google/vendor/SaaS processes data; No when clearly on-prem/in-house only.",
                            "Never invent financial figures or hours.",
                        ],
                        "categoryExamples": [
                            {
                                "text": "Roll out Microsoft Copilot for finance on enterprise accounts.",
                                "category": "AI For Us",
                            },
                            {
                                "text": "Building Credit Line Recommender trained on JazzCash transactions, hosted on Azure.",
                                "category": "AI By Us",
                            },
                            {
                                "text": "Voice-cloned calls impersonating executives; assess deepfake fraud risk against staff.",
                                "category": "AI Against Us",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }
    if settings.llm_json_mode:
        payload["response_format"] = {"type": "json_object"}
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"
    try:
        response = None
        last_error = None
        for attempt in range(3):
            try:
                response = httpx.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=settings.llm_timeout_seconds,
                    verify=settings.llm_verify_ssl,
                )
                if response.status_code in {502, 503, 504} and attempt < 2:
                    last_error = httpx.HTTPStatusError(
                        f"{response.status_code} from LLM",
                        request=response.request,
                        response=response,
                    )
                    continue
                response.raise_for_status()
                break
            except httpx.TransportError as exc:
                last_error = exc
                if attempt == 2:
                    raise
        if response is None:
            raise last_error or RuntimeError("LLM request failed")
        content = response.json()["choices"][0]["message"]["content"]
        parsed = _parse_content(content)
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("LLM extraction failed, using keyword extractor: %s", exc)
        return None

    found = {}
    for item in parsed.get("extractions") or []:
        if not isinstance(item, dict):
            continue
        accepted = _accept(str(item.get("id") or ""), item.get("value"), item.get("why") or "")
        if accepted:
            found[str(item["id"])] = accepted
    return found
