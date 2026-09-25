import asyncio

from temporalio.client import Client
from temporalio.service import RPCError

from exceptions.workflow import TemporalConnectionError
from utils.config import get_setting
from utils.logger import get_logger

logger = get_logger(__name__)

# Client.connect retries indefinitely when nothing is listening, which would
# hang a request instead of failing it. Give up and report it instead.
CONNECT_TIMEOUT_SECONDS = 5

_client = None


async def get_temporal_client() -> Client:
    """
    Returns a singleton Temporal client built from TEMPORAL_HOST and
    TEMPORAL_NAMESPACE.

    Raises TemporalConnectionError rather than letting the transport error
    escape, so callers can map it onto a response.
    """
    global _client
    if _client is None:
        settings = get_setting()
        logger.info("connecting to temporal at %s (namespace %s)", settings.temporal_host, settings.temporal_namespace)
        try:
            _client = await asyncio.wait_for(
                Client.connect(settings.temporal_host, namespace=settings.temporal_namespace),
                timeout=CONNECT_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            raise TemporalConnectionError(
                f"timed out after {CONNECT_TIMEOUT_SECONDS}s connecting to Temporal at {settings.temporal_host}"
            ) from exc
        except (RPCError, RuntimeError, OSError) as exc:
            raise TemporalConnectionError(f"could not reach Temporal at {settings.temporal_host}: {exc}") from exc

    return _client
