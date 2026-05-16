#!/usr/bin/env python3
import csv
import json
from pathlib import Path
from dca_engine import DCAEngine

INPUT_CSV = "dca_engine_sample_event.csv"
OUT_DIR = Path("interface_output")
OUT_DIR.mkdir(exist_ok=True)

PPS_EVENTS = {"PPS_EDGE", "PPS_RECOVERY"}


def to_int(v, default=0):
    if v is None or v == "":
        return default
    return int(float(v))


def has_seq_gap(v):
    if v is None:
        return False
    return str(v).strip() != ""


def to_bool(v):
    if v is None or v == "":
        return False
    return str(v).strip() in {"1", "true", "True", "YES", "yes"}


def get_reference_time(row):
    """
    Interface alignment sample:
    优先使用 corrected_time_us 作为 reference_time_us。
    如果为空，则退回 sensor_time_us。
    如果仍为空，则用 board_time_us。
    """
    if row.get("corrected_time_us"):
        return to_int(row["corrected_time_us"])
    if row.get("sensor_time_us"):
        return to_int(row["sensor_time_us"])
    return to_int(row["board_time_us"])


def main():
    engine = DCAEngine()

    input_path = Path(INPUT_CSV)
    if not input_path.exists():
        raise FileNotFoundError(f"missing {INPUT_CSV}")

    rows_out = []
    metrics = {
        "input_csv": INPUT_CSV,
        "total_rows": 0,
        "event_type_count": {},
        "pps_edge_count": 0,
        "pps_lost_count": 0,
        "pps_recovery_count": 0,
        "imu_sample_count": 0,
        "gnss_status_count": 0,
        "seq_gap_marked_count": 0,
        "loss_detected_count": 0,
        "engine_update_count": 0,
        "final_state": None,
        "final_offset_us": None,
        "final_drift_ppm": None,
        "final_confidence": None,
        "holdover_seen": False,
        "recovery_seen": False,
    }

    with input_path.open(newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            metrics["total_rows"] += 1

            event_type = row["event_type"]
            board_time_us = to_int(row["board_time_us"])

            metrics["event_type_count"][event_type] = (
                metrics["event_type_count"].get(event_type, 0) + 1
            )

            if event_type == "PPS_EDGE":
                metrics["pps_edge_count"] += 1
            elif event_type == "PPS_LOST":
                metrics["pps_lost_count"] += 1
            elif event_type == "PPS_RECOVERY":
                metrics["pps_recovery_count"] += 1
            elif event_type == "IMU_SAMPLE":
                metrics["imu_sample_count"] += 1
            elif event_type == "GNSS_STATUS":
                metrics["gnss_status_count"] += 1

            if has_seq_gap(row.get("seq_gap")):
                metrics["seq_gap_marked_count"] += 1

            if to_bool(row.get("loss_detected")):
                metrics["loss_detected_count"] += 1

            # 只把 PPS 类事件喂给 DCAEngine
            # IMU/GNSS 只做接口解析和当前 DCA 状态输出
            if event_type in PPS_EVENTS:
                reference_time_us = get_reference_time(row)
                output = engine.update(
                    board_time_us=board_time_us,
                    reference_time_us=reference_time_us,
                    is_pps=True,
                )
                metrics["engine_update_count"] += 1

            elif event_type == "PPS_LOST":
                output = engine.update(
                    board_time_us=board_time_us,
                    reference_time_us=None,
                    is_pps=False,
                )
                metrics["engine_update_count"] += 1

            else:
                # Non-PPS events do not update the DCA observer,
                # but their output timestamp must still obey the global monotonic contract.
                candidate = int(engine.compute_time(board_time_us))
                corrected = max(candidate, engine.last_output_time + 1)
                engine.last_output_time = corrected

                output = {
                    "corrected_time_us": corrected,
                    "state": engine.state.name,
                    "offset_us": engine.offset_us,
                    "drift_ppm": engine.drift_ppm,
                    "confidence": engine.confidence,
                    "residual": 0,
                }

            if output["state"] == "HOLDOVER":
                metrics["holdover_seen"] = True
            if output["state"] == "RECOVERY":
                metrics["recovery_seen"] = True

            rows_out.append({
                "board_time_us": board_time_us,
                "event_type": event_type,
                "sensor_id": row.get("sensor_id", ""),
                "seq_num": row.get("seq_num", ""),
                "seq_gap": row.get("seq_gap", ""),
                "loss_detected": row.get("loss_detected", ""),
                "input_sync_state": row.get("sync_state", ""),
                "dca_state": output["state"],
                "dca_corrected_time_us": int(output["corrected_time_us"]),
                "dca_offset_us": output["offset_us"],
                "dca_drift_ppm": output["drift_ppm"],
                "dca_confidence": output["confidence"],
                "dca_residual": output["residual"],
                "note": row.get("note", ""),
            })

    if rows_out:
        last = rows_out[-1]
        metrics["final_state"] = last["dca_state"]
        metrics["final_offset_us"] = last["dca_offset_us"]
        metrics["final_drift_ppm"] = last["dca_drift_ppm"]
        metrics["final_confidence"] = last["dca_confidence"]

    out_csv = OUT_DIR / "dca_interface_output.csv"
    with out_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        writer.writeheader()
        writer.writerows(rows_out)

    out_json = OUT_DIR / "dca_interface_metrics.json"
    with out_json.open("w") as f:
        json.dump(metrics, f, indent=2)

    print("DCA interface alignment done")
    print(f"output csv: {out_csv}")
    print(f"metrics json: {out_json}")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
