from app.intake.catalog import (
    EXAMPLES,
    effective_answer,
    flags_for,
    keyword_extract,
    route_for,
)
from app.intake.duplicates import compare_submissions
from app.methodology.engine import get_weight_profile


def test_keyword_extractor_reads_the_portal_examples():
    credit = keyword_extract(EXAMPLES[1])
    assert credit["category"]["value"] == "AI By Us"
    assert credit["name"] == {
        "value": "Credit Line Recommender",
        "why": "you named it",
        "source": "description",
    }
    assert credit["sensitive"]["value"] == "Yes"
    assert credit["decision"]["value"] == "Yes"
    assert credit["humanReview"]["value"] == "Always"
    assert credit["dataExternal"]["value"] == "Yes"

    threat = keyword_extract(EXAMPLES[2])
    assert threat["category"]["value"] == "AI Against Us"
    assert threat["threatTypes"]["value"] == ["Deepfake / impersonation", "Fraud / scam"]

    tool = keyword_extract(EXAMPLES[0])
    assert tool["category"]["value"] == "AI For Us"
    assert tool["forTool"]["value"] == "Microsoft Copilot"
    assert tool["forAccess"]["value"] == "JazzWorld enterprise / corporate account"


def test_category_classifier_separates_for_by_against(monkeypatch):
    from app.config import Settings
    from app.intake.catalog import classify_category
    from app.services import intake_flow

    assert classify_category(
        "Subscribe to a vendor chatbot SaaS for HR FAQs on enterprise accounts."
    )["value"] == "AI For Us"
    assert classify_category(
        "We are building an in-house churn model trained on customer data, hosted on Azure."
    )["value"] == "AI By Us"
    assert classify_category(
        "Assess deepfake voice-clone phishing aimed at our executives and payment staff."
    )["value"] == "AI Against Us"

    # Even if Gemma wrongly returns AI For Us, classifier wins for By Us / Against Us.
    monkeypatch.setattr(
        intake_flow,
        "llm_extract",
        lambda description, settings, focus_ids=None: {
            "category": {
                "value": "AI For Us",
                "why": "mentions a tool",
                "source": "llm",
            }
        },
    )
    settings = Settings()
    by_us, extractor = intake_flow._extract(
        "We're developing our own recommender prototype trained internally.",
        settings,
    )
    assert extractor == "llm"
    assert by_us["category"]["value"] == "AI By Us"
    against, _ = intake_flow._extract(
        "Voice-cloned executive calls are a deepfake threat we need to assess.",
        settings,
    )
    assert against["category"]["value"] == "AI Against Us"


def test_flags_and_routing_follow_the_portal_rules():
    values = {
        "category": "AI For Us",
        "sensitive": "Yes",
        "decision": "Yes",
        "action": "Yes",
        "forAccess": "Public / free web service",
        "dataExternal": "Yes",
        "humanReview": "No - AI output can determine the outcome",
        "autonomy": "Can take actions automatically across a workflow",
    }
    titles = [flag["title"] for flag in flags_for(values)]
    assert titles[0] == "Sensitive information in a public or personal AI account"
    assert "Sensitive information goes to an outside provider" in titles
    assert "No person checks the output before decisions are made" in titles
    assert "It can act automatically across a workflow" in titles
    assert not any("Not sure" in title for title in titles)
    assert route_for(values) == [
        "RAIO",
        "Privacy / Data Protection",
        "Cybersecurity",
        "Legal / Compliance",
        "Technology / Cybersecurity",
        "Supplier / Procurement Review",
    ]


def test_apply_extractions_can_update_confirmed_slots_from_chat():
    from app.intake.catalog import apply_extractions, initial_state

    state = initial_state("Ayesha Khan", "Technology", "Roll out Copilot.")
    apply_extractions(
        state,
        {"sensitive": {"value": "Yes", "why": "contracts", "source": "description"}},
    )
    state["slots"]["sensitive"]["status"] = "confirmed"
    changed = apply_extractions(
        state,
        {"sensitive": {"value": "No", "why": "user correction", "source": "you"}},
        allow_update=True,
        mark_confirmed=True,
    )
    assert changed == ["sensitive"]
    assert state["slots"]["sensitive"]["value"] == "No"
    assert state["slots"]["sensitive"]["status"] == "confirmed"
    # Profile fields stay locked.
    apply_extractions(
        state,
        {"owner": {"value": "Someone Else", "why": "x", "source": "you"}},
        allow_update=True,
        mark_confirmed=True,
    )
    assert state["slots"]["owner"]["value"] == "Ayesha Khan"


