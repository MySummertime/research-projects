# -*- coding: utf-8 -*-
"""4.4 转运时间波动敏感性：转运时间 N(e,σ) 的波动参数 σ 对路径与可靠度的影响。

两类模型使用同一组"真实"转运时间评价：
	- 本文模型按真实波动规划（机会约束）；
	- 确定性模型按期望值规划（σ = 0，硬约束 T0 + Σμ_i ≤ D），但同样用真实波动
	  参数评价其实际可靠度，从而暴露"名义满足、实际虚高"的偏差。

用法：
	python sensitivity/sensitivity_sigma.py
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sensitivity.runner import path_sigma, scaled_instance, true_reliability
from src.core.instance_builder import build_instance
from src.solvers.label_correcting import ParetoLabelSolver
from src.utils.paper_tables import write_table
from src.utils.plotting import Visualizer
from src.utils.reporting import path_text


def run(config, output_dir: str, logger, instance=None) -> dict:
	rows = []
	records = []
	for sigma in config.period_grid:
		# 真实算例：转运时间波动参数取 σ，D 与拓扑保持不变
		cfg = config.with_overrides(transfer_sigma=float(sigma))
		truth = build_instance(cfg)
		deadline = truth.deadline
		logger.info(f"σ = {sigma:.1f} h（D = {deadline:.2f} h），α = {cfg.alpha:.2f}")

		solver = ParetoLabelSolver(cfg, truth, logger)
		proposed_payload = solver.solve_scalar("cost", lam=cfg.lambda_alpha())
		proposed = proposed_payload["solutions"][0] if proposed_payload["solutions"] else None

		planning = scaled_instance(truth, cfg, sigma_scale=0.0)
		det_solver = ParetoLabelSolver(cfg, planning, logger)
		det_payload = det_solver.solve_scalar("cost", lam=0.0)
		deterministic = det_payload["solutions"][0] if det_payload["solutions"] else None

		if proposed is None:
			logger.warning(f"σ = {sigma:.1f} h：本文模型无可行解")
			continue
		proposed_reliability = true_reliability(proposed, truth, deadline)
		deterministic_reliability = (
			None if deterministic is None else true_reliability(deterministic, truth, deadline)
		)
		logger.info(
			f"σ = {sigma:.1f} h：本文模型 ¥{proposed.cost:,.0f}"
			f"（实际可靠度 {proposed_reliability:.4f}，路径 σ={path_sigma(proposed, truth):.2f}）；"
			f"确定性模型 ¥{(deterministic.cost if deterministic else float('nan')):,.0f}"
			f"（实际可靠度 {'—' if deterministic_reliability is None else f'{deterministic_reliability:.4f}'}）"
		)
		rows.append(
			[
				f"{sigma:.1f}",
				proposed.service_label(cfg),
				"/".join(proposed.yards_used(truth.network)),
				f"{proposed.cost:.2f}",
				f"{proposed.risk:.6f}",
				f"{proposed_reliability:.4f}",
				"—" if deterministic is None else deterministic.service_label(cfg),
				"—" if deterministic is None else "/".join(deterministic.yards_used(truth.network)),
				"—" if deterministic is None else f"{deterministic.cost:.2f}",
				"—" if deterministic_reliability is None else f"{deterministic_reliability:.4f}",
				path_text(proposed, truth),
			]
		)
		records.append(
			{
				"sigma_h": float(sigma),
				"proposed_cost": proposed.cost,
				"proposed_risk": proposed.risk,
				"reliability": proposed_reliability,
				"proposed_service": proposed.service,
				"proposed_yards": proposed.yards_used(truth.network),
				"det_service": None if deterministic is None else deterministic.service,
				"det_yards": None if deterministic is None else deterministic.yards_used(truth.network),
				"det_cost": None if deterministic is None else deterministic.cost,
				"det_reliability": (
					proposed_reliability if deterministic_reliability is None else deterministic_reliability
				),
				"path": path_text(proposed, truth),
			}
		)

	write_table(
		os.path.join(output_dir, "表7_波动敏感性.csv"),
		["σ/h", "本文服务类型", "本文货场", "本文成本/元", "本文风险", "本文实际可靠度",
		 "确定性服务类型", "确定性货场", "确定性成本/元", "确定性实际可靠度", "本文路径"],
		rows,
		title="表 7  转运时间波动对路径与可靠度的影响",
	)

	visualizer = Visualizer(config)
	visualizer.plot_sigma(records, os.path.join(output_dir, "fig8_period.png"))

	with open(os.path.join(output_dir, "sigma.json"), "w", encoding="utf-8") as handle:
		json.dump(records, handle, indent=2, ensure_ascii=False)
	return {"rows": rows, "records": records}


if __name__ == "__main__":
	from sensitivity._cli import run_as_script

	run_as_script("sigma", run, "4.4 转运时间波动敏感性")
