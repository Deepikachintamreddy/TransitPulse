"""Generates speedup_chart.png from benchmark_results.json."""

import json
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

# Load benchmark results
results_path = Path("results/benchmark_results.json")
if not results_path.exists():
    print("benchmark_results.json not found!")
    exit(1)

with open(results_path) as f:
    full_results = json.load(f)

# Extract scales
results = {}
for scale in ["small", "medium", "full"]:
    if scale in full_results:
        results[scale] = full_results[scale]

scales = list(results.keys())
x = np.arange(len(scales))
width = 0.35

# Build plots
fig, axes = plt.subplots(1, 2, figsize=(14, 6))

# Use custom styling for premium dark theme matching the dashboard
plt.style.use('dark_background')
fig.patch.set_facecolor('#0f172a') # Slate 900
for ax in axes:
    ax.set_facecolor('#1e293b') # Slate 800
    ax.spines['bottom'].set_color('#475569')
    ax.spines['top'].set_color('#475569')
    ax.spines['left'].set_color('#475569')
    ax.spines['right'].set_color('#475569')
    ax.tick_params(colors='#94a3b8')
    ax.yaxis.label.set_color('#94a3b8')
    ax.xaxis.label.set_color('#94a3b8')
    ax.title.set_color('#f8fafc')

cpu_totals = [results[s]["cpu"]["total"] for s in scales]
gpu_totals = [results[s]["gpu"]["total"] for s in scales]

# Chart 1: Total Processing Time
axes[0].bar(x - width/2, cpu_totals, width, label="CPU (pandas)", color="#ef4444") # Red-500
axes[0].bar(x + width/2, gpu_totals, width, label="GPU (cudf.pandas)", color="#10b981") # Emerald-500

axes[0].set_ylabel("Wall-clock Time (seconds)")
axes[0].set_title("Total Processing Time (Lower is Better)", pad=15)
axes[0].set_xticks(x)
axes[0].set_xticklabels([f"{s.capitalize()}\n({results[s]['rows']})" for s in scales])
axes[0].legend(facecolor='#1e293b', edgecolor='#475569')
axes[0].set_yscale("log")
axes[0].grid(True, which="both", ls="--", alpha=0.2, color='#475569')

# Chart 2: Speedup Factor
speedups = [results[s]["cpu"]["total"] / max(results[s]["gpu"]["total"], 0.001) for s in scales]

bars = axes[1].bar(x, speedups, width * 1.5, color="#3b82f6") # Blue-500
axes[1].set_ylabel("Speedup Multiplier (x)")
axes[1].set_title("GPU Speedup Factor vs CPU (Higher is Better)", pad=15)
axes[1].set_xticks(x)
axes[1].set_xticklabels([f"{s.capitalize()}\n({results[s]['rows']})" for s in scales])
axes[1].grid(True, ls="--", alpha=0.2, color='#475569')

# Add labels to speedup bars
for bar in bars:
    height = bar.get_height()
    axes[1].annotate(f"{height:.1f}x",
                xy=(bar.get_x() + bar.get_width() / 2, height),
                xytext=(0, 5),
                textcoords="offset points",
                ha='center', va='bottom', color='#f8fafc', fontweight='bold')

plt.suptitle("TransitPulse Performance: GPU vs CPU Acceleration", fontsize=16, fontweight='bold', color='#f8fafc', y=0.98)
plt.tight_layout()

# Save to both locations
for path in ["results/speedup_chart.png", "data/speedup_chart.png"]:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=150, facecolor=fig.get_facecolor(), edgecolor='none')
    print(f"Saved benchmark speedup chart to {out_path}")
