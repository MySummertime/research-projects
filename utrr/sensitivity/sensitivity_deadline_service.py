"""4.6 运到时限严格度与铁路服务类型分析。

三档时限（相对基准 D）：严格 1.0×、中等 1.2×、宽松 1.5×。对每档求 Pareto 前沿，
统计服务类型构成、铁路运距、分档线性费率成本和可靠度。

用法：
	python sensitivity/sensitivity_deadline_service.py
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sensitivity.runner import base_instance, front_extremes, scaled_instance, service_mix
from src.core.tariff import DecreasingTariff
from src.solvers.label_correcting import ParetoLabelSolver
from src.utils.paper_tables import write_table
from src.utils.plotting import Visualizer
from src.utils.reporting import path_text

DEADLINE_LABELS = {1.0: "严格", 1.2: "中等", 1.5: "宽松"}
LINEAR_REFERENCE_KM = 300.0  # 线性费率假设的参考短途运距


def linear_tariff_cost(solution, config) -> float:
	"""按短途平均费率线性外推的铁路成本。

	线性假设下不体现递远递减：以 300 km 处的平均单位运费 f(300)/300 作为全程
	费率。距离越长，该假设对铁路成本的高估越明显。
	"""
	tariff = DecreasingTariff(config)
	reference_rate = tariff.fare_per_ton(LINEAR_REFERENCE_KM) / LINEAR_REFERENCE_KM
	eta = solution.mean_eta(config)
	return eta * reference_rate * solution.dist * config.q


def run(config, output_dir: str, logger, instance=None) -> dict:
	base = instance or base_instance(config)
	base_deadline = base.deadline
	rows = []
	records = []

	for scale in config.deadline_scale_grid:
		deadline = base_deadline * scale
		derived = scaled_instance(base, config, deadline=deadline)
		solver = ParetoLabelSolver(config, derived, logger)
		payload = solver.solve_pareto()
		front = payload["solutions"]
		extremes = front_extremes(front)
		if extremes["cost_optimal"] is None:
			logger.warning(f"时限 {scale}× 基准：无可行解")
			continue
		cost_best = extremes["cost_optimal"]
		mix = service_mix(front)
		mix_text = "/".join(
			f"{config.service_name(code)}{share:.0%}" for code, share in sorted(mix.items())
		)
		rail_cost = cost_best.cost_breakdown(derived.network, config)["rail_cost"]
		logger.info(
			f"时限 {DEADLINE_LABELS.get(scale, scale)}（D={deadline:.2f} h，{scale}×）："
			f"前沿 {len(front)} 条，最小成本解 {cost_best.service_label(config)}，"
			f"铁路运距 {cost_best.dist:.1f} km，铁路成本 ¥{rail_cost:,.0f}；构成 {mix_text}"
		)
		rows.append(
			[
				DEADLINE_LABELS.get(scale, f"{scale}×"),
				f"{deadline:.2f}",
				cost_best.service_label(config),
				f"{cost_best.dist:.1f}",
				f"{rail_cost:.2f}",
				f"{cost_best.t0:.2f}",
				f"{cost_best.reliability(deadline):.4f}",
				f"{cost_best.cost:.2f}",
				len(front),
				f"{min(x.cost for x in front) / 1000:.1f}~{max(x.cost for x in front) / 1000:.1f}",
				path_text(cost_best, derived),
			]
		)
		records.append(
			{
				"label": DEADLINE_LABELS.get(scale, f"{scale}×"),
				"scale": float(scale),
				"deadline": deadline,
				"service_mix": mix,
				"front_size": len(front),
				"rail_distance": cost_best.dist,
				"rail_cost": rail_cost,
				"cost": cost_best.cost,
			}
		)

	write_table(
		os.path.join(output_dir, "表9_时限与服务类型.csv"),
		["时限档位", "运到时限/h", "服务类型", "铁路运距/km", "铁路成本/元",
		 "确定性时间/h", "M", "总成本/元", "前沿解数", "前沿成本区间/千元", "路径"],
		rows,
		title="表 9  运到时限严格度的影响",
	)

	# 各服务类型的"成本-时间"坐标（忽略运到时限时的最小成本方案），供图 9 使用
	points = []
	for code in config.service_codes:
		result = ParetoLabelSolver(config, base, logger).solve_scalar(
			"cost", lam=None, services=(code,)
		)
		if not result["solutions"]:
			continue
		candidate = result["solutions"][0]
		points.append(
			{
				"code": code,
				"label": candidate.service_label(config),
				"cost": candidate.cost,
				"equivalent_time": candidate.equivalent_time(),
				"dist": candidate.dist,
			}
		)
	points.sort(key=lambda item: item["equivalent_time"])
	logger.info(
		"服务类型成本-时间：" + "，".join(
			f"{item['label']} {item['equivalent_time']:.1f} h/¥{item['cost']:,.0f}" for item in points
		)
	)

	# 时限扫描：为图 9 提供"时限—最小可行成本"的阶跃曲线
	low, high, steps = config.deadline_sweep
	sweep = []
	for index in range(int(steps)):
		scale = low + (high - low) * index / (int(steps) - 1)
		deadline = base_deadline * scale
		if deadline < config.real_case_min_deadline_hours:
			sweep.append({"deadline": deadline, "cost": None, "label": "无可行解"})
			continue
		derived = scaled_instance(base, config, deadline=deadline)
		front = ParetoLabelSolver(config, derived, logger).solve_pareto()["solutions"]
		if not front:
			sweep.append({"deadline": deadline, "cost": None, "label": "无可行解"})
			continue
		best = min(front, key=lambda item: item.cost)
		sweep.append(
			{
				"deadline": deadline,
				"cost": best.cost,
				"label": best.service_label(config),
				"service": best.service,
				"service_name": config.service_name(best.service),
				"front_size": len(front),
			}
		)
	feasible = [item for item in sweep if item["cost"] is not None]
	if feasible:
		logger.info(
			f"时限扫描 {len(feasible)}/{len(sweep)} 个可行；"
			f"成本由 ¥{feasible[0]['cost']:,.0f}（D={feasible[0]['deadline']:.1f} h，"
			f"{feasible[0]['label']}）降至 ¥{feasible[-1]['cost']:,.0f}"
			f"（D={feasible[-1]['deadline']:.1f} h，{feasible[-1]['label']}）"
		)

	visualizer = Visualizer(config)
	visualizer.plot_deadline_service(
		records, points, os.path.join(output_dir, "fig10_deadline_service.png"), sweep=sweep
	)

	with open(os.path.join(output_dir, "deadline_service.json"), "w", encoding="utf-8") as handle:
		json.dump(
			{"rows": records, "service_points": points, "deadline_sweep": sweep},
			handle,
			indent=2,
			ensure_ascii=False,
		)
	return {"rows": rows, "records": records, "points": points, "sweep": sweep}


if __name__ == "__main__":
	from sensitivity._cli import run_as_script

	run_as_script("deadline_service", run, "4.6 运到时限严格度与服务类型")
