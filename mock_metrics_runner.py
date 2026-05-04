#!/usr/bin/env python3
import os
import json
import csv
import random
import statistics
from dca_engine import DCAEngine

OUT_DIR = "mock_output"
random.seed(42)


def make_event(time_us, event_type, seq, pps_status=0, ref=None, note=""):
    return {
        "time_us": time_us,
        "event_type": event_type,
        "seq": seq,
        "board_time_us": time_us,
        "reference_time_us": ref,
        "pps_status": pps_status,
        "note": note,
    }


def gen_base(duration_s=20, offset_us=200, drift_ppm=0, jitter_us=20):
    events = []
    seq = 0
    for t_ms in range(0, duration_s * 1000, 10):  # IMU 100Hz
        t_us = t_ms * 1000
        is_pps = t_ms % 1000 == 0

        if is_pps:
            drift = drift_ppm * t_us / 1_000_000
            noise = random.gauss(0, jitter_us)
            ref = int(t_us + offset_us + drift + noise)
            events.append(make_event(t_us, "PPS_EDGE", seq, 1, ref))
        else:
            events.append(make_event(t_us, "IMU_SAMPLE", seq, 0, None))

        seq += 1
    return events


def scenario_normal():
    return gen_base(duration_s=20, offset_us=200, drift_ppm=0, jitter_us=20)


def scenario_pps_lost_holdover():
    events = gen_base(duration_s=20)
    for e in events:
        if 8_000_000 <= e["time_us"] <= 13_000_000 and e["event_type"] == "PPS_EDGE":
            e["pps_status"] = 0
            e["reference_time_us"] = None
            e["event_type"] = "PPS_LOST"
            e["note"] = "pps lost"
    return events


def scenario_pps_recovery():
    events = gen_base(duration_s=25)
    for e in events:
        if 8_000_000 <= e["time_us"] <= 13_000_000 and e["event_type"] == "PPS_EDGE":
            e["pps_status"] = 0
            e["reference_time_us"] = None
            e["event_type"] = "PPS_LOST"
            e["note"] = "pps lost before recovery"
        elif 14_000_000 <= e["time_us"] <= 18_000_000 and e["event_type"] == "PPS_EDGE":
            e["event_type"] = "PPS_RECOVERY"
            e["note"] = "pps recovery"
    return events


def scenario_seq_gap():
    events = gen_base(duration_s=20)
    # 删除一段 IMU seq，模拟 seq gap
    events = [e for e in events if not (9_000_000 <= e["time_us"] <= 9_300_000)]
    return events


def scenario_jitter_spike():
    events = gen_base(duration_s=20)
    for e in events:
        if e["event_type"] == "PPS_EDGE" and e["time_us"] in [7_000_000, 12_000_000, 17_000_000]:
            e["reference_time_us"] += 800
            e["event_type"] = "JITTER_SPIKE"
            e["note"] = "injected +800us spike"
    return events


def scenario_drift_slow():
    return gen_base(duration_s=40, offset_us=200, drift_ppm=20, jitter_us=15)


SCENARIOS = {
    "normal": scenario_normal,
    "pps_lost_holdover": scenario_pps_lost_holdover,
    "pps_recovery": scenario_pps_recovery,
    "seq_gap": scenario_seq_gap,
    "jitter_spike": scenario_jitter_spike,
    "drift_slow": scenario_drift_slow,
}


def run_engine(events):
    engine = DCAEngine()
    outputs = []
    last_seq = None
    seq_gap_count = 0
    first_holdover_time = None
    first_recovery_time = None

    for e in events:
        # 当前 DCAEngine 主要吃 PPS；非 PPS 只在 PPS_LOST 时用于触发 holdover
        should_update = e["pps_status"] == 1 or e["event_type"] == "PPS_LOST"

        if should_update:
            out = engine.update(
                board_time_us=int(e["board_time_us"]),
                reference_time_us=e["reference_time_us"],
                is_pps=bool(e["pps_status"]),
            )

            if out["state"] == "HOLDOVER" and first_holdover_time is None:
                first_holdover_time = e["time_us"]

            if out["state"] == "RECOVERY" and first_recovery_time is None:
                first_recovery_time = e["time_us"]

            outputs.append({**e, **out})

        if last_seq is not None and e["seq"] != last_seq + 1:
            seq_gap_count += 1
        last_seq = e["seq"]

    return outputs, seq_gap_count, first_holdover_time, first_recovery_time


def calc_metrics(name, events, outputs, seq_gap_count, first_holdover_time, first_recovery_time):
    offsets = [o["offset_us"] for o in outputs]
    drifts = [o["drift_ppm"] for o in outputs]
    confidences = [o["confidence"] for o in outputs]
    residuals = [abs(o["residual"]) for o in outputs]
    states = [o["state"] for o in outputs]

    holdover_samples = [o for o in outputs if o["state"] == "HOLDOVER"]

    metrics = {
        "scenario": name,
        "event_count": len(events),
        "engine_update_count": len(outputs),

        "dca_state_final": states[-1] if states else "NO_OUTPUT",
        "state_sequence": list(dict.fromkeys(states)),

        "confidence_min": min(confidences) if confidences else None,
        "confidence_max": max(confidences) if confidences else None,
        "confidence_final": confidences[-1] if confidences else None,

        "offset_us_avg": statistics.mean(offsets) if offsets else None,
        "offset_us_final": offsets[-1] if offsets else None,
        "offset_us_std": statistics.stdev(offsets) if len(offsets) > 1 else 0,

        "drift_ppm_final": drifts[-1] if drifts else None,
        "drift_ppm_max_abs": max(abs(x) for x in drifts) if drifts else None,

        "jitter_us_max_residual": max(residuals) if residuals else None,
        "jitter_us_avg_residual": statistics.mean(residuals) if residuals else None,

        "holdover_duration_ms": (
            (holdover_samples[-1]["time_us"] - holdover_samples[0]["time_us"]) / 1000
            if len(holdover_samples) >= 2 else 0
        ),

        "mode_transition_latency_us": {
            "first_holdover_time_us": first_holdover_time,
            "first_recovery_time_us": first_recovery_time,
        },

        "seq_gap_count": seq_gap_count,
        "pps_lost_event_count": sum(1 for e in events if e["event_type"] == "PPS_LOST"),
        "jitter_spike_event_count": sum(1 for e in events if e["event_type"] == "JITTER_SPIKE"),
    }

    return metrics


def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    all_metrics = {}

    for name, fn in SCENARIOS.items():
        scenario_dir = os.path.join(OUT_DIR, name)
        os.makedirs(scenario_dir, exist_ok=True)

        events = fn()
        outputs, seq_gap_count, first_holdover_time, first_recovery_time = run_engine(events)

        metrics = calc_metrics(
            name,
            events,
            outputs,
            seq_gap_count,
            first_holdover_time,
            first_recovery_time,
        )

        write_csv(os.path.join(scenario_dir, "events.csv"), events)
        write_csv(os.path.join(scenario_dir, "engine_output.csv"), outputs)

        with open(os.path.join(scenario_dir, "metrics.json"), "w") as f:
            json.dump(metrics, f, indent=2)

        all_metrics[name] = metrics
        print(f"generated {scenario_dir}/metrics.json")

    with open(os.path.join(OUT_DIR, "all_metrics.json"), "w") as f:
        json.dump(all_metrics, f, indent=2)

    print("generated mock_output/all_metrics.json")


if __name__ == "__main__":
    main()
