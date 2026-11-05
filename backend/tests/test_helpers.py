from app.intake.helpers import (
    continue_helper,
    detect_helper_slot,
    format_helper_prompt,
    start_helper,
    wants_help,
)


def test_wants_help_and_detect_annual_value():
    text = "I want a finance chatbot but don't know its estimated annual value."
    assert wants_help(text)
    assert detect_helper_slot(text, ["annualValue", "name"]) == "annualValue"


def test_annual_value_helper_one_shot():
    state = {
        "helper": None,
        "slots": {"hoursSaved": {"status": "empty", "value": ""}},
    }
    prompt = start_helper(state, "annualValue")
    assert "estimated annual value" in prompt.lower() or "USD" in prompt
    assert "Monthly queries" in prompt
    assert "know the number" in prompt.lower() or "estimate" in prompt.lower()

    answers = "\n".join(
        [
            "8000",
            "4 people, 10 hours",
            "50%",
            "12000",
            "free employee time",
        ]
    )
    result = continue_helper(state, answers)
    assert result["done"] is True
    assert "annualValue" in result["extraction"]
    value = result["extraction"]["annualValue"]["value"]
    assert value.startswith("USD ")
    assert int(value[4:].replace(",", "")) >= 1000
    assert "(" not in result["reply"]
    assert "hoursSaved" in result["extraction"]
    assert "hours" in result["extraction"]["hoursSaved"]["value"].lower()
    assert state.get("helper") is None


def test_helper_prompt_lists_questions():
    body = format_helper_prompt("hoursSaved")
    assert "How many people would use this" in body
    assert "per week" in body.lower()


def test_hours_saved_uses_people_times_week_times_48():
    from app.intake.helpers import _estimate_hours

    value, why = _estimate_hours({"q1": "6-20", "q2": "1-2 hours"})
    # midpoint 13 people × 1.5 h/week × 48 weeks = 936
    assert value == "936 hours / year"
    assert "48" in why

    value2, _ = _estimate_hours({"q1": "1-5", "q2": "Under 1 hour"})
    # 3 × 0.5 × 48 = 72
    assert value2 == "72 hours / year"
