from nafas_core.db import session_scope
from nafas_core.enums.dialect import SpokenDialect, VoiceGender
from nafas_identity.logic.accounts import register_patient_account
from nafas_identity.logic.profile import get_profile, update_profile


async def _sign_up(email, dialect=None):
    async with session_scope() as session:
        return await register_patient_account(
            session, email=email, password="a long patient password", full_name="منى", dialect=dialect
        )


async def test_a_dialect_chosen_at_sign_up_is_kept(database):
    mona = await _sign_up("m@example.com", dialect=SpokenDialect.IRAQI)

    async with session_scope(patient_id=mona.patient_id) as session:
        profile = await get_profile(session, mona.patient_id)

    assert profile.dialect is SpokenDialect.IRAQI
    assert profile.voice is None


async def test_a_patient_changes_only_what_they_send(database):
    mona = await _sign_up("m@example.com")

    async with session_scope(patient_id=mona.patient_id) as session:
        await update_profile(session, mona.patient_id, dialect=SpokenDialect.EGYPTIAN, voice=VoiceGender.FEMALE)
    async with session_scope(patient_id=mona.patient_id) as session:
        profile = await update_profile(session, mona.patient_id, voice=None)

    assert profile.dialect is SpokenDialect.EGYPTIAN
    assert profile.voice is None
    assert profile.full_name == "منى"


async def test_a_patient_cannot_change_someone_elses_profile(database):
    mona = await _sign_up("m@example.com")
    karim = await _sign_up("k@example.com")

    async with session_scope(patient_id=karim.patient_id) as session:
        assert await update_profile(session, mona.patient_id, dialect=SpokenDialect.SAUDI) is None

    async with session_scope(patient_id=mona.patient_id) as session:
        assert (await get_profile(session, mona.patient_id)).dialect is None


def test_each_dialect_names_its_lahgtna_language():
    assert SpokenDialect.EGYPTIAN.lahgtna_language == "egyptian lahgtna"
    assert SpokenDialect.YEMENI.lahgtna_language == "yemeni lahgtna"
    assert len(SpokenDialect) == 13
