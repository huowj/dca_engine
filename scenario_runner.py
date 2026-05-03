import random
from state_machine import DCAStateMachine, SyncState


def run_scenario(name, events):
    sm = DCAStateMachine()

    print(f"\n=== Scenario: {name} ===")

    for e in events:
        state = sm.update(
            now_us=e["time"],
            is_pps=e["pps"],
            is_outlier=e["outlier"],
            residual_us=e["residual"]
        )
        print(e["time"], state.name)


def scenario_normal():
    events = []
    t = 0
    for _ in range(10):
        t += 1_000_000
        events.append({
            "time": t,
            "pps": True,
            "outlier": False,
            "residual": random.uniform(-50, 50)
        })
    return events


def scenario_holdover():
    events = []
    t = 0
    # normal first
    for _ in range(5):
        t += 1_000_000
        events.append({"time": t, "pps": True, "outlier": False, "residual": 10})

    # loss
    for _ in range(5):
        t += 1_000_000
        events.append({"time": t, "pps": False, "outlier": False, "residual": 0})

    return events


def scenario_jitter():
    events = []
    t = 0
    for _ in range(10):
        t += 1_000_000
        events.append({
            "time": t,
            "pps": True,
            "outlier": random.choice([False, True]),
            "residual": random.uniform(-300, 300)
        })
    return events


def scenario_drift():
    events = []
    t = 0
    drift = 0
    for _ in range(10):
        t += 1_000_000
        drift += 20  # simulate drift
        events.append({
            "time": t,
            "pps": True,
            "outlier": False,
            "residual": drift
        })
    return events


if __name__ == "__main__":
    run_scenario("NORMAL", scenario_normal())
    run_scenario("HOLDOVER", scenario_holdover())
    run_scenario("JITTER", scenario_jitter())
    run_scenario("DRIFT", scenario_drift())