def test_business_value_fields_extract_when_stated():
    text = (
        "We are building a corporate AI assistant for employees to improve productivity. "
        "Estimated annual value is USD 20000, investment 50000, spent to date 5000, "
        "saving about 40-60 hours per month."
    )
    found = keyword_extract(text)
    assert found["segment"]["value"] == "Corporate AI"
    assert found["valueDriver"]["value"] == "Productivity"
    assert "20000" in found["annualValue"]["value"].replace(",", "")
    assert "50000" in found["investmentCost"]["value"].replace(",", "")
    assert "5000" in found["spendingToDate"]["value"].replace(",", "")
    assert "hours" in found["hoursSaved"]["value"].lower()


def test_screening_options_are_yes_or_no_only():
    from app.intake.catalog import AUTONOMY, HUMAN_REVIEW, SLOTS_BY_ID, YNN

    assert YNN == ["Yes", "No"]
    assert "Not sure" not in YNN
    assert "Not decided yet" not in HUMAN_REVIEW
    assert "Not decided yet" not in AUTONOMY
    for slot_id in ("sensitive", "decision", "action", "dataExternal"):
        assert list(SLOTS_BY_ID[slot_id].option_values) == ["Yes", "No"]
    # Legacy stored "Not sure" is no longer treated as Yes.
    assert effective_answer("Not sure") == "No"
    profile = get_weight_profile(
        {
            "sensitive": effective_answer("Yes"),
            "decision": effective_answer("No"),
            "action": effective_answer("Yes"),
        }
    )
    assert profile["screening"] == {"data": True, "decision": False, "action": True}


def test_drop_ungrounded_rejects_copilot_example_leak():
    from app.intake.llm import drop_ungrounded_extractions

    leaked = drop_ungrounded_extractions(
        {
            "name": {
                "value": "Microsoft Copilot for Finance",
                "why": "example",
                "source": "llm",
            },
            "forTool": {
                "value": "Microsoft Copilot",
                "why": "example",
                "source": "llm",
            },
            "summary": {
                "value": "Request to roll out Microsoft Copilot for finance on enterprise accounts.",
                "why": "example",
                "source": "llm",
            },
            "dataExternal": {
                "value": "Yes",
                "why": "invented",
                "source": "llm",
            },
            "category": {
                "value": "AI By Us",
                "why": "build",
                "source": "llm",
            },
        },
        "I want to build a chatbot that uses customer data",
    )
    assert "name" not in leaked
    assert "forTool" not in leaked
    assert "summary" not in leaked
    assert "dataExternal" not in leaked
    assert leaked["category"]["value"] == "AI By Us"

    grounded = drop_ungrounded_extractions(
        {
            "name": {"value": "Microsoft Copilot", "why": "named", "source": "llm"},
            "forTool": {"value": "Microsoft Copilot", "why": "named", "source": "llm"},
            "dataExternal": {"value": "Yes", "why": "copilot", "source": "llm"},
        },
        "Roll out Microsoft Copilot for the finance team.",
    )
    assert grounded["name"]["value"] == "Microsoft Copilot"
    assert grounded["forTool"]["value"] == "Microsoft Copilot"
    assert grounded["dataExternal"]["value"] == "Yes"


def test_data_external_not_invented_without_provider():
    from app.intake.catalog import flags_for, keyword_extract

    vague = keyword_extract(
        "We are building an internal customer-support chatbot that will use customer "
        "names, CNICs, and account balances to draft replies."
    )
    assert "dataExternal" not in vague
    assert vague["sensitive"]["value"] == "Yes"
    titles = [flag["title"] for flag in flags_for({**{k: v["value"] for k, v in vague.items()}, "dataExternal": ""})]
    assert "Sensitive information goes to an outside provider" not in titles

    azure = keyword_extract(
        "Building a recommender trained on customer data and hosted on Azure."
    )
    assert azure["dataExternal"]["value"] == "Yes"
    assert "Sensitive information goes to an outside provider" in [
        flag["title"]
        for flag in flags_for(
            {
                "sensitive": "Yes",
                "dataExternal": "Yes",
                "decision": "No",
                "action": "No",
            }
        )
    ]


