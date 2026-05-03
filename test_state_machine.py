from state_machine import DCAStateMachine, SyncState


def test_holdover_transition():
    sm = DCAStateMachine()

    # simulate normal PPS
    for i in range(5):
        sm.update(i * 1_000_000, True, False, 10)

    # simulate loss
    state = sm.update(7_000_000, False, False, 0)

    assert state == SyncState.HOLDOVER


def test_recovery_transition():
    sm = DCAStateMachine()

    # force HOLDOVER
    sm.state = SyncState.HOLDOVER

    # 3 valid PPS
    for i in range(3):
        state = sm.update(i * 1_000_000, True, False, 10)

    assert state == SyncState.RECOVERY


def test_normal_transition():
    sm = DCAStateMachine()
    sm.state = SyncState.RECOVERY

    for i in range(3):
        state = sm.update(i * 1_000_000, True, False, 10)

    assert state == SyncState.NORMAL


if __name__ == "__main__":
    test_holdover_transition()
    test_recovery_transition()
    test_normal_transition()
    print("All tests passed.")
