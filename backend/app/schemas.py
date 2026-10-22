from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LoginIn(BaseModel):
    email: str
    password: str


class SessionCreate(BaseModel):
    description: str = Field(min_length=15, max_length=8000)


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=6000)


class ConfirmIn(BaseModel):
    slotIds: list[str] | None = None


class AnswerIn(BaseModel):
    slotId: str
    value: Any


class ScreeningIn(BaseModel):
    data: str
    decision: str
    action: str


class AiSystemIn(BaseModel):
    name: str
    businessOwner: str
    businessUnit: str
    summary: str = ""
    description: str = ""


class SubmissionIn(BaseModel):
    """Payload posted by the approval portal."""

    model_config = ConfigDict(extra="allow")

    referenceId: str | None = None
    submittedAt: str | None = None
    category: str
    screening: ScreeningIn
    aiSystem: AiSystemIn
    conditionalInformation: dict = Field(default_factory=dict)
    provenance: dict = Field(default_factory=dict)
    intake: dict = Field(default_factory=dict)
    governance: dict = Field(default_factory=dict)


class TriageIn(BaseModel):
    sensitive: str = "No"
    decision: str = "No"
    action: str = "No"


class ScreeningBoolIn(BaseModel):
    data: bool = False
    decision: bool = False
    action: bool = False


class HumanReviewIn(BaseModel):
    status: Literal["APPROVED", "DRAFT", "REJECTED", "PENDING"] = "PENDING"
    reviewedBy: str = ""
    comments: str = ""


class CalculateIn(BaseModel):
    """Legacy calculator input (Yes/No triage). Prefer OfficialCalculateIn."""

    triage: TriageIn
    scores: dict


class OfficialCalculateIn(BaseModel):
    """Official AIRA assessment calculation request.

    The LLM must not invent this result. Scores should be human-confirmed.
    """

    screening: ScreeningBoolIn
    scores: dict
    provenance: dict = Field(default_factory=dict)
    humanReview: HumanReviewIn = Field(default_factory=HumanReviewIn)
    context: dict = Field(default_factory=dict)
    mandatoryRequirements: dict = Field(default_factory=dict)
    enforceHumanApproval: bool = True


class AssessmentIn(BaseModel):
    scores: dict
    notes: str = ""
    provenance: dict = Field(default_factory=dict)
    humanReview: HumanReviewIn = Field(default_factory=lambda: HumanReviewIn(status="APPROVED"))
    context: dict = Field(default_factory=dict)
    mandatoryRequirements: dict = Field(default_factory=dict)


class DecisionIn(BaseModel):
    outcome: Literal["approved", "approved_with_conditions", "rejected", "needs_information"]
    conditions: str = ""
    notes: str = ""

    @model_validator(mode="after")
    def conditions_required(self):
        if self.outcome == "approved_with_conditions" and not self.conditions.strip():
            raise ValueError("Conditions are required when approving with conditions.")
        return self


class MailTestIn(BaseModel):
    to: str = Field(min_length=3, max_length=255)
