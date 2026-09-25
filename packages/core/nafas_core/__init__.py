"""nafas_core: what every Nafas service shares.

Settings, logging and tracing; the database layer; the Temporal client, worker
and queue names; the provider interfaces; and the shared enums and exception
hierarchy. It holds no domain logic — that lives in the service that owns it.
"""
