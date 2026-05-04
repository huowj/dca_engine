from dca_engine import DCAEngine
from golden_checker import GoldenChecker
import pandas as pd

df = pd.read_csv("fake_scenario.csv")

engine = DCAEngine()
checker = GoldenChecker()

print("time_us, raw_offset, corrected_time, state, confidence, result")

for _, row in df.iterrows():
    output = engine.update(
        board_time_us=int(row.sensor_ideal),
        reference_time_us=int(row.sensor_with_error),
        is_pps=bool(row.pps_status)
    )

    raw_offset = row.sensor_with_error - row.sensor_ideal
    power_ok = row.voltage_5v > 4.9

    result = checker.check(
        offset_us=raw_offset,
        power_ok=power_ok,
        pps_status=int(row.pps_status)
    )

    print(
        f"{int(row.time_us)}, "
        f"offset={raw_offset:.1f}, "
        f"corrected={output['corrected_time_us']}, "
        f"state={output['state']}, "
        f"confidence={output['confidence']:.3f}, "
        f"result={result}"
    )
