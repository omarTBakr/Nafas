"""Temporal workflows, one per file.

A workflow decides *what* happens and in what order; it never does I/O itself.
Everything that touches the network, the disk or the clock goes through an
activity, because a workflow is replayed from its history and has to produce
the same decisions every time.

Two rules that are easy to break and expensive to debug:

- Import anything non-deterministic inside `workflow.unsafe.imports_passed_through()`,
  so the sandbox does not re-import it and hand you a second copy of a class.
- Guard any change to an existing workflow's *shape* with `workflow.patched()`,
  or a run that is already in flight will fail to replay across the deploy.

Add one by writing `workflows/my_flow.py` with an `@workflow.defn` class,
importing it here, and adding it to the list below.
"""

# every workflow the worker registers
WORKFLOWS: list[type] = []
