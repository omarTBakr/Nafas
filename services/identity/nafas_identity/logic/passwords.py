from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from nafas_identity.exceptions import WeakPasswordError

# argon2id with the library's current defaults; `needs_rehash` upgrades old
# hashes at the next successful login when those defaults change
_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 12


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(f"passwords need at least {MIN_PASSWORD_LENGTH} characters")

    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


# verified against when the email is unknown, so a wrong email takes as long
# as a wrong password and response time does not reveal who has an account
DUMMY_HASH = _hasher.hash("not-a-real-password-for-timing-only")