def test_second_pass_extract_fills_empties_only(monkeypatch):
    from app.config import Settings
    from app.intake.catalog import apply_extractions, initial_state
    from app.services import intake_flow

    calls = {"n": 0}
    description = "Roll out Microsoft Copilot for finance on enterprise accounts."

    def fake_llm(description, settings, focus_ids=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "name": {"value": "Copilot Finance", "why": "named", "source": "llm"},
            }
        assert focus_ids and "forTool" in focus_ids
        return {
            "forTool": {
                "value": "Microsoft Copilot",
                "why": "stated in description",
                "source": "llm",
            },
            "forAccess": {
                "value": "JazzWorld enterprise / corporate account",
                "why": "enterprise accounts",
                "source": "llm",
            },
        }

    monkeypatch.setattr(intake_flow, "llm_extract", fake_llm)
    monkeypatch.setattr(intake_flow, "keyword_extract", lambda _text: {})
    settings = Settings()
    state = initial_state("Ayesha Khan", "Technology", description)
    found, _ = intake_flow._extract(description, settings)
    apply_extractions(state, found)
    intake_flow._confirm_inferred(state)
    assert state["slots"]["name"]["status"] == "confirmed"
    assert state["slots"]["forTool"]["status"] == "empty"
    empty_ids = intake_flow._empty_fillable_ids(state)
    more, _ = intake_flow._extract(description, settings, focus_ids=empty_ids)
    applied = apply_extractions(state, more, allow_update=False, mark_confirmed=True)
    intake_flow._confirm_inferred(state)
    assert calls["n"] == 2
    assert "forTool" in applied
    assert state["slots"]["forTool"]["value"] == "Microsoft Copilot"
    assert state["slots"]["forTool"]["status"] == "confirmed"
    assert state["slots"]["name"]["value"] == "Copilot Finance"


def test_duplicate_score_matches_the_portal_weights():
    current = {
        "category": "AI By Us",
        "name": "Credit Line Recommender",
        "summary": "Scores customers for a credit limit",
        "description": "Scores customers for a credit limit using transaction history",
        "requirements": "Type: AI By Us",
        "screening": "Yes | Yes | No",
    }
    assert compare_submissions(current, current) == 100
    category_only = {key: "" for key in current}
    category_only["category"] = current["category"]
    assert compare_submissions(current, category_only) == 7


def test_early_flags_cover_personal_financial_and_customer_output():
    titles = [
        flag["title"]
        for flag in flags_for(
            {
                "sensitive": "Yes",
                "action": "Yes",
                "dataExternal": "No",
                "summary": "Drafts replies to customers using account balances and billing history.",
            }
        )
    ]
    assert "Uses personal or sensitive data" in titles
    assert "Uses financial data" in titles
    assert "Output reaches customers" in titles


def test_llm_numbers_and_threat_category_must_be_grounded():
    from app.intake.llm import drop_ungrounded_extractions

    desc = "A customer support assistant that drafts replies to customers using account balances."
    invented = {
        slot_id: {"value": value}
        for slot_id, value in {
            "annualValue": "0",
            "investmentCost": "0",
            "spendingToDate": "0",
            "hoursSaved": "0",
            "category": "AI Against Us",
            "threatTypes": ["Phishing / social engineering"],
        }.items()
    }
    assert drop_ungrounded_extractions(invented, desc) == {}
    kept = drop_ungrounded_extractions(
        {"investmentCost": {"value": "PKR 1,000,000"}, "spendingToDate": {"value": "0"}},
        "The project will cost about PKR 1 million and we haven't started building.",
    )
    assert set(kept) == {"investmentCost", "spendingToDate"}


def test_stray_digits_do_not_ground_invented_numbers():
    from app.intake.llm import drop_ungrounded_extractions

    desc = "Use Microsoft 365 Copilot to summarise customer care tickets 24/7 for the support team."
    invented = {
        "annualValue": {"value": "0"},
        "investmentCost": {"value": "USD 50,000"},
        "spendingToDate": {"value": "0"},
        "hoursSaved": {"value": "2,400 hours"},
    }
    assert drop_ungrounded_extractions(invented, desc) == {}
    computed = drop_ungrounded_extractions(
        {"hoursSaved": {"value": "24,000 hours"}}, "Helps 50 staff save 10 hours a week each."
    )
    assert computed == {}
    stated = drop_ungrounded_extractions(
        {"annualValue": {"value": "USD 20,000"}, "hoursSaved": {"value": "960 hours / year"}},
        "Saves about $20k a year and 960 hours.",
    )
    assert set(stated) == {"annualValue", "hoursSaved"}
