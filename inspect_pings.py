import pandas as pd
from pathlib import Path

data_dir = Path(r"C:\Users\deepi\.gemini\antigravity-ide\scratch\transitpulse\data\pings")
first_date_dir = next(data_dir.glob("date=*"))
df = pd.read_parquet(first_date_dir / "data.parquet")
print("--- Raw Pings columns ---")
print(df.info())
print("\n--- First 20 pings ---")
print(df[["timestamp", "route_id", "vehicle_id", "stop_id", "stop_sequence", "dwell_sec"]].head(20))
