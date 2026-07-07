"""TransitPulse Core GPU/CPU Analytics Pipeline.
Calculates headway, bunching, gaps, dwell metrics, reliability scores, and trends.
Uses standard pandas operations that automatically run on GPU when enabled via cudf.pandas.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Check if cudf.pandas is active (either via CLI wrapper or if imported manually)
is_gpu_accelerated = False
if "cudf.pandas" in sys.modules or os.environ.get("CUDF_PANDAS_ACTIVE") == "1":
    is_gpu_accelerated = True

import pandas as pd
import numpy as np

from config import CFG


def run_pipeline(input_dir: Path, output_dir: Path) -> dict[str, float]:
    """Runs the analytics pipeline and returns stage durations in seconds."""
    timings = {}
    
    # ── Stage 1: Load Data ─────────────────────────────────────────────
    t0 = time.perf_counter()
    print(f"Loading data from {input_dir}...")
    
    # Load all parquet partitions
    df = pd.read_parquet(input_dir)
    
    if "date" not in df.columns:
        df["date"] = df["timestamp"].dt.date.astype(str)
    else:
        df["date"] = df["date"].astype(str)
        
    timings["load"] = time.perf_counter() - t0
    print(f"Loaded {len(df):,} pings. Time: {timings['load']:.3f}s")
    
    # ── Stage 2: Headway Computation ────────────────────────────────────
    t0 = time.perf_counter()
    print("Computing route-segment headways...")
    
    # Ensure correct sorting for sequential calculations
    df = df.sort_values(by=["route_id", "stop_id", "timestamp"]).reset_index(drop=True)
    
    # Safe convert timestamp to epoch seconds for arithmetic (resolves microseconds units bug!)
    df["timestamp_sec"] = df["timestamp"].astype("datetime64[s]").astype("int64")
    
    # Calculate difference between consecutive pings at (route_id, stop_id)
    df["prev_timestamp_sec"] = df.groupby(["route_id", "stop_id"])["timestamp_sec"].shift(1)
    df["prev_vehicle_id"] = df.groupby(["route_id", "stop_id"])["vehicle_id"].shift(1)
    
    # Headway is only valid if it's a consecutive bus (different vehicle)
    df["headway_sec"] = df["timestamp_sec"] - df["prev_timestamp_sec"]
    df.loc[df["vehicle_id"] == df["prev_vehicle_id"], "headway_sec"] = np.nan
    
    # Audit & Fix: Convert raw seconds to MINUTES for headway math
    df["headway_min"] = df["headway_sec"] / 60.0
    df["scheduled_headway_min"] = df["scheduled_headway_sec"] / 60.0
    
    timings["groupby_headway"] = time.perf_counter() - t0
    print(f"Headway computation finished. Time: {timings['groupby_headway']:.3f}s")
    
    # ── Stage 3: Anomaly Scan ──────────────────────────────────────────
    t0 = time.perf_counter()
    print("Scanning for headway anomalies (bunching & gaps)...")
    
    # Flag bunching and gap events based on scheduled headway
    df["is_bunching"] = df["headway_min"] < (CFG.bunching_threshold * df["scheduled_headway_min"])
    df["is_gap"] = df["headway_min"] > (CFG.gap_threshold * df["scheduled_headway_min"])
    
    valid_headways = df.dropna(subset=["headway_min"])
    
    timings["anomaly_scan"] = time.perf_counter() - t0
    print(f"Anomaly scan finished. Time: {timings['anomaly_scan']:.3f}s")
    
    # ── Stage 4: Scoring ───────────────────────────────────────────────
    t0 = time.perf_counter()
    print("Computing reliability scores per route and segment...")
    
    grp = valid_headways.groupby(["route_id", "stop_id", "date"])
    
    segment_metrics = grp.agg(
        total_trips=("headway_min", "count"),
        mean_headway=("headway_min", "mean"),
        std_headway=("headway_min", "std"),
        bunching_count=("is_bunching", "sum"),
        gap_count=("is_gap", "sum"),
        mean_dwell_sec=("dwell_sec", "mean"),
        route_base_boardings=("route_base_boardings", "max")
    ).reset_index()
    
    # Fill standard deviations with 0 if null (single bus/trip)
    segment_metrics["std_headway"] = segment_metrics["std_headway"].fillna(0.0)
    segment_metrics["headway_cov"] = (segment_metrics["std_headway"] / segment_metrics["mean_headway"]).fillna(0.0)
    
    segment_metrics["bunching_rate"] = (segment_metrics["bunching_count"] / segment_metrics["total_trips"]).fillna(0.0)
    segment_metrics["gap_rate"] = (segment_metrics["gap_count"] / segment_metrics["total_trips"]).fillna(0.0)
    
    # Composite Reliability Score:
    cov_penalty = np.minimum(segment_metrics["headway_cov"], 1.0)
    bunching_penalty = np.minimum(segment_metrics["bunching_rate"], 0.5) / 0.5
    gap_penalty = np.minimum(segment_metrics["gap_rate"], 0.5) / 0.5
    
    composite_penalty = (
        cov_penalty * CFG.weight_headway_cov +
        bunching_penalty * CFG.weight_bunching +
        gap_penalty * CFG.weight_gap
    )
    
    segment_metrics["reliability_score"] = (100.0 * (1.0 - composite_penalty)).clip(0.0, 100.0)
    
    # Compute overall route metrics (roll-up of segments)
    route_grp = segment_metrics.groupby(["route_id", "date"])
    route_metrics = route_grp.agg(
        reliability_score=("reliability_score", "mean"),
        mean_headway=("mean_headway", "mean"),
        bunching_count=("bunching_count", "sum"),
        gap_count=("gap_count", "sum"),
        mean_dwell_sec=("mean_dwell_sec", "mean"),
        route_base_boardings=("route_base_boardings", "max")
    ).reset_index()
    
    # Trend computation: Week-over-Week trend
    route_metrics = route_metrics.sort_values(by=["route_id", "date"]).reset_index(drop=True)
    
    # Compute a 7-day lagged score to compare week-over-week
    route_metrics["prev_week_score"] = route_metrics.groupby("route_id")["reliability_score"].shift(7)
    route_metrics["prev_week_score"] = route_metrics["prev_week_score"].fillna(route_metrics["reliability_score"])
    route_metrics["wow_trend"] = route_metrics["reliability_score"] - route_metrics["prev_week_score"]
    route_metrics["wow_trend"] = route_metrics["wow_trend"].fillna(0.0)
    
    # Extract anomaly events list for DB injection
    anomaly_events = valid_headways[valid_headways["is_bunching"] | valid_headways["is_gap"]][
        ["timestamp", "vehicle_id", "route_id", "stop_id", "stop_sequence", "headway_min", "scheduled_headway_min", "is_bunching", "is_gap"]
    ].copy()
    
    # Create descriptive labels
    anomaly_events["anomaly_type"] = np.where(anomaly_events["is_bunching"], "bunching", "gap")
    anomaly_events["timestamp_str"] = anomaly_events["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    
    timings["scoring"] = time.perf_counter() - t0
    print(f"Scoring and trend calculations complete. Time: {timings['scoring']:.3f}s")
    
    # ── Stage 5: Save Output Parquets ──────────────────────────────────
    t0 = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save aggregates
    route_metrics.to_parquet(output_dir / "route_scores.parquet", index=False)
    segment_metrics.to_parquet(output_dir / "daily_segment_metrics.parquet", index=False)
    anomaly_events.to_parquet(output_dir / "anomaly_events.parquet", index=False)
    
    timings["save"] = time.perf_counter() - t0
    print(f"Aggregates saved to {output_dir}. Time: {timings['save']:.3f}s")
    
    # Trigger sanity check validation
    validate_outputs(route_metrics, segment_metrics, anomaly_events)
    
    return timings


def validate_outputs(route_metrics: pd.DataFrame, segment_metrics: pd.DataFrame, anomaly_events: pd.DataFrame) -> None:
    """Runs data sanity validation checks and fails loudly on violation."""
    print("Running pipeline outputs validation tests...")
    
    # 1. Median headway between 4 and 20 minutes
    median_headway = route_metrics["mean_headway"].median()
    print(f"Validation: Median headway is {median_headway:.2f} min")
    assert 4.0 <= median_headway <= 20.0, f"Median headway {median_headway} min outside [4, 20] range."
    
    # 2. Bunching rate per route between 0 and 0.4
    # Calculate bunching rate: bunching trips / total trips
    # We can fetch bunching rate from segment_metrics
    bunching_rate_per_route = segment_metrics.groupby("route_id")["bunching_rate"].mean()
    max_bunching_rate = bunching_rate_per_route.max()
    print(f"Validation: Max route average bunching rate is {max_bunching_rate:.4f}")
    assert 0.0 <= max_bunching_rate <= 0.4, f"Max bunching rate {max_bunching_rate} outside [0, 0.4] range."
    
    # 3. Dwell std > 0
    dwell_std = segment_metrics["mean_dwell_sec"].std()
    print(f"Validation: Dwell standard deviation is {dwell_std:.2f}s")
    assert dwell_std > 0.0, "Dwell times are uniform (std == 0)."
    
    # 4. At least 25 distinct daily dates
    distinct_dates = route_metrics["date"].nunique()
    print(f"Validation: Number of distinct dates: {distinct_dates}")
    assert distinct_dates >= 25, f"Only {distinct_dates} distinct dates found; expected >= 25."
    
    # 5. WoW trend non-zero for >80% of routes
    # Filter dates to exclude first week (where WoW trend would be 0 because prev_week was filled with current)
    # The first 7 days have zero trend. For 30 days, we have 23 days of real WoW trend.
    # Check if for the latest date, trend is nonzero for >80% of routes.
    latest_date = route_metrics["date"].max()
    latest_metrics = route_metrics[route_metrics["date"] == latest_date]
    non_zero_trend_count = (latest_metrics["wow_trend"].abs() > 0.001).sum()
    pct_non_zero = non_zero_trend_count / len(latest_metrics)
    print(f"Validation: WoW trend non-zero for {pct_non_zero*100:.1f}% of routes on {latest_date}")
    # Note: On a small dataset, sometimes a few routes might remain exact. But with noise, they will differ.
    assert pct_non_zero > 0.8, f"WoW trend only non-zero for {pct_non_zero*100:.1f}% of routes; expected > 80%."
    
    print("All validation checks passed successfully!")


def main() -> None:
    parser = argparse.ArgumentParser(description="TransitPulse Analytics Pipeline")
    parser.add_argument("--input", type=str, default=str(CFG.pings_dir), help="Input directory containing pings")
    parser.add_argument("--output", type=str, default=str(CFG.output_dir), help="Output directory for metrics")
    parser.add_argument("--timing-file", type=str, default=None, help="Save timing metrics to this JSON file")
    args = parser.parse_args()
    
    print(f"=== TransitPulse Analytics Pipeline ===")
    print(f"GPU Acceleration Enabled: {is_gpu_accelerated}")
    
    input_path = Path(args.input)
    output_path = Path(args.output)
    
    if not input_path.exists():
        print(f"Error: Input path {input_path} does not exist. Run generate_pings.py first.")
        sys.exit(1)
        
    timings = run_pipeline(input_path, output_path)
    total_time = sum(timings.values())
    print(f"Pipeline executed successfully in {total_time:.3f} seconds.")
    
    if args.timing_file:
        import json
        with open(args.timing_file, "w") as f:
            json.dump(timings, f)
        print(f"Saved timings to {args.timing_file}")


if __name__ == "__main__":
    main()
