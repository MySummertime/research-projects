"""4.5 节点风险耦合敏感性：风险构成分解与耦合系数 θ、ρ 的影响。

包含两组设置：
	① 风险口径对比：仅弧段风险 vs 弧段 + 节点风险；
	② 耦合系数档位：θ、ρ 取 {0, 1×, 2×} 基准值。
所有设置均以"基准算例的货场参数"事后核算节点风险，使不同口径可比。

用法：
	python sensitivity/sensitivity_node_risk.py
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sensitivity.runner import base_instance, front_extremes, scaled_instance
from src.solvers.label_correcting import ParetoLabelSolver
from src.utils.paper_tables import write_table
from src.utils.plotting import Visualizer
from src.utils.reporting import path_text


def ex_post_node_risk(solution, base, theta: float, rho: float) -> float:
	"""按基准货场参数事后核算路径的节点转运风险。

	与模型式（2）同口径：必须乘品类风险系数 ζ_s。旧版漏乘 ζ_s，导致表 6 的
	节点风险占比（11.9%/16.0%）与表 2/附表的模型风险口径（14.0%/18.6%）不一致。
	"""
	total = 0.0
	for arc in solution.arcs:
		if arc.is_transfer:
			yard = base.network.yards[base.network.nodes[arc.i].yard]
			total += yard.node_risk(
				base.network.config.q,
				theta,
				rho,
				base.network.config.hazmat_risk_factor,
			)
	return total


def run(config, output_dir: str, logger, instance=None) -> dict:
	base = instance or base_instance(config)
	deadline = base.deadline
	theta0, rho0 = config.node_risk_theta, config.node_risk_rho

	settings = [("仅弧段风险", False, 1.0)]
	for scale in config.node_risk_scale_grid:
		settings.append((f"θ,ρ={scale:g}×基准", True, scale))
	short_labels = {"仅弧段风险": "仅弧段"}
	for scale in config.node_risk_scale_grid:
		short_labels[f"θ,ρ={scale:g}×基准"] = f"θ,ρ×{scale:g}"

	rows = []
	records = []
	for label, include, scale in settings:
		local = config.with_overrides(include_node_risk=include)
		derived = scaled_instance(
			base, local, deadline=deadline, node_risk_scale=scale, include_node_risk=include
		)
		solver = ParetoLabelSolver(local, derived, logger)
		payload = solver.solve_pareto()
		front = payload["solutions"]
		extremes = front_extremes(front)
		if extremes["cost_optimal"] is None:
			logger.warning(f"{label}：无可行解")
			continue

		for tag, solution in (("成本最优", extremes["cost_optimal"]), ("风险最优", extremes["risk_optimal"])):
			arc_risk = solution.risk_breakdown()["arc_risk"]
			node_risk = ex_post_node_risk(solution, base, theta0, rho0)
			total = arc_risk + node_risk
			rows.append(
				[
					label,
					tag,
					solution.service_label(config),
					"/".join(solution.yards_used(derived.network)),
					f"{solution.cost:.2f}",
					f"{solution.risk:.6f}",
					f"{total:.6f}",
					f"{node_risk / total:.4f}" if total > 0 else "0",
					sum(1 for a in solution.arcs if a.is_transfer),
					path_text(solution, derived),
				]
			)
			logger.info(
				f"{label} / {tag}：成本 ¥{solution.cost:,.0f}，模型风险 {solution.risk:.6f}，"
				f"基准口径总风险 {total:.6f}（节点占 {node_risk / total:.1%}），"
				f"货场 {'/'.join(solution.yards_used(derived.network))}"
			)

		cost_best = extremes["cost_optimal"]
		node_risk_model = 0.0
		if include:
			for arc in cost_best.arcs:
				if arc.is_transfer:
					yard = derived.network.yards[derived.network.nodes[arc.i].yard]
					node_risk_model += yard.node_risk(
						derived.network.config.q,
						theta0 * scale,
						rho0 * scale,
						derived.network.config.hazmat_risk_factor,
					)
		node_risk_true = ex_post_node_risk(cost_best, base, theta0, rho0)
		records.append(
			{
				"label": short_labels.get(label, label),
				"arc_risk": cost_best.risk_breakdown()["arc_risk"],
				"node_risk_model": node_risk_model,
				"node_risk_omitted": 0.0 if include else node_risk_true,
				"node_risk_true": node_risk_true,
				"cost": cost_best.cost,
				"transfers": sum(1 for a in cost_best.arcs if a.is_transfer),
				"yards": cost_best.yards_used(derived.network),
				"front_size": len(front),
			}
		)

	write_table(
		os.path.join(output_dir, "表8_节点风险敏感性.csv"),
		["风险口径", "解类型", "服务类型", "货场", "总成本/元", "模型总风险",
		 "基准口径总风险", "节点风险占比", "转运次数", "路径"],
		rows,
		title="表 8  节点风险敏感性",
	)

	visualizer = Visualizer(config)
	visualizer.plot_node_risk(records, os.path.join(output_dir, "fig9_node_risk.png"))

	with open(os.path.join(output_dir, "node_risk.json"), "w", encoding="utf-8") as handle:
		json.dump(records, handle, indent=2, ensure_ascii=False)
	return {"rows": rows, "records": records}


if __name__ == "__main__":
	from sensitivity._cli import run_as_script

	run_as_script("node_risk", run, "4.5 节点风险耦合敏感性")
