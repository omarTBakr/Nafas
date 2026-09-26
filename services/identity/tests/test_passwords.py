import pytest

from nafas_identity.exceptions import WeakPasswordError
from nafas_identity.logic.passwords import hash_password, verify_password


def test_a_hash_verifies_only_its_own_password():
    hashed = hash_password("correct horse battery")

    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "correct horse battery")
    assert not verify_password(hashed, "correct horse battery!")


def test_a_garbage_hash_is_a_failed_login_not_a_crash():
    assert not verify_password("not a hash", "anything")


def test_short_passwords_are_refused():
    with pytest.raises(WeakPasswordError):
        hash_password("short")
