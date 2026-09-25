"""Ports to the outside world, behind a Protocol.

One subpackage per kind of dependency (an LLM, a storage backend, a mailer),
each defining the Protocol its callers use and one module per implementation.
The point is that a caller names the Protocol, so a second provider is a new
file and a factory entry rather than an edit to everything that calls it.
"""
