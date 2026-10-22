from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.api import COOKIE_NAME, current_user, reviewer
from app.config import get_settings
from app.db import get_db
from app.models import User
from app.schemas import (
    AnswerIn,
    AssessmentIn,
    CalculateIn,
    ConfirmIn,
    DecisionIn,
    LoginIn,
    MailTestIn,
    MessageIn,
    OfficialCalculateIn,
    SessionCreate,
    SubmissionIn,
    TriageIn,
)
from app.security import create_token, verify_password
from app.services.intake_flow import (
    IntakeError,
    add_message,
    answer_slot,
    confirm_slots,
    create_session,
    examples,
    extract_description,
    get_owned,
    reset_slot,
    view_session,
)
from app.services.submissions import (
    SubmissionError,
    get_visible,
    list_for,
    preview_duplicate,
    public_submission,
    save_assessment,
    save_decision,
    submit_portal,
    submit_state,
)
from app.methodology.engine import calculate_assessment, calculate_risk, factor_schema, get_weight_profile
from app.methodology.provenance import ProvenanceError

router = APIRouter()


def _user_out(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "businessUnit": user.business_unit,
        "role": user.role,
    }


def _raise_intake(exc: IntakeError):
    raise HTTPException(status_code=exc.status_code, detail={"message": exc.message})


def _raise_submission(exc: SubmissionError):
    raise HTTPException(status_code=exc.status_code, detail={"message": exc.message, **exc.extra})


@router.post("/auth/login")
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    from sqlalchemy import select

    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    settings = get_settings()
    token = create_token(user.id)
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        max_age=settings.jwt_expire_minutes * 60,
        path="/",
    )
    return {"accessToken": token, "tokenType": "bearer", "user": _user_out(user)}


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return _user_out(user)


@router.get("/intake/examples")
def intake_examples(_user: User = Depends(current_user)):
    return {"examples": examples()}


@router.post("/intake/extract")
def extract_fields(body: SessionCreate, user: User = Depends(current_user)):
    """Fill intake slots from a free-text description using the configured LLM."""
    try:
        return extract_description(body.description, get_settings())
    except IntakeError as exc:
        _raise_intake(exc)


