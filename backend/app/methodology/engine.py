"""Official JazzWorld AIRA-DDA-1.0 deterministic risk engine.

The conversational AI may suggest inputs. This module alone calculates the
official risk score, residual risk, tier, and approval level. Formulas and
weights are fixed by the approved methodology and must not be altered by an LLM.
"""

from __future__ import annotations

import math

from app.methodology.contradictions import detect_contradictions
from app.methodology.descriptors import all_descriptors
from app.methodology.governance import get_governance_requirements, get_risk_tier
from app.methodology.provenance import ProvenanceError, filter_official_scores, require_human_approval

METHODOLOGY_VERSION = "AIRA-DDA-1.0"

IMPACT_FACTORS = {
    "business": [
        "Business Criticality",
        "Customer / Service Impact",
        "Decision Consequence",
        "Operational Dependency",
        "Financial Exposure",
        "Resilience / Continuity",
        "Third-Party / Supplier Dependency",
        "Strategic / Sovereignty Dependency",
    ],
    "peopleData": [
        "Population Affected",
        "Vulnerable / Higher-Impact Groups",
        "Employee Impact",
        "Customer Impact",
        "Data Sensitivity",
        "Personal Data Exposure",
        "Privacy / Data Protection",
        "Individual Consequence",
        "Human Rights / Wellbeing",
    ],
    "ai": [
        "Fairness & Non-Discrimination",
        "Safety & Reliability",
        "Transparency & Explainability",
        "Human Oversight & Autonomy",
        "Cybersecurity",
        "Legal & Regulatory",
        "Reputation & Trust",
        "Societal Impact",
    ],
}

LIKELIHOOD_FACTORS = {
    "occurrence": [
        "Historical Occurrence",
        "Frequency of Use",
        "Scale of Exposure",
        "Duration / Persistence of Exposure",
        "Change / Volatility",
    ],
    "feasibility": [
        "Technical Feasibility",
        "Access Required",
        "Skill / Complexity Required",
        "Foreseeable Misuse",
        "Model / Data Susceptibility",
    ],
}

CONTROL_FACTORS = [
    "Preventive Controls",
    "Detective Controls",
    "Human Oversight Controls",
    "Governance Controls",
    "Control Validation / Testing",
]

# Impact main-factor relevance points.
_IMPACT_POINTS = {
    "base": {"business": 2, "peopleData": 2, "ai": 2},
    "data": {"business": 0, "peopleData": 2, "ai": 1},
    "decision": {"business": 1, "peopleData": 2, "ai": 2},
    "action": {"business": 2, "peopleData": 1, "ai": 2},
}

# 1.00 = normal emphasis, 1.25 = moderate, 1.50 = high.
# Multiple active dimensions add their increments and are capped at 2.00.
_OCCURRENCE_MODIFIERS = {
    "data": {
        "Historical Occurrence": 1.00,
        "Frequency of Use": 1.25,
        "Scale of Exposure": 1.50,
        "Duration / Persistence of Exposure": 1.50,
        "Change / Volatility": 1.00,
    },
    "decision": {
        "Historical Occurrence": 1.00,
        "Frequency of Use": 1.25,
        "Scale of Exposure": 1.25,
        "Duration / Persistence of Exposure": 1.00,
        "Change / Volatility": 1.50,
    },
    "action": {
        "Historical Occurrence": 1.00,
        "Frequency of Use": 1.50,
        "Scale of Exposure": 1.50,
        "Duration / Persistence of Exposure": 1.50,
        "Change / Volatility": 1.50,
    },
}

_FEASIBILITY_MODIFIERS = {
    "data": {
        "Technical Feasibility": 1.00,
        "Access Required": 1.50,
        "Skill / Complexity Required": 1.00,
        "Foreseeable Misuse": 1.50,
        "Model / Data Susceptibility": 1.50,
    },
    "decision": {
        "Technical Feasibility": 1.00,
        "Access Required": 1.00,
        "Skill / Complexity Required": 1.00,
        "Foreseeable Misuse": 1.50,
        "Model / Data Susceptibility": 1.50,
    },
    "action": {
        "Technical Feasibility": 1.50,
        "Access Required": 1.50,
        "Skill / Complexity Required": 1.25,
        "Foreseeable Misuse": 1.50,
        "Model / Data Susceptibility": 1.25,
    },
}

