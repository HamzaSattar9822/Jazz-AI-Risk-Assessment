from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import RedirectResponse
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
    build_user_memory,
    confirm_slots,
    create_session,
    examples,
    extract_description,
    get_owned,
    list_sessions_for,
    reset_slot,
    view_session,
)
from app.services.oidc import (
    OidcError,
    build_authorize_url,
    create_oidc_state,
    exchange_code,
    issue_session_token,
    upsert_oidc_user,
    user_roles,
    verify_oidc_state,
)
from app.services.report_pdf import build_final_approval_pdf
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
    roles = user_roles(user)
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "businessUnit": user.business_unit,
        "role": user.role,
        "roles": roles,
    }


def _set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    secure = settings.entra_redirect_uri.startswith("https://")
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=settings.jwt_expire_minutes * 60,
        path="/",
    )


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
    token = create_token(user.id)
    _set_session_cookie(response, token)
    return {"accessToken": token, "tokenType": "bearer", "user": _user_out(user)}


@router.get("/auth/oidc/config")
def oidc_config():
    settings = get_settings()
    return {
        "enabled": settings.entra_configured,
        "loginPath": "/api/v1/auth/oidc/login",
        "provider": "microsoft-entra-id",
        "roles": sorted(settings.entra_allowed_role_set),
    }


@router.get("/auth/oidc/login")
def oidc_login():
    settings = get_settings()
    try:
        state = create_oidc_state(settings)
        url = build_authorize_url(settings, state)
    except OidcError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return RedirectResponse(url=url, status_code=302)


@router.get("/auth/oidc/callback")
def oidc_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = Query(default=None, alias="error_description"),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    portal = "/"
    if error:
        detail = quote(error_description or error, safe="")
        return RedirectResponse(url=f"{portal}?sso=error&detail={detail}", status_code=302)
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing OIDC code or state.")
    try:
        verify_oidc_state(settings, state)
        profile = exchange_code(settings, code)
        user = upsert_oidc_user(db, profile)
        token = issue_session_token(user)
    except OidcError as exc:
        return RedirectResponse(
            url=f"{portal}?sso=error&detail={quote(exc.message, safe='')}",
            status_code=302,
        )
    response = RedirectResponse(url=f"{portal}?sso=ok", status_code=302)
    _set_session_cookie(response, token)
    # Also expose token in a short-lived cookie readable by the SPA bootstrap.
    response.set_cookie(
        "aira_access_token",
        token,
        httponly=False,
        samesite="lax",
        secure=settings.entra_redirect_uri.startswith("https://"),
        max_age=120,
        path="/",
    )
    return response


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return _user_out(user)


@router.post("/auth/logout")
def logout(response: Response):
    """Clear browser session cookies (password or Entra SSO)."""
    response.delete_cookie(COOKIE_NAME, path="/")
    response.delete_cookie("aira_access_token", path="/")
    return {"ok": True}


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


@router.get("/intake/sessions")
def list_sessions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """List this user's saved intake chats (full transcripts live on each session)."""
    return {"sessions": list_sessions_for(db, user)}


@router.get("/intake/memory")
def intake_memory(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Prior sessions + submissions SYRA can reuse when the user refers to past data."""
    return build_user_memory(db, user)


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


@router.get("/submissions/{reference_id}/report.pdf")
def download_report_pdf(
    reference_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Direct Final Approval Report PDF for ServiceNow / RAIO integrations."""
    try:
        row = get_visible(db, user, reference_id)
    except SubmissionError as exc:
        _raise_submission(exc)
    if row.assessment is None:
        raise HTTPException(
            status_code=422,
            detail="Score the request before downloading the final approval report.",
        )
    pdf_bytes, filename = build_final_approval_pdf(row)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


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
        save_decision(
            db,
            user,
            row,
            body.outcome,
            body.conditions,
            body.notes,
            get_settings(),
            service_now_ticket=body.serviceNowTicket,
        )
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
