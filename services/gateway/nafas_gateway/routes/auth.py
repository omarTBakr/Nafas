from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field

from nafas_core.config import get_setting
from nafas_core.enums.dialect import SpokenDialect, VoiceGender
from nafas_core.enums.identity import Language
from nafas_gateway.clients.identity import Account, get_identity
from nafas_gateway.sessions import COOKIE_NAME, current_account, issue_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Login(BaseModel):
    email: str
    password: str


class SignUp(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12)
    full_name: str = Field(min_length=2, max_length=200)
    preferred_language: Language = Language.ARABIC
    phone: str | None = Field(default=None, max_length=32)
    dialect: SpokenDialect | None = None
    voice: VoiceGender | None = None


class Me(BaseModel):
    user_id: str
    email: str
    role: str
    doctor_id: str | None
    patient_id: str | None


def _me(account: Account) -> Me:
    return Me(
        user_id=str(account.user_id),
        email=account.email,
        role=account.role.value,
        doctor_id=str(account.doctor_id) if account.doctor_id else None,
        patient_id=str(account.patient_id) if account.patient_id else None,
    )


def _start_session(response: Response, account: Account) -> None:
    settings = get_setting()
    response.set_cookie(
        COOKIE_NAME,
        issue_token(account),
        max_age=settings.jwt_ttl_minutes * 60,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/login", response_model=Me)
async def login(credentials: Login, response: Response) -> Me:
    """Sets the session cookie. One answer for every kind of failure, so it says nothing about who has an account."""
    account = await get_identity().verify(credentials.email, credentials.password)
    if account is None:
        raise HTTPException(status_code=401, detail="email or password is wrong")

    _start_session(response, account)
    return _me(account)


@router.post("/register", response_model=Me, status_code=201)
async def register(form: SignUp, response: Response) -> Me:
    """Patient self sign-up, logged in straight away. Doctors are never created here."""
    account = await get_identity().sign_up_patient(form.model_dump(mode="json"))
    _start_session(response, account)
    return _me(account)


@router.post("/logout", status_code=204)
async def logout(response: Response) -> Response:
    response.delete_cookie(COOKIE_NAME, path="/")
    response.status_code = 204
    return response


@router.get("/me", response_model=Me)
async def me(account: Account = Depends(current_account)) -> Me:
    return _me(account)