# Control profiles are percentages from the agreed methodology.
_CONTROL_PROFILES = {
    "data": {
        "Preventive Controls": 25,
        "Detective Controls": 25,
        "Human Oversight Controls": 10,
        "Governance Controls": 20,
        "Control Validation / Testing": 20,
    },
    "decision": {
        "Preventive Controls": 15,
        "Detective Controls": 10,
        "Human Oversight Controls": 30,
        "Governance Controls": 25,
        "Control Validation / Testing": 20,
    },
    "action": {
        "Preventive Controls": 25,
        "Detective Controls": 20,
        "Human Oversight Controls": 25,
        "Governance Controls": 10,
        "Control Validation / Testing": 20,
    },
    "neutral": {
        "Preventive Controls": 20,
        "Detective Controls": 20,
        "Human Oversight Controls": 20,
        "Governance Controls": 20,
        "Control Validation / Testing": 20,
    },
}


def js_round(value: float, digits: int = 4) -> float:
    """Match JavaScript Number(Number(n).toFixed(digits)): half away from zero."""
    if not math.isfinite(value):
        raise ValueError("score is not a finite number")
    quant = 10**digits
    scaled = abs(value) * quant
    rounded = math.floor(scaled + 0.5 + 1e-8)
    signed = math.copysign(rounded / quant, value)
    if signed == 0:
        return 0.0
    return float(signed)


def js_math_round(value: float) -> int:
    """Nearest whole number (half away from zero for non-negative scores)."""
    return int(math.floor(value + 0.5))


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _as_bool(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"yes", "true", "1"}:
        return True
    if text in {"no", "false", "0"}:
        return False
    # Screening answers are Yes/No. Legacy "Not sure" is not treated as Yes here.
    return None


def _yes(value) -> bool:
    flag = _as_bool(value)
    if flag is not None:
        return flag
    return str(value).lower() == "yes"


def _normalize(obj: dict) -> dict:
    total = sum(obj.values())
    return {key: js_round(val / total, 6) for key, val in obj.items()}


def normalize_screening(screening: dict | None) -> dict:
    """Accept either boolean {data,decision,action} or Yes/No triage keys."""
    screening = screening or {}
    if any(key in screening for key in ("data", "decision", "action")) and "sensitive" not in screening:
        return {
            "data": bool(_as_bool(screening.get("data"))),
            "decision": bool(_as_bool(screening.get("decision"))),
            "action": bool(_as_bool(screening.get("action"))),
        }
    return {
        "data": _yes(screening.get("sensitive", screening.get("data"))),
        "decision": _yes(screening.get("decision")),
        "action": _yes(screening.get("action")),
    }


def triage_dimensions(triage: dict | None) -> dict:
    return normalize_screening(triage)


def calculate_impact_weights(screening: dict | None) -> dict:
    dims = normalize_screening(screening)
    points = dict(_IMPACT_POINTS["base"])
    if dims["data"]:
        for key in points:
            points[key] += _IMPACT_POINTS["data"][key]
    if dims["decision"]:
        for key in points:
            points[key] += _IMPACT_POINTS["decision"][key]
    if dims["action"]:
        for key in points:
            points[key] += _IMPACT_POINTS["action"][key]
    return _normalize(points)


# Backward-compatible alias used by the intake API.
get_impact_weights = calculate_impact_weights


def _combine_subfactor_weights(names: list[str], modifiers: dict, screening: dict | None) -> dict:
    dims = normalize_screening(screening)
    raw = {}
    for name in names:
        weight = 1.0
        for dim in ("data", "decision", "action"):
            if dims[dim]:
                weight += modifiers[dim][name] - 1
        raw[name] = _clamp(weight, 1, 2)
    return _normalize(raw)


