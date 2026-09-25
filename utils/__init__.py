"""The actual work, with no Temporal or FastAPI imports in sight.

This is where logic lives, so it can be tested by calling a function rather
than by standing up a server. `activities` and `routes` are the thin layers
that adapt it to a task queue and to HTTP.
"""
