"""Official AIRA-DDA-1.0 methodology package.

Deterministic scoring lives here. The LLM must not invent or override scores.
"""

from app.methodology.engine import (
    METHODOLOGY_VERSION,
    calculate_assessment,
    calculate_risk,
    factor_schema,
    get_weight_profile,
    risk_level,
)
from app.methodology.governance import get_governance_requirements, get_risk_tier, risk_statement

__all__ = [
    "METHODOLOGY_VERSION",
    "calculate_assessment",
    "calculate_risk",
    "factor_schema",
    "get_governance_requirements",
    "get_risk_tier",
    "get_weight_profile",
    "risk_level",
    "risk_statement",
]