def calculate_likelihood_weights(screening: dict | None) -> dict:
    return {
        "occurrence": _combine_subfactor_weights(
            LIKELIHOOD_FACTORS["occurrence"], _OCCURRENCE_MODIFIERS, screening
        ),
        "feasibility": _combine_subfactor_weights(
            LIKELIHOOD_FACTORS["feasibility"], _FEASIBILITY_MODIFIERS, screening
        ),
    }


def calculate_control_weights(screening: dict | None) -> dict:
    dims = normalize_screening(screening)
    active = [key for key in ("data", "decision", "action") if dims[key]]
    if not active:
        return _normalize(_CONTROL_PROFILES["neutral"])
    raw = {}
    for name in CONTROL_FACTORS:
        raw[name] = sum(_CONTROL_PROFILES[key][name] for key in active) / len(active)
    return _normalize(raw)


get_control_weights = calculate_control_weights


def get_weight_profile(triage: dict | None) -> dict:
    screening = normalize_screening(triage)
    likelihood = calculate_likelihood_weights(triage)
    return {
        "methodologyVersion": METHODOLOGY_VERSION,
        "screening": screening,
        "impactMain": calculate_impact_weights(triage),
        "likelihood": likelihood,
        "existingControls": calculate_control_weights(triage),
        "residualLikelihoodControlMultipliers": {
            "1": 0.60,
            "2": 0.70,
            "3": 0.80,
            "4": 0.90,
            "5": 1.00,
        },
    }


def _as_score(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, dict) and "value" in value:
        value = value.get("value")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 1 or number > 5:
        return None
    # Official scores are integers 1–5.
    if abs(number - round(number)) > 1e-9:
        return None
    return int(round(number))


def _validate_scores(obj, names: list[str]) -> bool:
    if not isinstance(obj, dict):
        return False
    return all(_as_score(obj.get(name)) is not None for name in names)


def _weighted_average(scores, weights: dict, names: list[str]):
    if not _validate_scores(scores, names):
        return None
    return sum(float(_as_score(scores[name])) * weights[name] for name in names)


def _equal_weights(names: list[str]) -> dict:
    return _normalize({name: 1 for name in names})


def calculate_impact_main_factors(scores: dict | None) -> dict | None:
    impact = (scores or {}).get("impact") or {}
    business = _weighted_average(
        impact.get("business"), _equal_weights(IMPACT_FACTORS["business"]), IMPACT_FACTORS["business"]
    )
    people_data = _weighted_average(
        impact.get("peopleData"),
        _equal_weights(IMPACT_FACTORS["peopleData"]),
        IMPACT_FACTORS["peopleData"],
    )
    ai = _weighted_average(impact.get("ai"), _equal_weights(IMPACT_FACTORS["ai"]), IMPACT_FACTORS["ai"])
    if any(value is None for value in (business, people_data, ai)):
        return None
    return {"business": business, "peopleData": people_data, "ai": ai}


def calculate_impact_score(main_factors: dict, weights: dict) -> float:
    return 3 * (
        main_factors["business"] * weights["business"]
        + main_factors["peopleData"] * weights["peopleData"]
        + main_factors["ai"] * weights["ai"]
    )


def calculate_weighted_occurrence(scores: dict | None, weights: dict) -> float | None:
    return _weighted_average(
        ((scores or {}).get("likelihood") or {}).get("occurrence"),
        weights,
        LIKELIHOOD_FACTORS["occurrence"],
    )


def calculate_weighted_feasibility(scores: dict | None, weights: dict) -> float | None:
    return _weighted_average(
        ((scores or {}).get("likelihood") or {}).get("feasibility"),
        weights,
        LIKELIHOOD_FACTORS["feasibility"],
    )


