"""Dataclasses that cross a Temporal boundary, one file per activity.

Each activity gets a `FooInput` and a `FooOutput` here. They are plain
dataclasses because Temporal's converter encodes them to JSON and decodes them
on the other side — which is also the trap: a field the *decoding* class does
not know about is dropped in silence, so every worker polling a queue must be
running the same version of these files.
"""
