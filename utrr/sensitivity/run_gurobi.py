# -*- coding: utf-8 -*-
"""Gurobi MIP 基准运行脚本（需本机 gurobipy 许可证）。

对基准算例集合（OD4 真实算例 + 合成规模算例）以 ε-约束扫描求 Pareto 前沿，
结果写入 results/gurobi_benchmark.json，供 4.7 算法对比实验合并展示。

用法：
	python sensitivity/run_gurobi.py [--num-eps 30] [--output results/gurobi_benchmark.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import DATA_SOURCE_SYNTHETIC, UTRRConfig
from src.benchmarks.gurobi_mip import solve_gurobi_sweep
from src.core.instance_builder import build_instance
from src.core.instance_generator import InstanceGenerator


def build_benchmark_instances(config: UTRRConfig) -> dict:
    instances = {}
    instances["OD4"] = build_instance(config)
    synthetic = config.with_overrides(data_source=DATA_SOURCE_SYNTHETIC)
    for layers, rows, yards in config.scalability_sizes:
        inst = InstanceGenerator(synthetic).build(
            n_rail_layers=layers, n_rail_rows=rows, n_yards=yards
        )
        instances[f"synth_{inst.network.counts()['num_nodes']}"] = inst
    return instances


def main() -> None:
    parser = argparse.ArgumentParser(description="Gurobi MIP 基准（ε-约束扫描）")
    parser.add_argument("--num-eps", type=int, default=30)
    parser.add_argument("--output", default=os.path.join("results", "gurobi_benchmark.json"))
    args = parser.parse_args()

    config = UTRRConfig()
    instances = build_benchmark_instances(config)
    payload = {"num_eps": args.num_eps, "instances": {}}
    for name, inst in instances.items():
        counts = inst.network.counts()
        print(f"== {name}（节点 {counts['num_nodes']}，弧 {counts['num_arcs']}，D={inst.deadline:.2f} h）==")
        result = solve_gurobi_sweep(inst, config, num_eps=args.num_eps, verbose=True)
        result["num_nodes"] = counts["num_nodes"]
        result["num_arcs"] = counts["num_arcs"]
        payload["instances"][name] = result
        print(f"   前沿 {result['num_points']} 解，求解 {result['num_solves']} 次，"
              f"耗时 {result['wall_time']:.2f} s")
        for point in result["points"]:
            print(f"   cost={point['cost']:.2f} risk={point['risk']:.6f} T={point['equivalent_time']:.2f}")
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    print("已写入", args.output)


if __name__ == "__main__":
    main()