@router.post("/intake/sessions", status_code=201)
def open_session(body: SessionCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        draft = create_session(db, user, body.description, get_settings())
    except IntakeError as exc:
        _raise_intake(exc)
    return view_session(draft)


@router.get("/intake/sessions/{session_id}")
def read_session(session_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        draft = get_owned(db, user, session_id)
    except IntakeError as exc:
        _raise_intake(exc)
    return view_session(draft)


@router.post("/intake/sessions/{session_id}/confirm")
def confirm(session_id: str, body: ConfirmIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        draft = get_owned(db, user, session_id)
        draft = confirm_slots(db, draft, body.slotIds)
    except IntakeError as exc:
        _raise_intake(exc)
    return view_session(draft)


@router.post("/intake/sessions/{session_id}/answers")
def answer(session_id: str, body: AnswerIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        draft = get_owned(db, user, session_id)
        draft = answer_slot(db, draft, body.slotId, body.value)
    except IntakeError as exc:
        _raise_intake(exc)
    return view_session(draft)


@router.post("/intake/sessions/{session_id}/messages")
def message(session_id: str, body: MessageIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        draft = get_owned(db, user, session_id)
        draft = add_message(db, draft, body.text, get_settings())
    except IntakeError as exc:
        _raise_intake(exc)
    return view_session(draft)


@router.post("/intake/sessions/{session_id}/slots/{slot_id}/clear")
def clear_slot(session_id: str, slot_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        draft = get_owned(db, user, session_id)
        draft = reset_slot(db, draft, slot_id)
    except IntakeError as exc:
        _raise_intake(exc)
    return view_session(draft)


@router.post("/intake/sessions/{session_id}/duplicate-check")
def duplicate_check(session_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        draft = get_owned(db, user, session_id)
    except IntakeError as exc:
        _raise_intake(exc)
    match = preview_duplicate(db, draft.state, draft.description, get_settings())
    return {"match": match, "blocked": bool(match and match["blocked"])}


@router.post("/intake/sessions/{session_id}/submit", status_code=201)
def submit_intake(session_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        draft = get_owned(db, user, session_id)
        if draft.status != "active":
            raise IntakeError("This request has already been submitted.", 409)
        view = view_session(draft)
        if not view["readyToSubmit"]:
            raise IntakeError("Confirm the remaining answers before submitting.", 422)
        row = submit_state(db, user, draft.state, draft.description, get_settings(), None, "conversational")
    except IntakeError as exc:
        _raise_intake(exc)
    except SubmissionError as exc:
        _raise_submission(exc)
    match = getattr(row, "duplicate_check", None)
    draft.status = "submitted"
    draft.submission_reference = row.reference_id
    db.commit()
    return public_submission(get_visible(db, user, row.reference_id), match)


@router.post("/submissions", status_code=201)
def submit_from_portal(body: SubmissionIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        row = submit_portal(db, user, body, get_settings())
    except SubmissionError as exc:
        _raise_submission(exc)
    match = getattr(row, "duplicate_check", None)
    return public_submission(get_visible(db, user, row.reference_id), match)


@router.get("/submissions")
def list_submissions(
    status: str | None = None,
    category: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    rows = list_for(db, user, status, category)
    return {
        "requests": [
            {
                "referenceId": row.reference_id,
                "status": row.status,
                "category": row.category,
                "name": (row.payload.get("aiSystem") or {}).get("name"),
                "businessUnit": (row.payload.get("aiSystem") or {}).get("businessUnit"),
                "submittedAt": public_submission(row)["submittedAt"],
                "routing": (row.payload.get("governance") or {}).get("indicativeRouting") or [],
                "residualRiskScore": ((row.assessment or {}).get("result") or {}).get("residualRiskScore"),
            }
            for row in rows
        ]
    }


@router.get("/submissions/{reference_id}")
def read_submission(reference_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        row = get_visible(db, user, reference_id)
    except SubmissionError as exc:
        _raise_submission(exc)
    return public_submission(row)


@router.post("/submissions/{reference_id}/assessment")
def assess(
    reference_id: str,
    body: AssessmentIn,
    user: User = Depends(reviewer),
    db: Session = Depends(get_db),
):
    try:
        row = get_visible(db, user, reference_id)
        save_assessment(
            db,
            user,
            row,
            body.scores,
            body.notes,
            provenance=body.provenance,
            human_review=body.humanReview.model_dump(),
            context=body.context,
            mandatory_requirements=body.mandatoryRequirements,
        )
        row = get_visible(db, user, reference_id)
    except SubmissionError as exc:
        _raise_submission(exc)
    return public_submission(row)


@router.post("/submissions/{reference_id}/decision")
def decide(
    reference_id: str,
    body: DecisionIn,
    user: User = Depends(reviewer),
    db: Session = Depends(get_db),
):
    try:
        row = get_visible(db, user, reference_id)
        save_decision(db, user, row, body.outcome, body.conditions, body.notes, get_settings())
        row = get_visible(db, user, reference_id)
    except SubmissionError as exc:
        _raise_submission(exc)
    return public_submission(row)


@router.get("/mail/status")
def mail_status_endpoint(_user: User = Depends(reviewer)):
    from app.mail.service import mail_status

    return mail_status(get_settings())


@router.post("/mail/test")
def mail_test(body: MailTestIn, _user: User = Depends(reviewer)):
    """Send a short Outlook/Graph connectivity check to one address."""
    from app.services.emailer import probe_mail

    return probe_mail(get_settings(), body.to.strip())


@router.get("/methodology")
def methodology(_user: User = Depends(current_user)):
    return factor_schema()


@router.post("/methodology/weights")
def weights(body: TriageIn, _user: User = Depends(current_user)):
    return get_weight_profile(body.model_dump())


@router.post("/methodology/calculate")
def calculate(body: CalculateIn, _user: User = Depends(reviewer)):
    """Legacy calculator. Prefer /methodology/assess for the official pipeline."""
    result = calculate_risk(body.scores, body.triage.model_dump())
    if not result.get("complete"):
        from app.methodology.engine import incomplete_score_paths

        raise HTTPException(
            status_code=422,
            detail={"message": "Every factor needs a score from 1 to 5.", "missing": incomplete_score_paths(body.scores)},
        )
    return result


@router.post("/methodology/assess")
def assess_official(body: OfficialCalculateIn, _user: User = Depends(reviewer)):
    """Official deterministic AIRA calculation. LLM output is never the score."""
    try:
        result = calculate_assessment(
            {
                "screening": body.screening.model_dump(),
                "scores": body.scores,
                "provenance": body.provenance,
                "humanReview": body.humanReview.model_dump(),
                "context": body.context,
                "mandatoryRequirements": body.mandatoryRequirements,
            },
            enforce_human_approval=body.enforceHumanApproval,
        )
    except ProvenanceError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": exc.message, "rejected": exc.rejected},
        ) from exc
    if not result.get("complete"):
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Assessment inputs are incomplete or invalid.",
                "errors": result.get("errors") or [],
            },
        )
    return result
