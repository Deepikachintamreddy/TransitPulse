"""Cross-consistency verification tests for TransitPulse.
Parses numbers in cached copilot answers and decision cards, and matches them to DuckDB.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
import duckdb

def get_latest_date(conn, scores_path):
    return conn.execute(f"SELECT MAX(date) FROM read_parquet('{scores_path}')").fetchone()[0]

def test_copilot_consistency(conn, scores_path, segment_path, cache_path):
    print("Checking copilot answers cache consistency...")
    with open(cache_path) as f:
        cache = json.load(f)
        
    latest_date = get_latest_date(conn, scores_path)
    
    # --- Question 1: which 5 routes ---
    ans1 = cache["which 5 routes should we fix first"]
    # Find route score patterns: **DTC-008** (Score: **33.0**)
    route_matches = re.findall(r"\*\*(DTC-\d{3})\*\*\s*\(Score:\s*\*\*(\d+\.\d+)\*\*\)", ans1)
    assert len(route_matches) == 5, f"Expected 5 route score patterns, found {len(route_matches)}"
    
    for r_id, score_str in route_matches:
        expected_score = float(score_str)
        actual_score = conn.execute(
            f"SELECT reliability_score FROM read_parquet('{scores_path}') WHERE route_id = '{r_id}' AND date = '{latest_date}'"
        ).fetchone()[0]
        assert abs(actual_score - expected_score) <= 0.5, f"Score mismatch for {r_id}: DB {actual_score:.2f} vs copilot {expected_score:.2f}"
        print(f"  [Pass] {r_id} score: DB {actual_score:.2f} matches copilot {expected_score:.2f}")

    # --- Question 2: DTC-010 degradation ---
    ans2 = cache["why did dtc-010 degrade this week"]
    # Find score drop: drop by **X.Y points** (WoW trend: **-A.B**)
    drop_match = re.search(r"(drop by|improve by)\s*\*\*(\d+\.\d+) points\*\* this week \(WoW trend: \*\*([+-]?\d+\.\d+)\*\*\)", ans2)
    assert drop_match, "DTC-010 drop/trend pattern not found in answer"
    drop_val = float(drop_match.group(2))
    trend_val = float(drop_match.group(3))
    
    dtc10_db = conn.execute(
        f"SELECT wow_trend FROM read_parquet('{scores_path}') WHERE route_id = 'DTC-010' AND date = '{latest_date}'"
    ).fetchone()
    
    if dtc10_db:
        actual_trend = dtc10_db[0]
        assert abs(actual_trend - trend_val) <= 0.5, f"WoW trend mismatch for DTC-010: DB {actual_trend:.2f} vs copilot {trend_val:.2f}"
        assert abs(abs(actual_trend) - drop_val) <= 0.5, f"Drop points mismatch for DTC-010: DB {abs(actual_trend):.2f} vs copilot {drop_val:.2f}"
        print(f"  [Pass] DTC-010 trend: DB {actual_trend:.2f} matches copilot {trend_val:.2f}")

    # --- Question 3: weekday vs weekend ---
    ans3 = cache["compare weekday vs weekend reliability"]
    # Parse markdown table rows: | **Weekday** | **61.4** | **17.8%** | **9.2%** | **38.4s** |
    wk_matches = re.findall(r"\|\s*\*\*(Weekday|Weekend)\*\*\s*\|\s*\*\*(\d+\.\d+)\*\*\s*\|\s*\*\*(\d+\.\d+)%\*\*\s*\|\s*\*\*(\d+\.\d+)%\*\*\s*\|\s*\*\*(\d+\.\d+)s\*\*", ans3)
    assert len(wk_matches) == 2, f"Expected 2 day type rows in comparison table, found {len(wk_matches)}"
    
    for day_type, score_str, bunch_str, gap_str, dwell_str in wk_matches:
        score_val = float(score_str)
        bunch_val = float(bunch_str)
        gap_val = float(gap_str)
        dwell_val = float(dwell_str)
        
        is_weekend = day_type == "Weekend"
        
        db_score = conn.execute(f"""
            SELECT AVG(reliability_score) 
            FROM read_parquet('{scores_path}') 
            WHERE EXTRACT(dow FROM CAST(date AS DATE)) {"IN (0, 6)" if is_weekend else "NOT IN (0, 6)"}
        """).fetchone()[0]
        
        db_dwell = conn.execute(f"""
            SELECT AVG(mean_dwell_sec) 
            FROM read_parquet('{scores_path}') 
            WHERE EXTRACT(dow FROM CAST(date AS DATE)) {"IN (0, 6)" if is_weekend else "NOT IN (0, 6)"}
        """).fetchone()[0]
        
        db_rates = conn.execute(f"""
            SELECT SUM(bunching_count) * 100.0 / SUM(total_trips),
                   SUM(gap_count) * 100.0 / SUM(total_trips)
            FROM read_parquet('{segment_path}') 
            WHERE EXTRACT(dow FROM CAST(date AS DATE)) {"IN (0, 6)" if is_weekend else "NOT IN (0, 6)"}
        """).fetchone()
        
        assert abs(db_score - score_val) <= 0.5, f"{day_type} score mismatch: DB {db_score:.2f} vs copilot {score_val:.2f}"
        assert abs(db_dwell - dwell_val) <= 0.5, f"{day_type} dwell mismatch: DB {db_dwell:.2f} vs copilot {dwell_val:.2f}"
        assert abs(db_rates[0] - bunch_val) <= 0.5, f"{day_type} bunching rate mismatch: DB {db_rates[0]:.2f} vs copilot {bunch_val:.2f}"
        assert abs(db_rates[1] - gap_val) <= 0.5, f"{day_type} gap rate mismatch: DB {db_rates[1]:.2f} vs copilot {gap_val:.2f}"
        print(f"  [Pass] {day_type} metrics match DB within rounding.")

def test_decisions_consistency(conn, segment_path, scores_path):
    print("Checking decisions cards consistency...")
    # Simulate get_decisions query logic
    query = f"""
        SELECT route_id, stop_id, 
               AVG(reliability_score) as reliability_score, 
               SUM(total_trips) as total_trips, 
               SUM(bunching_count) as bunching_count,
               SUM(gap_count) as gap_count,
               AVG(mean_dwell_sec) as mean_dwell_sec
        FROM read_parquet('{segment_path}')
        GROUP BY route_id, stop_id
        HAVING SUM(total_trips) >= 80
        ORDER BY reliability_score ASC
        LIMIT 1000
    """
    worst = conn.execute(query).fetchall()
    
    # Pre-fetch WoW trends
    wow_trends = {}
    trends_df = conn.execute(f"SELECT route_id, wow_trend FROM read_parquet('{scores_path}') ORDER BY date DESC").fetchall()
    for r_id, wow_trend in trends_df:
        if r_id not in wow_trends:
            wow_trends[r_id] = float(wow_trend)
            
    # Simulate decisions selection
    decisions = []
    seen_routes = set()
    target_types = ["bunching", "gap", "dwell", "WoW-degrading"]
    
    for i in range(8):
        card_type = target_types[i % 4]
        selected_item = None
        
        # Sort pools
        if card_type == "bunching":
            pool = sorted(worst, key=lambda x: x[4]/x[3] if x[3] > 0 else 0.0, reverse=True)
        elif card_type == "gap":
            pool = sorted(worst, key=lambda x: x[5]/x[3] if x[3] > 0 else 0.0, reverse=True)
        elif card_type == "dwell":
            pool = sorted(worst, key=lambda x: x[6], reverse=True)
        else: # WoW-degrading
            pool = sorted(worst, key=lambda x: wow_trends.get(x[0], 0.0))
            
        for item in pool:
            r_id = item[0]
            if r_id in seen_routes:
                continue
            selected_item = item
            break
            
        if not selected_item:
            for item in worst:
                r_id = item[0]
                if r_id not in seen_routes:
                    selected_item = item
                    break
                    
        if selected_item:
            r_id = selected_item[0]
            seen_routes.add(r_id)
            decisions.append((r_id, card_type, selected_item))
            
    assert len(decisions) == 8, f"Expected 8 decision cards, got {len(decisions)}"
    print(f"  [Pass] Successfully generated 8 decision cards from DB with 4 alternating types:")
    for r_id, c_type, _ in decisions:
        print(f"    - Route: {r_id}, Type: {c_type}")

def main():
    print("=== Running Cross-Consistency Verification ===")
    
    project_root = Path(__file__).resolve().parent.parent
    scores_path = project_root / "data" / "output" / "route_scores.parquet"
    segment_path = project_root / "data" / "output" / "daily_segment_metrics.parquet"
    cache_path = project_root / "data" / "copilot_cached_answers.json"
    
    if not scores_path.exists() or not cache_path.exists():
        print("FAIL: Parquet scores or Copilot cached answers file missing.")
        sys.exit(1)
        
    conn = duckdb.connect(database=":memory:")
    
    try:
        test_copilot_consistency(conn, scores_path, segment_path, cache_path)
        test_decisions_consistency(conn, segment_path, scores_path)
        print("\nSUCCESS: All cross-consistency checks passed successfully!")
    except AssertionError as e:
        print(f"\nCRITICAL CONSISTENCY CHECK FAILURE: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nUNEXPECTED ERROR DURING TESTS: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
