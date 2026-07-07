import pandas as pd
import numpy as np
from pathlib import Path

data_dir = Path(r"C:\Users\deepi\.gemini\antigravity-ide\scratch\transitpulse\data")
output_dir = data_dir / "output"

print("--- Inspecting route_scores.parquet ---")
if (output_dir / "route_scores.parquet").exists():
    df_scores = pd.read_parquet(output_dir / "route_scores.parquet")
    print(df_scores.head(10))
    print("Mean headway stats:\n", df_scores["mean_headway"].describe())
    print("Mean dwell stats:\n", df_scores["mean_dwell_sec"].describe())
else:
    print("route_scores.parquet does not exist.")

print("\n--- Inspecting daily_segment_metrics.parquet ---")
if (output_dir / "daily_segment_metrics.parquet").exists():
    df_seg = pd.read_parquet(output_dir / "daily_segment_metrics.parquet")
    print(df_seg.head(10))
else:
    print("daily_segment_metrics.parquet does not exist.")
