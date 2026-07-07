import pandas as pd
from pathlib import Path
import numpy as np

pings_dir = Path(r"C:\Users\deepi\.gemini\antigravity-ide\scratch\transitpulse\data\pings")
first_date_dir = next(pings_dir.glob("date=*"))
df = pd.read_parquet(first_date_dir / "data.parquet")

# Run headway computation on a single route and stop
route_id = "DTC-001"
df_route = df[df["route_id"] == route_id].copy()

# Sort
df_route = df_route.sort_values(by=["stop_id", "timestamp"]).reset_index(drop=True)
df_route["timestamp_sec"] = df_route["timestamp"].astype("int64") // 10**9
df_route["prev_timestamp_sec"] = df_route.groupby("stop_id")["timestamp_sec"].shift(1)
df_route["headway_sec"] = df_route["timestamp_sec"] - df_route["prev_timestamp_sec"]

print("--- Headway values for DTC-001 ---")
print(df_route[["timestamp", "stop_id", "vehicle_id", "headway_sec"]].head(25))

print("\n--- Value counts of headway_sec ---")
print(df_route["headway_sec"].value_counts().head(10))