def calculate_inherent_likelihood(weighted_occurrence: float, weighted_feasibility: float) -> float:
    return 3 * ((weighted_occurrence + weighted_feasibility) / 2)


def calculate_weighted_control_strength(scores: dict | None, weights: dict) -> float | None:
    return _weighted_average((scores or {}).get("controls"), weights, CONTROL_FACTORS)


def calculate_control_multiplier(weighted_control_strength: float) -> float:
    return 0.5 + (0.1 * weighted_control_strength)


def calculate_residual_likelihood(inherent_likelihood: float, control_multiplier: float) -> float:
    return max(3.0, inherent_likelihood * control_multiplier)


def calculate_risk_score(impact: float, likelihood: float) -> int:
    raw = ((impact * likelihood) / 225) * 100
    return int(_clamp(js_math_round(raw), 1, 100))


def risk_level(score):
    return get_risk_tier(score)


def _score_value(node):
    if isinstance(node, dict) and "value" in node:
        return node.get("value")
    return node


def incomplete_score_paths(scores: dict | None) -> list[str]:
    scores = scores or {}
    impact = scores.get("impact") or {}
    likelihood = scores.get("likelihood") or {}
    missing = []
    for group, names in IMPACT_FACTORS.items():
        bucket = impact.get(group) or {}
        for name in names:
            if _as_score(_score_value(bucket.get(name))) is None:
                missing.append(f"impact.{group}.{name}")
    for group, names in LIKELIHOOD_FACTORS.items():
        bucket = likelihood.get(group) or {}
        for name in names:
            if _as_score(_score_value(bucket.get(name))) is None:
                missing.append(f"likelihood.{group}.{name}")
    controls = scores.get("controls") or {}
    for name in CONTROL_FACTORS:
        if _as_score(_score_value(controls.get(name))) is None:
            missing.append(f"controls.{name}")
    return missing


def validate_assessment_inputs(assessment: dict) -> list[str]:
    errors = []
    screening = assessment.get("screening")
    if not isinstance(screening, dict):
        errors.append("screening must be an object with data, decision, and action")
    else:
        data = screening.get("data", screening.get("sensitive"))
        decision = screening.get("decision")
        action = screening.get("action")
        if _as_bool(data) is None:
            errors.append("screening.data must be boolean (or Yes/No)")
        if _as_bool(decision) is None:
            errors.append("screening.decision must be boolean (or Yes/No)")
        if _as_bool(action) is None:
            errors.append("screening.action must be boolean (or Yes/No)")
    missing = incomplete_score_paths(assessment.get("scores"))
    errors.extend(f"missing or invalid score: {path}" for path in missing)
    return errors


def calculate_risk(scores: dict | None, triage: dict | None) -> dict:
    """Core deterministic calculation. Does not apply human-review gates."""
    working = _unwrap_all(scores or {})
    weights = get_weight_profile(triage)

    main = calculate_impact_main_factors({"impact": working.get("impact")})
    if main is None:
        return {"complete": False, "weights": weights}

    impact_score = calculate_impact_score(main, weights["impactMain"])
    occurrence = calculate_weighted_occurrence(working, weights["likelihood"]["occurrence"])
    feasibility = calculate_weighted_feasibility(working, weights["likelihood"]["feasibility"])
    if occurrence is None or feasibility is None:
        return {"complete": False, "weights": weights, "impactScore": js_round(impact_score)}

    inherent_likelihood = calculate_inherent_likelihood(occurrence, feasibility)
    control_strength = calculate_weighted_control_strength(working, weights["existingControls"])
    if control_strength is None:
        return {
            "complete": False,
            "weights": weights,
            "impactScore": js_round(impact_score),
            "inherentLikelihood": js_round(inherent_likelihood),
        }

    control_multiplier = calculate_control_multiplier(control_strength)
    residual_likelihood = calculate_residual_likelihood(inherent_likelihood, control_multiplier)
    inherent_risk = calculate_risk_score(impact_score, inherent_likelihood)
    residual_risk = calculate_risk_score(impact_score, residual_likelihood)
    governance = get_risk_tier(residual_risk)

    return {
        "complete": True,
        "methodologyVersion": METHODOLOGY_VERSION,
        "weights": weights,
        "components": {
            "impact": {
                "business": js_round(main["business"]),
                "peopleData": js_round(main["peopleData"]),
                "ai": js_round(main["ai"]),
            },
            "likelihood": {
                "occurrence": js_round(occurrence),
                "feasibility": js_round(feasibility),
            },
            "existingControlStrength": js_round(control_strength),
            "controlMultiplier": js_round(control_multiplier),
        },
        "impactScore": js_round(impact_score),
        "inherentLikelihood": js_round(inherent_likelihood),
        "residualLikelihood": js_round(residual_likelihood),
        "inherentRiskScore": inherent_risk,
        "residualRiskScore": residual_risk,
        "residualRiskGovernance": governance,
    }


