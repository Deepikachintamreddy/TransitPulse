"""TransitPulse configuration — paths, thresholds, and feature flags."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class DataScale:
    """Defines a data-generation scale tier."""

    name: str
    num_routes: int
    num_days: int
    ping_interval_sec: int
    approx_rows: str  # human-readable label


# Pre-defined scale tiers for benchmarking
SCALES: dict[str, DataScale] = {
    "small": DataScale("small", num_routes=20, num_days=30, ping_interval_sec=30, approx_rows="~1.1M"),
    "medium": DataScale("medium", num_routes=80, num_days=30, ping_interval_sec=30, approx_rows="~25M"),
    "full": DataScale("full", num_routes=200, num_days=30, ping_interval_sec=30, approx_rows="~150M"),
}


@dataclass
class TransitPulseConfig:
    """Master configuration for the TransitPulse pipeline."""

    # ── Paths ──────────────────────────────────────────────────────────
    project_root: Path = field(default_factory=lambda: Path(__file__).resolve().parent)

    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"

    @property
    def pings_dir(self) -> Path:
        return self.data_dir / "pings"

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "output"

    # ── Mode ───────────────────────────────────────────────────────────
    mode: Literal["local", "cloud"] = "local"

    # ── GCP settings (cloud mode) ──────────────────────────────────────
    gcp_project: str = field(default_factory=lambda: os.getenv("GCP_PROJECT", ""))
    gcs_bucket: str = field(default_factory=lambda: os.getenv("GCS_BUCKET", "transitpulse-data"))
    bq_dataset: str = field(default_factory=lambda: os.getenv("BQ_DATASET", "transitpulse"))

    # ── Gemini ─────────────────────────────────────────────────────────
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str = "gemini-2.5-flash"

    # ── Reliability scoring thresholds ─────────────────────────────────
    bunching_threshold: float = 0.25   # headway < 25 % of scheduled → bunching
    gap_threshold: float = 2.0         # headway > 200 % of scheduled → gap
    weight_headway_cov: float = 0.40
    weight_bunching: float = 0.30
    weight_gap: float = 0.30

    # ── Server ─────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000

    # ── Delhi bounding box (for synthetic lat/lon) ─────────────────────
    delhi_lat_min: float = 28.40
    delhi_lat_max: float = 28.88
    delhi_lon_min: float = 76.84
    delhi_lon_max: float = 77.35

    # ── Synthetic generator tuning ─────────────────────────────────────
    stops_per_route_min: int = 15
    stops_per_route_max: int = 45
    buses_per_route_min: int = 8
    buses_per_route_max: int = 25
    peak_hours: tuple[int, ...] = (8, 9, 17, 18)

    def ensure_dirs(self) -> None:
        """Create data directories if they don't exist."""
        self.pings_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)


# Singleton
CFG = TransitPulseConfig()
