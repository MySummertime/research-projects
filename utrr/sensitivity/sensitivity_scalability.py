# -*- coding: utf-8 -*-
"""4.7 算法实验：消融实验与外部对比实验。

**消融实验（表 10）**：本文算法含 4 个创新策略——
	①机会可行性剪枝 ②Pareto 支配剪枝 ③下界剪枝 ④双向汇合
按 4→3→2→1 的阶梯逐级去除（依次去除双向汇合、下界剪枝、机会可行性剪枝，
支配剪枝为最底层机制最后去除），量化各策略对效率的贡献。各变体均为精确
算法，Pareto 前沿应完全一致——一致性列即正确性证据。

**外部对比实验（表 11）**：本文算法 vs Gurobi MIP（ε-约束扫描）vs 加权和法
WST（独立标号设置实现）。三者在相同算例上求解同一双目标模型：
	- 精确算法之间前沿应一致，判别指标为运行时间与工作量；
	- WST 只能取到前沿凸包段（supported solutions），其覆盖率列量化该经典
	  方法的固有损失；
	- Gurobi 结果由 `python sensitivity/run_gurobi.py` 单独运行写入
	  results/gurobi_benchmark.json，本模块自动合并（缺失则标注"待运行"）。

**图 11**：各算法求解时间随网络规模的可扩展性曲线（对数纵轴）。

小规模（≤ scalability_full_enum_max_nodes 节点）另以关闭支配与剪枝的完整
枚举复核前沿一致性。

用法：
	python sensitivity/sensitivity_scalability.py
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import DATA_SOURCE_SYNTHETIC
from src.benchmarks.weighted_sum import solve_weighted_sum
from src.core.instance_generator import InstanceGenerator
from src.solvers.baselines import pareto_filter
from src.solvers.label_correcting import ParetoLabelSolver
from src.utils.paper_tables import write_table
from src.utils.plotting import Visualizer

LADDER = [
	("完整算法（4策略）", {
		"enable_chance_pruning": True, "enable_pruning": True,
		"enable_dominance": True, "bidirectional": True,
	}),
	("去除双向汇合（3策略）", {
		"enable_chance_pruning": True, "enable_pruning": True,
		"enable_dominance": True, "bidirectional": False,
	}),
	("再去除下界剪枝（2策略）", {
		"enable_chance_pruning": True, "enable_pruning": False,
		"enable_dominance": True, "bidirectional": False,
	}),
	("仅保留Pareto支配（1策略）", {
		"enable_chance_pruning": False, "enable_pruning": False,
		"enable_dominance": True, "bidirectional": False,
	}),
]

GUROBI_JSON = os.path.join("results", "gurobi_benchmark.json")


def _objective_set(points) -> set:
	return {(round(p[0], 2), round(p[1], 4)) for p in points}


def _front_points(solutions) -> list:
	return [(s.cost, s.risk) for s in solutions]


def _hv(points: list, ref_risk: float, ref_cost: float) -> float:
	"""二维超体积（最小化口径）。points: [(cost, risk), ...]。"""
	pts = sorted(((r, c) for c, r in points if r <= ref_risk and c <= ref_cost))
	volume, prev_cost = 0.0, ref_cost
	for risk, cost in pts:
		if cost < prev_cost:
			volume += (ref_risk - risk) * (prev_cost - cost)
			prev_cost = cost
	return volume


def _label_count(payload: dict) -> int:
	return sum(row["labels_generated"] for row in payload["stats"])


def run(config, output_dir: str, logger, instance=None) -> dict:
	from src.core.instance_builder import build_instance

	synthetic = config.with_overrides(data_source=DATA_SOURCE_SYNTHETIC)
	instances = []
	if instance is not None:
		instances.append(("OD4真实算例", instance))
	for layers, rows_count, yards in config.scalability_sizes:
		inst = InstanceGenerator(synthetic).build(
			n_rail_layers=layers, n_rail_rows=rows_count, n_yards=yards
		)
		counts = inst.network.counts()
		instances.append((f"合成{counts['num_nodes']}节点", inst))

	# ---------------- 消融实验 ----------------
	ablation_rows = []
	ablation_records = []
	variant_fronts: dict = {}
	own_payloads: dict = {}
	for name, inst in instances:
		reference_points = None
		for label, flags in LADDER:
			cfg = config.with_overrides(**flags)
			payload = ParetoLabelSolver(cfg, inst, logger).solve_pareto()
			front = payload["solutions"]
			points = _front_points(front)
			if reference_points is None:
				reference_points = _objective_set(points)
				own_payloads[name] = payload
			labels = _label_count(payload)
			prune_rate = (
				sum(r["labels_dominated"] + r["labels_chance_pruned"] + r["labels_bounds_pruned"]
					for r in payload["stats"]) / labels
				if labels else 0.0
			)
			variant_fronts[(name, label)] = points
			ablation_rows.append([
				name, label, str(len(front)),
				"是" if _objective_set(points) == reference_points else "否",
				str(labels), f"{prune_rate * 100:.1f}", f"{payload['wall_time']:.3f}",
			])
			ablation_records.append({
				"instance": name, "variant": label, "pareto_size": len(front),
				"labels": labels, "prune_rate": prune_rate, "wall_time": payload["wall_time"],
			})
			logger.info(f"消融 {name} / {label}：前沿 {len(front)}，标号 {labels}，"
						f"耗时 {payload['wall_time']:.3f}s")

	# ---------------- 完整枚举一致性（小规模） ----------------
	full_enum_note = ""
	max_nodes = getattr(config, "scalability_full_enum_max_nodes", 52)
	for name, inst in instances:
		counts = inst.network.counts()
		if counts["num_nodes"] > max_nodes:
			continue
		cfg = config.with_overrides(
			bidirectional=False, enable_pruning=False, enable_dominance=False,
			enable_chance_pruning=True, max_labels_per_node=4_000_000, max_solutions=4_000_000,
		)
		try:
			payload = ParetoLabelSolver(cfg, inst, logger).solve_pareto()
			points = _objective_set(_front_points(payload["solutions"]))
			full_ref = _objective_set(variant_fronts[(name, LADDER[0][0])])
			ok = points == full_ref
			full_enum_note += f"{name}完整枚举一致={'是' if ok else '否'}；"
			logger.info(f"完整枚举校验 {name}：一致={'是' if ok else '否'}，"
						f"标号 {_label_count(payload)}，耗时 {payload['wall_time']:.3f}s")
		except MemoryError:
			full_enum_note += f"{name}完整枚举内存不足；"

	# ---------------- 外部对比 ----------------
	gurobi_payload = {}
	if os.path.exists(GUROBI_JSON):
		with open(GUROBI_JSON, encoding="utf-8") as handle:
			gurobi_payload = json.load(handle).get("instances", {})
	else:
		logger.warning(f"未找到 {GUROBI_JSON}，Gurobi 行以'待运行'占位（python sensitivity/run_gurobi.py）")

	bench_rows = []
	bench_records = []
	scaling = {}
	for name, inst in instances:
		counts = inst.network.counts()
		own_points = variant_fronts[(name, LADDER[0][0])]
		# WST
		wst = solve_weighted_sum(inst, config)
		wst_points = [(p["cost"], p["risk"]) for p in wst["points"]]
		# Gurobi
		key = "OD4" if name.startswith("OD4") else f"synth_{counts['num_nodes']}"
		gur = gurobi_payload.get(key)
		gur_points = [(p["cost"], p["risk"]) for p in gur["points"]] if gur else None
		all_points = own_points + wst_points + (gur_points or [])
		ref_risk = max(r for _, r in all_points) * 1.1 + 1e-12
		ref_cost = max(c for c, _ in all_points) * 1.1 + 1e-12
		hv_own = _hv(own_points, ref_risk, ref_cost)
		own_wall = own_payloads[name]["wall_time"]
		entries = [
			("本文算法", own_points, hv_own, "是",
			 f"标号 {_label_count(own_payloads[name])}", own_wall),
			("加权和法WST", wst_points, _hv(wst_points, ref_risk, ref_cost),
			 "是" if _objective_set(wst_points) <= _objective_set(own_points) else "否",
			 f"扩展 {wst['labels_expanded']} 次", wst["wall_time"]),
			("Gurobi-MIP", gur_points,
			 None if gur_points is None else _hv(gur_points, ref_risk, ref_cost),
			 "待运行" if gur_points is None
			 else ("是" if _objective_set(gur_points) == _objective_set(own_points) else "否"),
			 "待运行" if gur is None else f"{gur['num_solves']} 次求解",
			 None if gur is None else gur["wall_time"]),
		]
		for alg, points, hv, consistent, effort, wall in entries:
			bench_rows.append([
				name, alg, "待运行" if points is None else str(len(points)),
				"待运行" if hv is None else f"{hv:.4g}", consistent, effort,
				"待运行" if wall is None else f"{wall:.3f}",
			])
		bench_records.append({
			"instance": name, "num_nodes": counts["num_nodes"],
			"own": {"points": own_points, "hv": hv_own},
			"wst": {"points": wst_points, "hv": _hv(wst_points, ref_risk, ref_cost),
					"wall_time": wst["wall_time"], "labels": wst["labels_expanded"]},
			"gurobi": None if gur is None else {
				"points": gur_points, "hv": _hv(gur_points, ref_risk, ref_cost),
				"wall_time": gur["wall_time"], "num_solves": gur["num_solves"]},
		})
		scaling[name] = counts["num_nodes"]
		logger.info(f"对比 {name}：本文 {len(own_points)} 解 / WST {len(wst_points)} 解 / "
					f"Gurobi {'待运行' if gur_points is None else f'{len(gur_points)} 解'}")

	# ---------------- 表与图 ----------------
	write_table(
		os.path.join(output_dir, "表10_消融实验.csv"),
		["算例", "变体", "前沿解数", "与完整算法一致", "生成标号数", "剪枝率/%", "时间/s"],
		ablation_rows,
		title="表 10  算法消融实验",
	)
	write_table(
		os.path.join(output_dir, "表11_外部对比.csv"),
		["算例", "算法", "前沿解数", "超体积HV", "与本文前沿一致", "工作量", "时间/s"],
		bench_rows,
		title="表 11  外部对比实验",
	)
	Visualizer(config).plot_algorithm_scaling(
		bench_records, ablation_records, os.path.join(output_dir, "fig11_scalability.png")
	)
	with open(os.path.join(output_dir, "algorithm.json"), "w", encoding="utf-8") as handle:
		json.dump({"ablation": ablation_records, "benchmarks": bench_records,
				   "full_enum_note": full_enum_note}, handle, indent=2, ensure_ascii=False)
	return {"ablation": ablation_records, "benchmarks": bench_records}


if __name__ == "__main__":
	from sensitivity._cli import run_as_script

	run_as_script("scalability", run, "4.7 算法实验")
