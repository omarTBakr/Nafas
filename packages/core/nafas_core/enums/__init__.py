"""Closed vocabularies, one per file.

Anything with a fixed set of values — a status, a severity, a decision — is an
Enum here rather than a bare string, so a typo is an error at the boundary
instead of a branch that quietly never matches.
"""
