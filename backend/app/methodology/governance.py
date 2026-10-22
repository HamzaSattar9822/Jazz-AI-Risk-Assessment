"""Residual-risk tiering and mandatory treatment / governance requirements.

Final approval always comes from residual risk. Inherent risk is informational.
"""

from __future__ import annotations

TREATMENT_OPTIONS = [
    "Avoid",
    "Reduce / Mitigate",
    "Transfer / Share",
    "Accept",
]

TREATMENT_OPTION_DEFINITIONS = {
    "Avoid": "Do not undertake, discontinue, or redesign the activity so that the unacceptable risk condition no longer exists.",
    "Reduce / Mitigate": "Implement controls or changes that reduce likelihood and/or consequence.",
    "Transfer / Share": "Allocate or share defined risk responsibilities through contractual, insurance, supplier, or other approved mechanisms, without transferring JazzWorld accountability for mandatory obligations.",
    "Accept": "Formally accept residual risk within the authority assigned to the applicable Residual Risk Tier, subject to all mandatory requirements.",
}

TREATMENT_PLAN_FIELDS = [
    "riskScenario",
    "riskEvent",
    "rootCause",
    "consequence",
    "treatmentOption",
    "riskOwner",
    "treatmentOwner",
    "actions",
    "controls",
    "targetDates",
    "dependencies",
    "expectedResidualRisk",
    "implementationEvidence",
    "controlEffectivenessEvidence",
    "reassessmentRequirement",
    "approvalStatus",
]

TIER_REQUIREMENTS = {
    "Tier 1": {
        "severity": "Low",
        "approval": "Self-Review",
        "managerLevel": "N/A",
        "minimumTreatment": [
            "Baseline controls",
            "Accountable owner",
            "Assessment retained",
            "Routine monitoring",
        ],
        "formalTreatmentPlanRequired": False,
        "raioReviewRequired": False,
        "specialistReviewRequired": False,
        "residualRiskReassessmentRequired": False,
        "explicitSeniorAcceptanceRequired": False,
    },
    "Tier 2": {
        "severity": "Medium",
        "approval": "Line Manager",
        "managerLevel": "L4 / L3",
        "minimumTreatment": [
            "Documented mitigation for material gaps",
            "Accountable owner",
            "Target date",
            "Relevant specialist review where triggered",
            "Residual risk retained in assessment record",
        ],
        "formalTreatmentPlanRequired": False,
        "raioReviewRequired": False,
        "specialistReviewRequired": "where_triggered",
        "residualRiskReassessmentRequired": False,
        "explicitSeniorAcceptanceRequired": False,
    },
    "Tier 3": {
        "severity": "High",
        "approval": "Head of Department / Function",
        "managerLevel": "L5",
        "minimumTreatment": [
            "Formal risk treatment plan",
            "Relevant specialist review",
            "Enhanced controls implemented or formally committed",
            "Residual risk reassessed",
            "RAIO governance review and challenge",
        ],
        "formalTreatmentPlanRequired": True,
        "raioReviewRequired": True,
        "specialistReviewRequired": True,
        "residualRiskReassessmentRequired": True,
        "explicitSeniorAcceptanceRequired": False,
    },
    "Tier 4": {
        "severity": "Critical",
        "approval": "C-Suite",
        "managerLevel": "L6",
        "minimumTreatment": [
            "Formal treatment plan",
            "Mandatory RAIO review",
            "Relevant specialist review",
            "Material risk reduction expected before approval",
            "Residual risk reassessed",
            "Explicit acceptance by senior authority",
        ],
        "formalTreatmentPlanRequired": True,
        "raioReviewRequired": True,
        "specialistReviewRequired": True,
        "residualRiskReassessmentRequired": True,
        "explicitSeniorAcceptanceRequired": True,
    },
}


def get_risk_tier(residual_risk_score: int | None) -> dict | None:
    if residual_risk_score is None:
        return None
    if residual_risk_score >= 80:
        tier = "Tier 4"
    elif residual_risk_score >= 60:
        tier = "Tier 3"
    elif residual_risk_score >= 26:
        tier = "Tier 2"
    else:
        tier = "Tier 1"
    requirements = TIER_REQUIREMENTS[tier]
    return {
        "severity": requirements["severity"],
        "tier": tier,
        "approval": requirements["approval"],
        "managerLevel": requirements["managerLevel"],
    }


def get_governance_requirements(tier: str | None) -> dict | None:
    if not tier or tier not in TIER_REQUIREMENTS:
        return None
    row = TIER_REQUIREMENTS[tier]
    return {
        "tier": tier,
        "severity": row["severity"],
        "approvalLevel": row["approval"],
        "managerLevel": row["managerLevel"],
        "minimumTreatment": list(row["minimumTreatment"]),
        "formalTreatmentPlanRequired": row["formalTreatmentPlanRequired"],
        "raioReviewRequired": row["raioReviewRequired"],
        "specialistReviewRequired": row["specialistReviewRequired"],
        "residualRiskReassessmentRequired": row["residualRiskReassessmentRequired"],
        "explicitSeniorAcceptanceRequired": row["explicitSeniorAcceptanceRequired"],
        "treatmentOptions": list(TREATMENT_OPTIONS),
        "treatmentOptionDefinitions": dict(TREATMENT_OPTION_DEFINITIONS),
        "treatmentPlanFields": list(TREATMENT_PLAN_FIELDS),
    }


def risk_statement(risk_event: str, root_cause: str, consequence: str) -> str:
    event = (risk_event or "").strip() or "[Risk Event]"
    cause = (root_cause or "").strip() or "[Cause / Root Cause]"
    result = (consequence or "").strip() or "[Consequence / Impact]"
    return (
        f"There is a risk that {event}, "
        f"caused by {cause}, "
        f"resulting in {result}."
    )
