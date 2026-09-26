from enum import StrEnum


class UserRole(StrEnum):
    """Who a dashboard account belongs to; carried in the session token."""

    DOCTOR = "doctor"
    ADMIN = "admin"
    STAFF = "staff"


class Language(StrEnum):
    ARABIC = "ar"
    ENGLISH = "en"
