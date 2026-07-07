"""Synthetic data generator for TransitPulse.
Generates realistic bus GPS pings with bunching, gaps, and dwell anomalies.
Sets route personalities to create leaderboard spread.
"""

from __future__ import annotations

import argparse
import datetime
import math
import os
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from config import CFG, SCALES, DataScale


def generate_route_geography(route_id: int) -> list[tuple[float, float, str]]:
    """Generates a list of stop coords along a route path within Delhi bounding box."""
    # Pick a random start and end point
    lat_start = random.uniform(CFG.delhi_lat_min + 0.05, CFG.delhi_lat_max - 0.05)
    lon_start = random.uniform(CFG.delhi_lon_min + 0.05, CFG.delhi_lon_max - 0.05)
    
    # Route length
    angle = random.uniform(0, 2 * math.pi)
    dist = random.uniform(0.08, 0.20)  # degrees
    lat_end = lat_start + dist * math.sin(angle)
    lon_end = lon_start + dist * math.cos(angle)
    
    num_stops = random.randint(CFG.stops_per_route_min, CFG.stops_per_route_max)
    
    stops = []
    for i in range(num_stops):
        fraction = i / (num_stops - 1)
        lat = lat_start + fraction * (lat_end - lat_start)
        lon = lon_start + fraction * (lon_end - lon_start)
        lat += random.uniform(-0.0005, 0.0005)
        lon += random.uniform(-0.0005, 0.0005)
        
        stop_id = f"STOP_{route_id:03d}_{i:02d}"
        stops.append((lat, lon, stop_id))
    return stops


