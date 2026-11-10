# -*- coding: utf-8 -*-
"""4.5 节点风险耦合敏感性：θ、ρ 双参数切片设计。

θ 与 ρ 均无文献取值依据（形式可溯源至 Cozzani 等的编组站风险框架，数值为算例
设定），故以双参数切片覆盖取值不确定性：
	① 固定 θ 取若干值，逐一扫描 ρ 的若干取值；
	② 固定 ρ 取若干值，逐一扫描 θ 的若干取值。
两方向共用 θ×ρ 全格（各取 0、基准 0.005、2 倍 0.01 h⁻¹），每组合独立重解，
对成本最优与风险最优两类解各核算一次。另设"仅弧段风险"口径行为参照。

用法：
	python sensitivity/sensitivity_node_risk.py
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sensitivity.runner import base_instance, front_extremes
from src.core.instance_builder import build_instance
from src.solvers.label_correcting import ParetoLabelSolver
from src.utils.paper_tables import write_table
from src.utils.plotting import Visualizer
from src.utils.reporting import path_text


def ex_post_node_risk(solution, inst, theta: float, rho: float) -> float:
	"""按实例货场参数事后核算路径的节点转运风险（与式（2）同口径，含 ζ_s）。"""
	total = 0.0
	for arc in solution.arcs:
		if arc.is_transfer:
			yard = inst.network.yards[inst.network.nodes[arc.i].yard]
			total += yard.node_risk(
				inst.network.config.q,
				theta,
				rho,
				inst.network.config.hazmat_risk_factor,
			)
	return total


def run(config, output_dir: str, logger, instance=None) -> dict:
	base = instance or base_instance(config)
	theta_grid = list(config.node_risk_theta_grid)
	rho_grid = list(config.node_risk_rho_grid)

	rows = []
	records = []

	# ---------- 参照：仅弧段风险口径 ----------
	local = config.with_overrides(include_node_risk=False)
	arc_inst = build_instance(local)
	front = ParetoLabelSolver(local, arc_inst, logger).solve_pareto()["solutions"]
	extremes = front_extremes(front)
	for tag, solution in (("成本最优", extremes["cost_optimal"]), ("风险最优", extremes["risk_optimal"])):
		logger.info(f"仅弧段风险 / {tag}：总风险 {solution.risk:.6f}")
	records.append({
		"theta": None, "rho": None,
		"cost_total": extremes["cost_optimal"].risk, "cost_share": 0.0,
		"risk_total": extremes["risk_optimal"].risk, "risk_share": 0.0,
		"service": extremes["cost_optimal"].service_label(config),
		"transfers": sum(1 for a in extremes["cost_optimal"].arcs if a.is_transfer),
	})
	rows.append(["仅弧段风险", "—",
				 f"{extremes['cost_optimal'].risk:.1f}", "0.0",
				 f"{extremes['risk_optimal'].risk:.1f}", "0.0",
				 extremes["cost_optimal"].service_label(config), path_text(extremes["cost_optimal"], arc_inst)])

	# ---------- θ×ρ 全格 ----------
	for theta in theta_grid:
		for rho in rho_grid:
			cfg2 = config.with_overrides(node_risk_theta=theta, node_risk_rho=rho)
			inst2 = build_instance(cfg2)
			front = ParetoLabelSolver(cfg2, inst2, logger).solve_pareto()["solutions"]
			extremes = front_extremes(front)
			cost_opt, risk_opt = extremes["cost_optimal"], extremes["risk_optimal"]
			cost_node = ex_post_node_risk(cost_opt, inst2, theta, rho)
			risk_node = ex_post_node_risk(risk_opt, inst2, theta, rho)
			cost_total, risk_total = cost_opt.risk, risk_opt.risk
			logger.info(
				f"θ={theta:g} ρ={rho:g}：成本最优总风险 {cost_total:.1f}（节点占 {cost_node / cost_total:.1%}），"
				f"风险最优总风险 {risk_total:.1f}（节点占 {risk_node / risk_total:.1%}）"
			)
			records.append({
				"theta": theta, "rho": rho,
				"cost_total": cost_total, "cost_share": cost_node / cost_total if cost_total else 0.0,
				"risk_total": risk_total, "risk_share": risk_node / risk_total if risk_total else 0.0,
				"service": cost_opt.service_label(config),
				"transfers": sum(1 for a in cost_opt.arcs if a.is_transfer),
			})
			rows.append([
				f"{theta:g}", f"{rho:g}",
				f"{cost_total:.1f}", f"{cost_node / cost_total * 100:.1f}",
				f"{risk_total:.1f}", f"{risk_node / risk_total * 100:.1f}",
				cost_opt.service_label(config), path_text(cost_opt, inst2),
			])

	write_table(
		os.path.join(output_dir, "表8_节点风险敏感性.csv"),
		["θ/(h⁻¹)", "ρ/(h⁻¹)", "成本最优总风险/人", "其节点占比/%",
		 "风险最优总风险/人", "其节点占比/%", "服务类型", "路径"],
		rows,
		title="表 9  节点风险敏感性",
	)

	visualizer = Visualizer(config)
	visualizer.plot_node_risk(records, os.path.join(output_dir, "fig9_node_risk.png"))

	with open(os.path.join(output_dir, "node_risk.json"), "w", encoding="utf-8") as handle:
		json.dump(records, handle, indent=2, ensure_ascii=False)
	return {"rows": rows, "records": records}


if __name__ == "__main__":
	from sensitivity._cli import run_as_script

	run_as_script("node_risk", run, "节点风险耦合敏感性（θ、ρ 双参数切片）")
