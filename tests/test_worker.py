import logging

import worker
from activities import ACTIVITIES
from workflows import WORKFLOWS


def test_the_registries_are_lists():
    """`create_worker` is handed these directly, so their type is part of the contract."""
    assert isinstance(WORKFLOWS, list)
    assert isinstance(ACTIVITIES, list)


async def test_an_empty_worker_says_so_instead_of_polling(caplog):
    """
    A worker with nothing registered polls forever and does nothing, which
    looks exactly like a worker that is merely idle. Say it out loud.
    """
    with caplog.at_level(logging.ERROR):
        await worker.run()

    assert "nothing to register" in caplog.text