def _unwrap_all(node):
    if isinstance(node, dict) and set(node.keys()) >= {"value"} and not any(
        isinstance(v, dict) and "value" not in v for v in node.values() if isinstance(v, dict)
    ):
        # leaf-like {value, source}
        if "value" in node and not any(isinstance(node.get(k), dict) for k in node if k != "value"):
            return node.get("value")
    if isinstance(node, dict):
        if "value" in node and all(k in {"value", "source", "why", "descriptor"} for k in node):
            return node.get("value")
        return {key: _unwrap_all(value) for key, value in node.items()}
    return node


def build_calculation_trace(result: dict, screening: dict) -> dict:
    gov = result.get("residualRiskGovernance") or {}
    weights = result.get("weights") or {}
    components = result.get("components") or {}
    return {
        "methodologyVersion": METHODOLOGY_VERSION,
        "screening": screening,
        "impact": {
            "businessScore": (components.get("impact") or {}).get("business"),
            "peopleDataScore": (components.get("impact") or {}).get("peopleData"),
            "aiScore": (components.get("impact") or {}).get("ai"),
            "weights": weights.get("impactMain"),
            "impactScore": result.get("impactScore"),
            "scale": "3-15",
        },
        "likelihood": {
            "weightedOccurrence": (components.get("likelihood") or {}).get("occurrence"),
            "weightedFailureMisuse": (components.get("likelihood") or {}).get("feasibility"),
            "occurrenceWeights": (weights.get("likelihood") or {}).get("occurrence"),
            "feasibilityWeights": (weights.get("likelihood") or {}).get("feasibility"),
            "inherentLikelihood": result.get("inherentLikelihood"),
            "residualLikelihood": result.get("residualLikelihood"),
            "scale": "3-15",
        },
        "controls": {
            "weights": weights.get("existingControls"),
            "weightedControlStrength": components.get("existingControlStrength"),
            "controlMultiplier": components.get("controlMultiplier"),
            "direction": "1 = strongest controls, 5 = weakest / absent",
        },
        "risk": {
            "inherentRiskScore": result.get("inherentRiskScore"),
            "residualRiskScore": result.get("residualRiskScore"),
            "formula": "((Impact × Likelihood) / 225) × 100",
            "finalTierUses": "residualRiskScore",
        },
        "governance": gov,
    }


