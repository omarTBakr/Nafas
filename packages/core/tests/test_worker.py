import logging

from nafas_core.temporal import TaskQueue, run_worker


async def test_an_empty_worker_says_so_instead_of_polling(caplog):
    """
    A worker with nothing registered polls forever and does nothing, which
    looks exactly like a worker that is merely idle. Say it out loud.
    """
    with caplog.at_level(logging.ERROR):
        await run_worker(TaskQueue.SCHEDULING, [], [])

    assert "nothing to register" in caplog.text
    assert "scheduling" in caplog.text


def test_every_queue_name_is_unique():
    assert len({q.value for q in TaskQueue}) == len(TaskQueue)
