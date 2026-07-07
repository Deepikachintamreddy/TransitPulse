"""Database abstraction layer for TransitPulse.
Supports local DuckDB (direct Parquet querying) and BigQuery in cloud mode.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from config import CFG


class TransitPulseDB:
    """Manages queries to either local DuckDB or BigQuery."""

    def __init__(self, mode: str = "local"):
        self.mode = mode
        self.duck_conn = None
        
        if self.mode == "local":
            # Initialize DuckDB local in-memory or file database
            self.duck_conn = duckdb.connect(database=":memory:")
            self.init_local_tables()
        else:
            # Cloud mode: initialize BigQuery client
            from google.cloud import bigquery
            self.bq_client = bigquery.Client(project=CFG.gcp_project)
            print(f"BigQuery serving layer initialized in project: {CFG.gcp_project}")

    def init_local_tables(self) -> None:
        """Create views in DuckDB over the output parquet files."""
        scores_path = CFG.output_dir / "route_scores.parquet"
        segment_path = CFG.output_dir / "daily_segment_metrics.parquet"
        anomaly_path = CFG.output_dir / "anomaly_events.parquet"

        if not scores_path.exists():
            # If parquet doesn't exist, create empty tables or register mock schemas
            print("WARNING: Parquet outputs not found. DuckDB views might fail until pipeline runs.")
            # We can create dummy files so startup doesn't crash
            return

        # Register views pointing to parquet files directly
        # This keeps the DuckDB database dynamically in sync with parquet outputs
        self.duck_conn.execute(f"CREATE OR REPLACE VIEW route_scores AS SELECT * FROM read_parquet('{scores_path}')")
        self.duck_conn.execute(f"CREATE OR REPLACE VIEW daily_segment_metrics AS SELECT * FROM read_parquet('{segment_path}')")
        self.duck_conn.execute(f"CREATE OR REPLACE VIEW anomaly_events AS SELECT * FROM read_parquet('{anomaly_path}')")
        print("DuckDB views created successfully.")

    def run_query(self, query: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        """Helper to run SQL query on DuckDB or BigQuery."""
        if self.mode == "local":
            if self.duck_conn is None:
                # Late-bind if connection was missed
                self.duck_conn = duckdb.connect(database=":memory:")
                self.init_local_tables()
                
            # DuckDB supports named parameters with $name or standard python interpolation
            # Let's execute and return dataframe
            if params:
                df = self.duck_conn.execute(query, params).df()
            else:
                df = self.duck_conn.execute(query).df()
        else:
            # Cloud mode (BigQuery)
            # Standard BigQuery query
            job_config = None
            if params:
                from google.cloud import bigquery
                query_params = [
                    bigquery.ScalarQueryParameter(name, "STRING" if isinstance(val, str) else "FLOAT", val)
                    for name, val in params.items()
                ]
                job_config = bigquery.QueryJobConfig(query_parameters=query_params)
            
            # Map simple table names to dataset qualified names
            bq_query = query.replace("route_scores", f"`{CFG.gcp_project}.{CFG.bq_dataset}.route_scores`")
            bq_query = bq_query.replace("daily_segment_metrics", f"`{CFG.gcp_project}.{CFG.bq_dataset}.daily_segment_metrics`")
            bq_query = bq_query.replace("anomaly_events", f"`{CFG.gcp_project}.{CFG.bq_dataset}.anomaly_events`")
            
            query_job = self.bq_client.query(bq_query, job_config=job_config)
            df = query_job.to_dataframe()

        import numpy as np
        return df.replace({np.nan: None})

    # ── Database Endpoint Operations ───────────────────────────────────

    def get_route_scores(self, sort_by: str = "reliability_score", ascending: bool = True) -> list[dict[str, Any]]:
        """Returns sorted route reliability scores."""
        direction = "ASC" if ascending else "DESC"
        # Validate column name to prevent SQL injection
        valid_cols = ["route_id", "reliability_score", "mean_headway", "bunching_count", "gap_count", "mean_dwell_sec", "wow_trend", "date", "route_base_boardings"]
        if sort_by not in valid_cols:
            sort_by = "reliability_score"
            
        # Get latest date available in the route_scores table
        try:
            latest_date_df = self.run_query("SELECT MAX(date) as max_date FROM route_scores")
            latest_date = latest_date_df.iloc[0]["max_date"]
        except Exception:
            latest_date = None

        if latest_date:
            query = f"SELECT * FROM route_scores WHERE date = $latest_date ORDER BY {sort_by} {direction}"
            params = {"latest_date": str(latest_date)}
        else:
            query = f"SELECT * FROM route_scores ORDER BY {sort_by} {direction}"
            params = {}

        df = self.run_query(query, params)
        return df.to_dict(orient="records")

    def get_route_timeline(self, route_id: str) -> list[dict[str, Any]]:
        """Returns historical scores timeline for a specific route."""
        query = "SELECT date, reliability_score, mean_headway, mean_dwell_sec, bunching_count, gap_count FROM route_scores WHERE route_id = $route_id ORDER BY date ASC"
        df = self.run_query(query, {"route_id": route_id})
        return df.to_dict(orient="records")

    def get_worst_segments(self, limit: int = 10) -> list[dict[str, Any]]:
        """Returns the bottom N route segments sorted by reliability score."""
        try:
            latest_date_df = self.run_query("SELECT MAX(date) as max_date FROM daily_segment_metrics")
            latest_date = latest_date_df.iloc[0]["max_date"]
        except Exception:
            latest_date = None

        if latest_date:
            query = f"SELECT route_id, stop_id, reliability_score, total_trips, bunching_rate, gap_rate, mean_dwell_sec, route_base_boardings FROM daily_segment_metrics WHERE date = $latest_date ORDER BY reliability_score ASC LIMIT {limit}"
            params = {"latest_date": str(latest_date)}
        else:
            query = f"SELECT route_id, stop_id, reliability_score, total_trips, bunching_rate, gap_rate, mean_dwell_sec, route_base_boardings FROM daily_segment_metrics ORDER BY reliability_score ASC LIMIT {limit}"
            params = {}
            
        df = self.run_query(query, params)
        return df.to_dict(orient="records")

    def get_anomalies(self, route_id: str | None = None, anomaly_type: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Returns recent anomaly events, optionally filtered."""
        where_clauses = []
        params = {}
        
        if route_id:
            where_clauses.append("route_id = $route_id")
            params["route_id"] = route_id
        if anomaly_type:
            where_clauses.append("anomaly_type = $anomaly_type")
            params["anomaly_type"] = anomaly_type
            
        where_str = ""
        if where_clauses:
            where_str = "WHERE " + " AND ".join(where_clauses)
            
        query = f"SELECT timestamp_str, vehicle_id, route_id, stop_id, stop_sequence, headway_sec, scheduled_headway_sec, anomaly_type FROM anomaly_events {where_str} ORDER BY timestamp_str DESC LIMIT {limit}"
        df = self.run_query(query, params)
        return df.to_dict(orient="records")

    def compare_periods(self, route_id: str, date1: str, date2: str) -> dict[str, Any]:
        """Compares route performance metrics between two dates."""
        query = "SELECT reliability_score, mean_headway, bunching_count, gap_count FROM route_scores WHERE route_id = $route_id AND date IN ($date1, $date2)"
        df = self.run_query(query, {"route_id": route_id, "date1": date1, "date2": date2})
        return df.to_dict(orient="records")


# Database Singleton
DB = TransitPulseDB(mode=CFG.mode)
