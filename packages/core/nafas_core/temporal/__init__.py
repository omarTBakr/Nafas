"""Temporal plumbing every service shares: the client, the worker, and the queue names.

Each service's worker polls its own TaskQueue. A workflow in one service runs
an activity in another by naming that service's queue, which is how services
call each other without sharing code beyond `schemas`.
"""

from nafas_core.temporal.client import get_temporal_client
from nafas_core.temporal.queues import TaskQueue
from nafas_core.temporal.serve import serve_with_worker
from nafas_core.temporal.worker import create_worker, run_worker

__all__ = ["TaskQueue", "create_worker", "get_temporal_client", "run_worker", "serve_with_worker"]
