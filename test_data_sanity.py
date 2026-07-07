"""Sanity checker for TransitPulse generated metrics.
Asserts scheduled headways, bunching rates, date ranges, and WoW trend spread.
"""

from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd

from config import CFG


def check_sanity() -> None:
    print("=== Running Sanity Verification Tests ===")
    
    scores_path = CFG.output_dir / "route_scores.parquet"
    segment_path = CFG.output_dir / "daily_segment_metrics.parquet"
    anomaly_path = CFG.output_dir / "anomaly_events.parquet"
    
    if not scores_path.exists():
        print(f"Error: {scores_path} does not exist. Run pipeline first.")
        sys.exit(1)
        
    df_scores = pd.read_parquet(scores_path)
    df_seg = pd.read_parquet(segment_path)
    df_anom = pd.read_parquet(anomaly_path)
    
    # 1. Median headway between 4 and 20 minutes
    median_headway = df_scores["mean_headway"].median()
    print(f"1. Median Headway: {median_headway:.2f} min (Expected: 4.0 - 20.0)")
    assert 4.0 <= median_headway <= 20.0, f"FAIL: Median headway is {median_headway:.2f}"
    
    # 2. Bunching rate per route between 0 and 0.4
    bunching_rates = df_seg.groupby("route_id")["bunching_rate"].mean()
    max_bunching = bunching_rates.max()
    print(f"2. Max Route Bunching Rate: {max_bunching:.4f} (Expected: 0.0 - 0.4)")
    assert 0.0 <= max_bunching <= 0.4, f"FAIL: Max bunching is {max_bunching:.4f}"
    
    # 3. Dwell standard deviation & span checks (B1 requirements)
    route_dwells = df_scores.groupby("route_id")["mean_dwell_sec"].mean()
    min_dwell = route_dwells.min()
    max_dwell = route_dwells.max()
    route_dwell_std = route_dwells.std()
    print(f"3a. Route Dwell Span: {min_dwell:.1f}s - {max_dwell:.1f}s (Expected: min <= 35s, max >= 90s)")
    print(f"3b. Route Dwell Std Dev: {route_dwell_std:.1f}s (Expected: > 12.0s)")
    assert min_dwell <= 35.0, f"FAIL: Min route dwell {min_dwell:.1f}s is > 35.0s"
    assert max_dwell >= 90.0, f"FAIL: Max route dwell {max_dwell:.1f}s is < 90.0s"
    assert route_dwell_std > 12.0, f"FAIL: Route dwell std dev across routes {route_dwell_std:.1f}s <= 12.0s"
    
    # 4. At least 25 distinct daily dates
    distinct_dates = df_scores["date"].nunique()
    print(f"4. Distinct Daily Dates: {distinct_dates} (Expected: >= 25)")
    assert distinct_dates >= 25, f"FAIL: Distinct dates: {distinct_dates}"
    
    # 5. WoW trend non-zero for >80% of routes on latest date
    latest_date = df_scores["date"].max()
    latest_scores = df_scores[df_scores["date"] == latest_date]
    non_zero_trend_count = (latest_scores["wow_trend"].abs() > 0.001).sum()
    pct_non_zero = non_zero_trend_count / len(latest_scores)
    print(f"5. Pct Routes with non-zero WoW Trend: {pct_non_zero*100:.1f}% (Expected: > 80.0%)")
    assert pct_non_zero > 0.8, f"FAIL: WoW trend percentage is {pct_non_zero*100:.1f}%"
    
    # 6. Clean fraction checks for 30-day aggregate bunching/gap rates (B2 requirements)
    overall_seg = df_seg.groupby(["route_id", "stop_id"]).agg(
        bunching_count=("bunching_count", "sum"),
        gap_count=("gap_count", "sum"),
        total_trips=("total_trips", "sum")
    ).reset_index()
    
    eligible_seg = overall_seg[overall_seg["total_trips"] >= 200].copy()
    eligible_seg["bunching_rate"] = eligible_seg["bunching_count"] / eligible_seg["total_trips"]
    eligible_seg["gap_rate"] = eligible_seg["gap_count"] / eligible_seg["total_trips"]
    
    clean_pcts = {25.0, 33.3, 50.0, 66.7}
    for idx, row in eligible_seg.iterrows():
        b_pct = round(row["bunching_rate"] * 100, 1)
        g_pct = round(row["gap_rate"] * 100, 1)
        assert b_pct not in clean_pcts, f"FAIL: Segment {row['stop_id']} has clean bunching rate {b_pct}%"
        assert g_pct not in clean_pcts, f"FAIL: Segment {row['stop_id']} has clean gap rate {g_pct}%"
    print("6. Clean fraction check: PASSED (no aggregate rate is a clean fraction)")
    
    print("\nSUCCESS: All sanity assertions passed successfully!")


if __name__ == "__main__":
    check_sanity()
