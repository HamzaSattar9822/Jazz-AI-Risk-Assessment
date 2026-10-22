"""Validation flags. These do not change the deterministic score."""

from __future__ import annotations


def _score(value):
    if isinstance(value, dict) and "value" in value:
        value = value.get("value")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 1 or number > 5:
        return None
    return int(round(number))


def detect_contradictions(assessment: dict) -> list[dict]:
    screening = assessment.get("screening") or {}
    scores = assessment.get("scores") or {}
    impact = scores.get("impact") or {}
    people = impact.get("peopleData") or {}
    business = impact.get("business") or {}
    ai = impact.get("ai") or {}
    controls = scores.get("controls") or {}
    context = assessment.get("context") or {}
    flags = []

    oversight = str(context.get("humanReview") or "").strip().lower()
    autonomy = str(context.get("autonomy") or "").strip().lower()
    if oversight.startswith("always") and (
        "automatically across a workflow" in autonomy or "fully automatic" in autonomy
    ):
        flags.append(
            {
                "code": "oversight_vs_autonomy",
                "level": "attention",
                "message": "Human review is 'Always' but autonomy is fully automatic. Confirm whether both answers are correct.",
            }
        )

    data_on = bool(screening.get("data"))
    decision_on = bool(screening.get("decision"))
    action_on = bool(screening.get("action"))

    data_sensitivity = _score(people.get("Data Sensitivity"))
    if not data_on and data_sensitivity is not None and data_sensitivity >= 3:
        flags.append(
            {
                "code": "data_screening_vs_sensitivity",
                "level": "attention",
                "message": "Data screening is No, but Data Sensitivity is scored 3 or higher.",
            }
        )

    decision_consequence = _score(business.get("Decision Consequence"))
    if not decision_on and decision_consequence is not None and decision_consequence >= 3:
        flags.append(
            {
                "code": "decision_screening_vs_consequence",
                "level": "attention",
                "message": "Decision screening is No, but Decision Consequence is scored 3 or higher.",
            }
        )

    oversight_impact = _score(ai.get("Human Oversight & Autonomy"))
    if not action_on and oversight_impact is not None and oversight_impact >= 3:
        flags.append(
            {
                "code": "action_screening_vs_autonomy_impact",
                "level": "attention",
                "message": "Action screening is No, but Human Oversight & Autonomy impact is scored 3 or higher.",
            }
        )

    oversight_control = _score(controls.get("Human Oversight Controls"))
    if (
        oversight_impact is not None
        and oversight_impact >= 4
        and oversight_control is not None
        and oversight_control == 1
    ):
        flags.append(
            {
                "code": "high_autonomy_vs_strong_oversight_control",
                "level": "attention",
                "message": "Human Oversight & Autonomy impact is 4 or 5 while Human Oversight Controls are scored as strongest (1). Confirm this combination.",
            }
        )

    for key in ("legal", "regulatory", "contractual", "privacy", "cybersecurity", "safety", "policy"):
        if assessment.get("mandatoryRequirements", {}).get(key):
            flags.append(
                {
                    "code": f"mandatory_{key}",
                    "level": "mandatory",
                    "message": f"Mandatory {key} requirement is flagged. A low calculated score does not waive this requirement.",
                }
            )

    return flags
