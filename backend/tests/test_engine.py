import json
from pathlib import Path

from app.methodology.engine import calculate_risk, get_weight_profile

GOLDENS = json.loads(Path(__file__).parent.joinpath("fixtures/aira_goldens.json").read_text())

TRIAGE = {
    "none": {"sensitive": "No", "decision": "No", "action": "No"},
    "data": {"sensitive": "Yes", "decision": "No", "action": "No"},
    "decision": {"sensitive": "No", "decision": "Yes", "action": "No"},
    "action": {"sensitive": "No", "decision": "No", "action": "Yes"},
    "all": {"sensitive": "Yes", "decision": "Yes", "action": "Yes"},
    "unsure": {"sensitive": "Not sure", "decision": "not sure", "action": "YES"},
}


def _diff(actual, expected, path=""):
    mismatches = []
    if isinstance(actual, dict) and isinstance(expected, dict):
        if set(actual) != set(expected):
            mismatches.append(f"{path} keys {set(actual) ^ set(expected)}")
        for key in actual:
            if key in expected:
                mismatches.extend(_diff(actual[key], expected[key], f"{path}.{key}"))
        return mismatches
    if actual != expected:
        mismatches.append(f"{path}: {actual!r} != {expected!r}")
    return mismatches


def test_scores_match_portal_engine():
    for case in GOLDENS["cases"]:
        actual = calculate_risk(case["scores"], case["triage"])
        mismatches = _diff(actual, case["result"])
        assert not mismatches, f"{case['name']}: {mismatches[:8]}"


def test_weight_profiles_match_portal_engine():
    for name, expected in GOLDENS["weights"].items():
        actual = get_weight_profile(TRIAGE[name])
        mismatches = _diff(actual, expected)
        assert not mismatches, f"{name}: {mismatches[:8]}"


def test_not_sure_is_not_yes_inside_the_engine():
    profile = get_weight_profile({"sensitive": "Not sure", "decision": "No", "action": "No"})
    assert profile["screening"]["data"] is False