def calculate_assessment(assessment: dict, *, enforce_human_approval: bool = True) -> dict:
    """Official assessment pipeline with provenance gate and audit trace.

    The LLM must not call this to invent a score. Callers pass confirmed inputs.
    """
    assessment = assessment or {}
    if enforce_human_approval:
        require_human_approval(assessment.get("humanReview"))

    raw_scores = assessment.get("scores") or {}
    provenance = assessment.get("provenance")
    official_scores, rejected = filter_official_scores(raw_scores, provenance)
    if rejected and enforce_human_approval:
        raise ProvenanceError(
            "Official scoring rejected AI_SUGGESTED or unconfirmed values.",
            rejected=rejected,
        )

    # When provenance wrappers were used, official_scores is the cleaned tree.
    # When plain numbers were sent without provenance, filter keeps them as HUMAN_ENTERED.
    scores_for_engine = official_scores if official_scores else _unwrap_all(raw_scores)

    input_errors = validate_assessment_inputs(
        {"screening": assessment.get("screening"), "scores": scores_for_engine}
    )
    if input_errors:
        return {
            "complete": False,
            "methodologyVersion": METHODOLOGY_VERSION,
            "errors": input_errors,
            "contradictions": detect_contradictions(assessment),
        }

    screening = normalize_screening(assessment.get("screening"))
    # Bridge boolean screening into triage keys used by weight helpers.
    triage = {
        "sensitive": "Yes" if screening["data"] else "No",
        "decision": "Yes" if screening["decision"] else "No",
        "action": "Yes" if screening["action"] else "No",
    }
    core = calculate_risk(scores_for_engine, triage)
    if not core.get("complete"):
        return {
            **core,
            "errors": incomplete_score_paths(scores_for_engine),
            "contradictions": detect_contradictions(assessment),
        }

    governance = core["residualRiskGovernance"] or {}
    treatment = get_governance_requirements(governance.get("tier"))
    contradictions = detect_contradictions(
        {
            **assessment,
            "screening": screening,
            "scores": scores_for_engine,
        }
    )
    if governance.get("tier") in {"Tier 3", "Tier 4"}:
        contradictions.append(
            {
                "code": "high_tier_treatment_required",
                "level": "mandatory",
                "message": f"{governance.get('tier')} residual risk requires formal treatment / governance review.",
            }
        )

    mandatory_flags = [
        flag for flag in contradictions if flag.get("level") == "mandatory"
    ]
    components = core["components"]
    weights = core["weights"]

    return {
        "complete": True,
        "methodologyVersion": METHODOLOGY_VERSION,
        "inherentRiskScore": core["inherentRiskScore"],
        "residualRiskScore": core["residualRiskScore"],
        "severity": governance.get("severity"),
        "riskTier": governance.get("tier"),
        "approvalLevel": governance.get("approval"),
        "managerLevel": governance.get("managerLevel"),
        "impactScore": core["impactScore"],
        "inherentLikelihood": core["inherentLikelihood"],
        "residualLikelihood": core["residualLikelihood"],
        "weightedOccurrence": components["likelihood"]["occurrence"],
        "weightedFailureMisuse": components["likelihood"]["feasibility"],
        "weightedControlStrength": components["existingControlStrength"],
        "controlMultiplier": components["controlMultiplier"],
        "impactWeights": weights["impactMain"],
        "likelihoodWeights": weights["likelihood"],
        "controlWeights": weights["existingControls"],
        "mandatoryReviewFlags": mandatory_flags,
        "contradictions": contradictions,
        "treatmentRequirements": treatment,
        "calculationTrace": build_calculation_trace(core, screening),
        # Compatibility with earlier API consumers:
        "weights": weights,
        "components": components,
        "residualRiskGovernance": governance,
    }


def factor_schema() -> dict:
    return {
        "methodologyVersion": METHODOLOGY_VERSION,
        "impact": IMPACT_FACTORS,
        "likelihood": LIKELIHOOD_FACTORS,
        "controls": CONTROL_FACTORS,
        "scoreScale": {"min": 1, "max": 5, "integer": True},
        "controlDirection": "1 is strong control, 5 is weak or absent",
        "impactScale": "3-15",
        "likelihoodScale": "3-15",
        "riskFormula": "((Impact × Likelihood) / 225) × 100",
        "finalTierSource": "residualRiskScore",
        "officialScoreSources": sorted(
            {"HUMAN_ENTERED", "HUMAN_CONFIRMED", "HUMAN_EDITED"}
        ),
        "descriptors": all_descriptors(),
        "subFactorCount": {
            "impact": 25,
            "likelihood": 10,
            "controls": 5,
            "total": 40,
        },
    }
