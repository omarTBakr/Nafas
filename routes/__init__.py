"""FastAPI routers, one per resource.

A route validates its input, starts or queries a workflow, and maps errors
onto responses. It holds no business logic: anything worth a unit test belongs
in `utils`.

Each module exposes `router = APIRouter(prefix=..., tags=[...])`, and `main.py`
includes it. Dependencies that must apply to everything — authentication, for
instance — are attached where the router is included, not decorated onto each
endpoint, so an endpoint added later is covered by having been added at all.
"""
