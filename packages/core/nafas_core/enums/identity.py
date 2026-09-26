from enum import StrEnum


class UserRole(StrEnum):
    """Who a web account belongs to; decides which portal and routes it may use."""

    DOCTOR = "doctor"
    PATIENT = "patient"
    ADMIN = "admin"
    STAFF = "staff"


class Language(StrEnum):
    ARABIC = "ar"
    ENGLISH = "en"
