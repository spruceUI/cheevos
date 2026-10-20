from cheevos.core.sync.progress import Phase, ProgressTracker


def test_notifications_can_read_each_published_status_without_holding_the_lock():
    statuses = []

    def changed():
        assert tracker._lock.acquire(blocking=False)
        tracker._lock.release()
        statuses.append(tracker.snapshot())

    tracker = ProgressTracker(on_change=changed)
    tracker.phase(Phase.DETAILS, total=2)
    tracker.working_on("Game")
    tracker.advance(detail=True)
    tracker.finish(Phase.DONE, at=123)
    tracker.reset()
    assert [status.phase for status in statuses] == [Phase.DETAILS] * 3 + [Phase.DONE, Phase.IDLE]
    assert statuses[1].current == "Game"
    assert (statuses[2].done, statuses[2].details_fetched) == (1, 1)
    assert statuses[3].finished_at == 123
