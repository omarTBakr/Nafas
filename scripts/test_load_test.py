"""The load test's verdict: a route over its latency objective, or errors over budget, fails the run."""

from scripts.load_test import Results, report


def test_a_run_within_its_objectives_passes():
    results = Results()
    for i in range(100):
        results.record("GET /api/doctors", 0.05 + i / 1000, True)
        results.record("POST /api/chat/{id}/messages", 3.0, True)

    summary, passed = report(results, seconds=10)

    assert passed and summary["requests_per_second"] == 20.0
    assert summary["routes"]["GET /api/doctors"]["p95_ms"] == 144
    assert summary["routes"]["POST /api/chat/{id}/messages"]["objective_p95_ms"] == 12000


def test_a_slow_route_or_too_many_errors_fails_it():
    slow = Results()
    for _ in range(100):
        slow.record("GET /api/doctors", 1.5, True)
    assert not report(slow, 10)[1]

    failing = Results()
    for i in range(100):
        failing.record("GET /api/doctors", 0.05, i >= 1)
    summary, passed = report(failing, 10)
    assert not passed and summary["error_rate"] == 0.01
