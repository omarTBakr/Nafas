"""Prompts as data, one module per task.

Each module holds a SYSTEM string, a USER_TEMPLATE, and the object that pairs
them. Keeping them out of the code that calls the model means a prompt change
is a reviewable diff in one place, and the same text can be reused by an
evaluation harness.
"""
