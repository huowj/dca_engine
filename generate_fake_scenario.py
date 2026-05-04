import pandas as pd
import numpy as np

np.random.seed(42)

rows = []
for i in range(1000):
    time_us = i * 100_000
    t_s = time_us / 1_000_000

    sensor_ideal = time_us
    error = 200 + np.random.normal(0, 50)

    if 20 <= t_s <= 30:
        error += (t_s - 20) * 100

    voltage_5v = 4.8 if 45 <= t_s <= 46 else 5.0
    pps_status = 0 if 45 <= t_s <= 46 else 1

    rows.append({
        "time_us": time_us,
        "sensor_ideal": sensor_ideal,
        "sensor_with_error": int(sensor_ideal + error),
        "pps_status": pps_status,
        "voltage_5v": voltage_5v,
    })

pd.DataFrame(rows).to_csv("fake_scenario.csv", index=False)
print("generated fake_scenario.csv, rows=1000")
