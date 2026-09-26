"""The gateway remembers a confirmed account briefly, and forgets it when its time is up."""

import uuid

from nafas_core.clients.identity import Account
from nafas_core.enums.identity import UserRole
from nafas_gateway.sessions import AccountCache


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def account() -> Account:
    return Account(user_id=uuid.uuid4(), email="a@example.com", role=UserRole.PATIENT, doctor_id=None, patient_id=uuid.uuid4())


def test_an_account_is_remembered_until_its_time_is_up():
    clock, sara = Clock(), account()
    cache = AccountCache(clock)
    cache.put(sara.user_id, sara, 30)

    clock.now += 29
    assert cache.get(sara.user_id) == sara
    clock.now += 2
    assert cache.get(sara.user_id) is None


def test_a_full_cache_drops_what_expired_and_never_grows_past_its_size():
    clock = Clock()
    cache = AccountCache(clock, max_entries=3)
    old = [account() for _ in range(3)]
    for a in old:
        cache.put(a.user_id, a, 10)
    clock.now += 11
    new = account()
    cache.put(new.user_id, new, 10)

    assert cache.get(new.user_id) == new
    assert all(cache.get(a.user_id) is None for a in old)
    assert len(cache._entries) == 1
