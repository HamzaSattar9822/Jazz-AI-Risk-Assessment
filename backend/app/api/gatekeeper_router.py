
"""API endpoint for AIMS semantic definition validation.

This endpoint checks the meaning of a use-case description before
the normal intake begins.

It does not save intake sessions, approve projects, assign risk,
or modify existing user records.
"""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api import current_user
from app.config import get_settings
from app.models import User
from app.services.gatekeeper import validate_definition


router = APIRouter(
    prefix="/gatekeeper",
    tags=["Semantic Gatekeeper"],
)


class ClarificationIn(BaseModel):
    """One question-and-answer pair from Syra's mini-chat."""

    question: str = Field(
        default="",
        max_length=1500,
    )

    answer: str = Field(
        default="",
        max_length=1500,
    )


class GatekeeperValidateIn(BaseModel):
    """Description and previously collected clarifications."""

    description: str = Field(
        min_length=1,
        max_length=8000,
    )

    answers: list[ClarificationIn] = Field(
        default_factory=list,
        max_length=20,
    )


class GatekeeperFieldOut(BaseModel):
    status: Literal[
        "complete",
        "needs_clarification",
    ]

    value: str = ""
    evidence: str = ""
    question: str = ""


class GatekeeperValidateOut(BaseModel):
    """Stable response contract for the frontend."""

    status: Literal[
        "complete",
        "needs_clarification",
        "unavailable",
    ]

    validated: bool
    retryable: bool
    complete: bool

    fields: dict[str, GatekeeperFieldOut]

    missing: list[str]
    nextQuestion: str
    message: str
    errorCode: str | None = None


@router.post(
    "/validate",
    response_model=GatekeeperValidateOut,
)
def validate_gatekeeper(
    body: GatekeeperValidateIn,
    _user: User = Depends(current_user),
):
    """Validate the three mandatory use-case description elements.

    The original description and answers are supplied by the caller.

    A model outage produces an explicit unavailable response,
    never a successful validation.

    This endpoint is read-only: it does not persist or modify
    the description, answers, or any existing intake session.
    """

    answers = [
        {
            "question": item.question,
            "answer": item.answer,
        }
        for item in body.answers
    ]

    result = validate_definition(
        description=body.description,
        answers=answers,
        settings=get_settings(),
    )

    return result
