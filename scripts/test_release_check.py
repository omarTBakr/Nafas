from scripts.release_check import verdict


def test_only_the_expected_commit_in_the_expected_environment_passes():
    good = {"status": "ok", "version": "abc1234", "environment": "staging"}

    assert verdict(good, "abc1234", "staging") is None
    assert verdict(None, "abc1234", "staging") == "did not answer /health"
    assert "not 'abc1234'" in verdict(good | {"version": "old9999"}, "abc1234", "staging")
    assert "not 'prod'" in verdict(good, "abc1234", "prod")