def generate_pings_for_day(
    day_offset: int,
    date_str: str,
    routes: list[int],
    scale: DataScale,
    route_stops: dict[int, list[tuple[float, float, str]]],
    output_dir: Path
) -> None:
    """Generates and writes ping data for a single day."""
    day_date = datetime.date.fromisoformat(date_str)
    records = []
    
    for route_id in routes:
        stops = route_stops[route_id]
        num_stops = len(stops)
        
        # ── Route Reliability Personalities ──
        # Targets: At least 4 green routes (>=70), 4-6 red routes (<40), and the rest amber.
        # DTC-003, DTC-006, DTC-009, DTC-012, DTC-015 (5 routes total) -> GREEN
        # DTC-002, DTC-005, DTC-008, DTC-011, DTC-014, DTC-017, DTC-020 (7 routes total) -> RED
        # All others (DTC-001, DTC-004, DTC-007, DTC-010, DTC-013, DTC-016, DTC-018, DTC-019) -> AMBER
        
        is_green = route_id in [3, 6, 9, 12, 15]
        is_red = route_id in [2, 5, 8, 11, 14, 17, 20]
        
        if is_green:
            scheduled_headway_min = random.choice([12, 15])
            bunching_prob = random.uniform(0.01, 0.03)  # 1-3%
            gap_prob = random.uniform(0.005, 0.015)    # 0.5-1.5%
            headway_noise_std_min = 0.2  # very low noise
            dwell_base_sec = 20
            # Green routes have stable, low ridership profiles
            route_base_boardings = 2500
        elif is_red:
            scheduled_headway_min = random.choice([5, 6, 7])  # high-frequency congested corridors
            bunching_prob = random.uniform(0.24, 0.32)  # 24-32%
            gap_prob = random.uniform(0.12, 0.16)       # 12-16%
            headway_noise_std_min = 3.8  # high noise
            dwell_base_sec = 35
            # Red routes are congested trunk corridors with high ridership
            route_base_boardings = 15000
        else:
            scheduled_headway_min = random.choice([8, 10])
            bunching_prob = random.uniform(0.08, 0.12)  # 8-12%
            gap_prob = random.uniform(0.04, 0.06)       # 4-6%
            headway_noise_std_min = 1.2  # moderate noise
            dwell_base_sec = 25
            route_base_boardings = 6000

        scheduled_headway_sec = scheduled_headway_min * 60
        
        # Disruption days: inject periodic traffic disruption
        is_disrupted_day = False
        if is_red and (day_offset % 6 == 0):
            is_disrupted_day = True
        elif not is_green and (day_offset % 10 == 0):
            is_disrupted_day = True
            
        # Active buses on this route today
        num_buses = random.randint(CFG.buses_per_route_min, CFG.buses_per_route_max)
        
        # Day schedule: 06:00 to 22:00 (16 hours)
        start_time_sec = 6 * 3600
        end_time_sec = 22 * 3600
        
        # Build departure schedule
        trip_departures = []
        curr_time = start_time_sec
        trip_idx = 0
        
        while curr_time < end_time_sec:
            # Add gradual transitions over peak/off-peak hours
            # Peak hours: 8-10 AM (28800-36000) and 5-7 PM (61200-68400)
            hour = curr_time / 3600.0
            is_peak = (8.0 <= hour <= 10.0) or (17.0 <= hour <= 19.0)
            
            # Dispatch noise with log-normal shape to represent delay skewness
            noise_scale = headway_noise_std_min * (1.8 if is_peak else 1.0)
            if is_disrupted_day:
                noise_scale *= 2.5
                
            dep_noise = random.lognormvariate(0.5, 0.3) * noise_scale * 30
            actual_dep = curr_time + dep_noise
            
            # Explicitly inject bunching/gaps to match target probabilities
            is_bunch = random.random() < bunching_prob
            is_gap = random.random() < gap_prob
            
            if is_bunch and trip_departures:
                # Bunch with the preceding bus
                actual_dep = trip_departures[-1][1] + random.randint(20, 60)
            elif is_gap:
                # Inject massive gap delay
                actual_dep += scheduled_headway_sec * random.uniform(1.8, 2.6)
                
            trip_departures.append((trip_idx, actual_dep, is_bunch, is_gap))
            
            # Move schedule time forward
            curr_time += scheduled_headway_sec
            trip_idx += 1
            
        # Simulate each trip moving along the stops
        for trip_idx_num, dep_time, was_bunch, was_gap in trip_departures:
            trip_id = f"TRIP_{route_id:03d}_{date_str.replace('-', '')}_{trip_idx_num:03d}"
            vehicle_id = f"BUS_{route_id:03d}_{(trip_idx_num % num_buses):02d}"
            
            sim_time = dep_time
            avg_speed = random.uniform(0.00018, 0.00024)  # degrees/sec
            
            for stop_seq in range(num_stops):
                lat, lon, stop_id = stops[stop_seq]
                
                # Sane stop-dependent Dwell Times
                # Busy interchanges (every 4th stop): 45-75s
                # Terminals (start/end stops): 60-90s
                # Minor stops: 15-30s
                if stop_seq == 0 or stop_seq == num_stops - 1:
                    base_dwell = random.randint(60, 90)
                elif stop_seq % 4 == 0:
                    base_dwell = random.randint(45, 75)
                else:
                    base_dwell = random.randint(15, 30)
                
                # Apply route-specific dwell factor to meet the new spread requirements
                # Dwell column spans >=35s to >=90s with std >12s
                route_dwell_multiplier = 0.5 + 2.1 * ((route_id - 1) / 19.0)
                base_dwell = int(base_dwell * route_dwell_multiplier)
                
                # Peak multiplier: 1.3 - 1.8x
                hour_float = (sim_time / 3600.0) % 24
                is_peak = (8.0 <= hour_float <= 10.0) or (17.0 <= hour_float <= 19.0)
                peak_multiplier = random.uniform(1.3, 1.8) if is_peak else 1.0
                
                dwell_sec = int(base_dwell * peak_multiplier)
                
                # Travel time from previous stop
                if stop_seq > 0:
                    prev_lat, prev_lon, _ = stops[stop_seq - 1]
                    dist = math.hypot(lat - prev_lat, lon - prev_lon)
                    travel_time_sec = dist / avg_speed
                    
                    # Travel congestion multiplier
                    congestion = random.uniform(1.3, 1.8) if is_peak else random.uniform(0.9, 1.1)
                    if is_disrupted_day:
                        congestion *= random.uniform(1.4, 2.0)
                        
                    # Log-normal travel jitter to kill synthetic sawtooth timeline fingerprint
                    travel_jitter = random.lognormvariate(1.2, 0.4) * 20
                    sim_time += travel_time_sec * congestion + travel_jitter
                    
                # Record ping
                dt = datetime.datetime.combine(day_date, datetime.time()) + datetime.timedelta(seconds=int(sim_time))
                records.append({
                    "timestamp": dt,
                    "vehicle_id": vehicle_id,
                    "route_id": f"DTC-{route_id:03d}",
                    "stop_id": stop_id,
                    "stop_sequence": stop_seq,
                    "latitude": lat,
                    "longitude": lon,
                    "trip_id": trip_id,
                    "scheduled_headway_sec": scheduled_headway_sec,
                    "dwell_sec": dwell_sec,
                    # Save route base ridership profile
                    "route_base_boardings": route_base_boardings
                })
                
                # Bus remains at stop for dwell duration
                sim_time += dwell_sec
                
    # Create DataFrame
    df = pd.DataFrame(records)
    
    # Filter out timestamps that overflowed day bounds to keep date partition clean
    df = df[df["timestamp"].dt.date == day_date]
    df = df.sort_values(by="timestamp").reset_index(drop=True)
    
    # Save partitioned Parquet
    partition_path = output_dir / f"date={date_str}"
    partition_path.mkdir(parents=True, exist_ok=True)
    
    table = pa.Table.from_pandas(df)
    pq.write_table(table, partition_path / "data.parquet", compression="snappy")
    print(f"Generated {len(df):,} pings for {date_str} -> {partition_path / 'data.parquet'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="TransitPulse Synthetic Data Generator")
    parser.add_argument(
        "--scale",
        choices=["small", "medium", "full"],
        default="small",
        help="Select scale"
    )
    args = parser.parse_args()
    
    scale = SCALES[args.scale]
    print(f"Starting synthetic generation for scale '{args.scale}' ({scale.approx_rows} rows)")
    print(f"Routes: {scale.num_routes}, Days: {scale.num_days}, Ping Interval: {scale.ping_interval_sec}s")
    
    CFG.ensure_dirs()
    
    random.seed(42)
    np.random.seed(42)
    
    routes = list(range(1, scale.num_routes + 1))
    route_stops = {route_id: generate_route_geography(route_id) for route_id in routes}
    
    end_date = datetime.date(2026, 7, 5)
    start_date = end_date - datetime.timedelta(days=scale.num_days - 1)
    
    for day_offset in range(scale.num_days):
        date_str = (start_date + datetime.timedelta(days=day_offset)).isoformat()
        generate_pings_for_day(
            day_offset=day_offset,
            date_str=date_str,
            routes=routes,
            scale=scale,
            route_stops=route_stops,
            output_dir=CFG.pings_dir
        )
        
    print("Synthetic data generation complete!")


if __name__ == "__main__":
    main()
