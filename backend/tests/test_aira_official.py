"""Official AIRA-DDA-1.0 methodology tests.

These assert the deterministic engine - never LLM behaviour.
"""

import pytest

from app.methodology.engine import (
    METHODOLOGY_VERSION,
    calculate_assessment,
    calculate_control_multiplier,
    calculate_risk,
    calculate_risk_score,
    get_weight_profile,
    risk_level,
)
from app.methodology.governance import get_governance_requirements, get_risk_tier
from app.methodology.provenance import ProvenanceError
from app.methodology.engine import IMPACT_FACTORS, LIKELIHOOD_FACTORS, CONTROL_FACTORS


def _uniform(score: int) -> dict:
    return {
        "impact": {
            group: {name: score for name in names} for group, names in IMPACT_FACTORS.items()
        },
        "likelihood": {
            group: {name: score for name in names} for group, names in LIKELIHOOD_FACTORS.items()
        },
        "controls": {name: score for name in CONTROL_FACTORS},
    }


def _triage(**flags):
    return {
        "sensitive": "Yes" if flags.get("data") else "No",
        "decision": "Yes" if flags.get("decision") else "No",
        "action": "Yes" if flags.get("action") else "No",
    }


def _screening(**flags):
    return {
        "data": bool(flags.get("data")),
        "decision": bool(flags.get("decision")),
        "action": bool(flags.get("action")),
    }


@pytest.mark.parametrize(
    "score,tier",
    [
        (1, "Tier 1"),
        (25, "Tier 1"),
        (26, "Tier 2"),
        (59, "Tier 2"),
        (60, "Tier 3"),
        (79, "Tier 3"),
        (80, "Tier 4"),
        (100, "Tier 4"),
    ],
)
def test_residual_tier_boundaries(score, tier):
    assert get_risk_tier(score)["tier"] == tier
    assert risk_level(score)["tier"] == tier


def test_final_tier_comes_from_residual_not_inherent():
    # Strong controls can pull residual below inherent; tier must follow residual.
    scores = _uniform(5)
    scores["controls"] = {name: 1 for name in CONTROL_FACTORS}  # strong controls
    result = calculate_risk(scores, _triage(data=True, decision=True, action=True))
    assert result["complete"] is True
    assert result["inherentRiskScore"] >= result["residualRiskScore"]
    assert result["residualRiskGovernance"] == get_risk_tier(result["residualRiskScore"])


@pytest.mark.parametrize("score", [1, 3, 5])
@pytest.mark.parametrize(
    "flags",
    [
        {},
        {"data": True},
        {"decision": True},
        {"action": True},
        {"data": True, "decision": True},
        {"data": True, "action": True},
        {"decision": True, "action": True},
        {"data": True, "decision": True, "action": True},
    ],
)
def test_uniform_scores_complete_for_all_screening(score, flags):
    result = calculate_risk(_uniform(score), _triage(**flags))
    assert result["complete"] is True
    assert result["methodologyVersion"] == METHODOLOGY_VERSION
    assert 1 <= result["inherentRiskScore"] <= 100
    assert 1 <= result["residualRiskScore"] <= 100
    assert 3 <= result["impactScore"] <= 15
    assert 3 <= result["inherentLikelihood"] <= 15
    assert 3 <= result["residualLikelihood"] <= 15


def test_control_multiplier_table():
    assert calculate_control_multiplier(1) == pytest.approx(0.60)
    assert calculate_control_multiplier(2) == pytest.approx(0.70)
    assert calculate_control_multiplier(3) == pytest.approx(0.80)
    assert calculate_control_multiplier(4) == pytest.approx(0.90)
    assert calculate_control_multiplier(5) == pytest.approx(1.00)


def test_risk_score_rounding_and_clamp():
    assert calculate_risk_score(15, 15) == 100
    assert calculate_risk_score(3, 3) == 4  # (9/225)*100 = 4
    assert calculate_risk_score(0, 0) == 1  # clamped


