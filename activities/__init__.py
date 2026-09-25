"""Temporal activities, one per file.

Each activity is a thin wrapper: it takes a dataclass from `schemas`, does one
side-effecting step, and returns a dataclass. The real work stays in `utils` so
it can be tested without a Temporal server — an activity module should be short
enough to read in one screen.

Add one by writing `activities/do_thing.py` with an `@activity.defn` function,
importing it here, and adding it to the list below. The worker registers
whatever is in that list, so forgetting it is the one mistake that fails
silently at runtime rather than at import.
"""

# every activity the worker registers
ACTIVITIES: list = []
