"""Script to plot committed speedup chart for TransitPulse from results/benchmark_results.json."""

from __future__ import annotations

import json
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

def main() -> None:
    results_path = Path("results/benchmark_results.json")
    output_chart_path = Path("results/speedup_chart.png")
    
    with open(results_path) as f:
        results = json.load(f)
        
    scales = list(results.keys())
    
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    
    # Chart 1: CPU vs GPU Total Time (Log scale)
    x = np.arange(len(scales))
    width = 0.35
    
    cpu_totals = [results[s]["cpu"]["total"] for s in scales]
    gpu_totals = [results[s]["gpu"]["total"] for s in scales]
    
    axes[0].bar(x - width/2, cpu_totals, width, label="CPU (pandas)", color="#ff4a5a")
    axes[0].bar(x + width/2, gpu_totals, width, label="GPU (cudf.pandas)", color="#4caf50")
    
    axes[0].set_ylabel("Wall-clock Time (seconds)")
    axes[0].set_title("Total Processing Time (Lower is Better)")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels([f"{s.capitalize()}\n({results[s]['rows']})" for s in scales])
    axes[0].legend()
    axes[0].set_yscale("log")
    axes[0].grid(True, which="both", ls="--", alpha=0.3)
    
    # Chart 2: Speedup multiplier (CPU / GPU)
    speedups = [results[s]["cpu"]["total"] / results[s]["gpu"]["total"] for s in scales]
    
    bars = axes[1].bar(x, speedups, width * 1.5, color="#2196f3")
    axes[1].set_ylabel("Speedup Multiplier (x)")
    axes[1].set_title("GPU Speedup Factor vs CPU (Higher is Better)")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels([f"{s.capitalize()}\n({results[s]['rows']})" for s in scales])
    axes[1].grid(True, ls="--", alpha=0.3)
    
    # Add values on top of bars
    for bar in bars:
        height = bar.get_height()
        axes[1].annotate(f"{height:.1f}x",
                    xy=(bar.get_x() + bar.get_width() / 2, height),
                    xytext=(0, 3),  # 3 points vertical offset
                    textcoords="offset points",
                    ha='center', va='bottom', fontweight='bold', color='black')
                    
    plt.suptitle("TransitPulse Performance: GPU vs CPU Acceleration (Colab T4)", fontsize=16, fontweight='bold')
    plt.tight_layout()
    plt.savefig(output_chart_path, dpi=150)
    print(f"Committed speedup chart saved to {output_chart_path}")

if __name__ == "__main__":
    main()