def test_dynamic_impact_weights_data_decision_action():
    none = get_weight_profile(_triage())
    assert none["impactMain"]["business"] == pytest.approx(1 / 3, abs=1e-5)
    all_on = get_weight_profile(_triage(data=True, decision=True, action=True))
    # base 2+0+1+2=5 business, people 2+2+2+1=7, ai 2+1+2+2=7 => 5/19, 7/19, 7/19
    assert all_on["impactMain"]["business"] == pytest.approx(5 / 19, abs=1e-5)
    assert all_on["impactMain"]["peopleData"] == pytest.approx(7 / 19, abs=1e-5)
    assert all_on["impactMain"]["ai"] == pytest.approx(7 / 19, abs=1e-5)


def test_control_profile_average_for_data_and_decision():
    weights = get_weight_profile(_triage(data=True, decision=True))["existingControls"]
    # Preventive (25+15)/2 = 20% of 100 => normalized share 0.20
    assert weights["Preventive Controls"] == pytest.approx(0.20, abs=1e-5)
    assert weights["Detective Controls"] == pytest.approx(0.175, abs=1e-5)
    assert weights["Human Oversight Controls"] == pytest.approx(0.20, abs=1e-5)
    assert weights["Governance Controls"] == pytest.approx(0.225, abs=1e-5)
    assert weights["Control Validation / Testing"] == pytest.approx(0.20, abs=1e-5)
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-5)


def test_official_assessment_requires_human_approval():
    with pytest.raises(ProvenanceError):
        calculate_assessment(
            {
                "screening": _screening(data=True),
                "scores": _uniform(3),
                "humanReview": {"status": "PENDING"},
            }
        )


def test_ai_suggested_scores_rejected():
    scores = _uniform(3)
    scores["impact"]["business"]["Business Criticality"] = {
        "value": 5,
        "source": "AI_SUGGESTED",
    }
    with pytest.raises(ProvenanceError) as exc:
        calculate_assessment(
            {
                "screening": _screening(data=True, decision=True, action=True),
                "scores": scores,
                "humanReview": {"status": "APPROVED", "reviewedBy": "rahim.qureshi@jazz.example"},
            }
        )
    assert any("Business Criticality" in path for path in exc.value.rejected)


def test_human_confirmed_assessment_returns_trace_and_governance():
    result = calculate_assessment(
        {
            "screening": _screening(data=True, decision=True, action=True),
            "scores": _uniform(3),
            "humanReview": {"status": "APPROVED", "reviewedBy": "rahim.qureshi@jazz.example"},
            "context": {
                "humanReview": "Always",
                "autonomy": "Can take actions automatically across a workflow",
            },
            "mandatoryRequirements": {"privacy": True},
        }
    )
    assert result["complete"] is True
    assert result["methodologyVersion"] == METHODOLOGY_VERSION
    assert "calculationTrace" in result
    assert result["calculationTrace"]["risk"]["finalTierUses"] == "residualRiskScore"
    assert result["riskTier"] == result["residualRiskGovernance"]["tier"]
    assert result["treatmentRequirements"] == get_governance_requirements(result["riskTier"])
    codes = {flag["code"] for flag in result["contradictions"]}
    assert "oversight_vs_autonomy" in codes
    assert "mandatory_privacy" in codes
    assert any(flag["code"] == "mandatory_privacy" for flag in result["mandatoryReviewFlags"])


def test_tier3_and_tier4_force_treatment_flag():
    high = calculate_assessment(
        {
            "screening": _screening(data=True, decision=True, action=True),
            "scores": _uniform(5),
            "humanReview": {"status": "APPROVED"},
        }
    )
    assert high["residualRiskScore"] >= 80
    assert any(flag["code"] == "high_tier_treatment_required" for flag in high["contradictions"])


def test_strong_vs_weak_controls_change_residual():
    scores_strong = _uniform(4)
    scores_strong["controls"] = {n: 1 for n in CONTROL_FACTORS}
    scores_weak = _uniform(4)
    scores_weak["controls"] = {n: 5 for n in CONTROL_FACTORS}
    strong = calculate_risk(scores_strong, _triage(data=True))
    weak = calculate_risk(scores_weak, _triage(data=True))
    assert strong["residualRiskScore"] <= weak["residualRiskScore"]
    assert strong["inherentRiskScore"] == weak["inherentRiskScore"]
