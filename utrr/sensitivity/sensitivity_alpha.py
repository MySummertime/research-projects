"""4.3 置信水平敏感性分析：α 对可行域、货场/服务类型选择与成本-风险的影响。

用法：
	python sensitivity/sensitivity_alpha.py
	python sensitivity/sensitivity_alpha.py --alpha 0.95 --data-source synthetic
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sensitivity.runner import base_instance, front_extremes, service_mix, yard_mix
from src.solvers.baselines import knee_point
from src.solvers.label_correcting import ParetoLabelSolver
from src.utils.paper_tables import write_table
from src.utils.plotting import Visualizer
from src.utils.reporting import path_text


def _min_cost_at(config, instance, logger, alpha: float):
	"""给定置信水平下的最小成本可行解（无可行解时返回 None）。"""
	local = config.with_overrides(alpha=float(alpha))
	front = ParetoLabelSolver(local, instance, logger).solve_pareto()["solutions"]
	if not front:
		return None
	return min(front, key=lambda item: item.cost)


def critical_alpha(config, instance, logger, low: float, high: float, threshold: float) -> float:
	"""二分定位最小成本方案发生切换的临界置信水平 α*。

	α 升高会压缩可行域：区间 [low, high] 内最小成本由 threshold 以下跳到以上，
	二分到 1e-3 精度即可满足表格与图形报数需要。
	"""
	lo, hi = float(low), float(high)
	for _ in range(18):
		mid = 0.5 * (lo + hi)
		solution = _min_cost_at(config, instance, logger, mid)
		if solution is None or solution.cost > threshold:
			hi = mid
		else:
			lo = mid
		if hi - lo < 0.0005:
			break
	return 0.5 * (lo + hi)


def run(config, output_dir: str, logger, instance=None) -> dict:
	instance = instance or base_instance(config)
	rows = []
	records = []

	for alpha in config.alpha_grid:
		local = config.with_overrides(alpha=float(alpha))
		solver = ParetoLabelSolver(local, instance, logger)
		payload = solver.solve_pareto()
		front = payload["solutions"]
		extremes = front_extremes(front)
		cost_best = extremes["cost_optimal"]
		risk_best = extremes["risk_optimal"]
		if cost_best is None:
			logger.warning(f"α = {alpha:.2f} 无可行解")
			continue
		mix = service_mix(front)
		mix_text = "/".join(
			f"{config.service_name(code)}{share:.0%}" for code, share in sorted(mix.items())
		)
		# 折中解（前沿拐点）与 4.2 节"本文方案"取法一致，单独记录以便两节口径对齐
		knee = knee_point(front)
		logger.info(
			f"α = {alpha:.2f}：λ_α = {local.lambda_alpha():.4f}，前沿 {len(front)} 条，"
			f"最小成本 ¥{cost_best.cost:,.0f}（{cost_best.service_label(config)}，"
			f"{path_text(cost_best, instance)}），服务类型构成 {mix_text}"
		)
		if knee is not None:
			logger.info(
				f"  折中解：{knee.service_label(config)} "
				f"¥{knee.cost:,.0f}，风险 {knee.risk:.6f}，"
				f"可靠度 {knee.reliability(instance.deadline):.4f}"
			)
		rows.append(
			[
				f"{alpha:.2f}",
				f"{local.lambda_alpha():.4f}",
				cost_best.service_label(config),
				f"{cost_best.cost:.2f}",
				f"{cost_best.risk:.6f}",
				f"{cost_best.reliability(instance.deadline):.4f}",
				"/".join(cost_best.yards_used(instance.network)),
				f"{cost_best.equivalent_time():.2f}",
				len(front),
				f"{min(x.cost for x in front) / 1000:.1f}~{max(x.cost for x in front) / 1000:.1f}",
				path_text(cost_best, instance),
			]
		)
		records.append(
			{
				"alpha": float(alpha),
				"lambda_alpha": local.lambda_alpha(),
				"front_size": len(front),
				"cost": cost_best.cost,
				"risk": cost_best.risk,
				"reliability": cost_best.reliability(instance.deadline),
				"min_risk": risk_best.risk,
				"min_risk_cost": risk_best.cost,
				"knee_cost": knee.cost if knee else None,
				"knee_risk": knee.risk if knee else None,
				"knee_service": knee.service_label(config) if knee else "",
				"knee_reliability": knee.reliability(instance.deadline) if knee else None,
				"service_mix": mix,
				"yard_mix": yard_mix(front, instance),
				"path": path_text(cost_best, instance),
			}
		)

	write_table(
		os.path.join(output_dir, "表6_置信水平敏感性.csv"),
		["α", "可靠性价格系数", "服务类型", "总成本/元", "总风险", "可靠度",
		 "选中货场", "等价时间/h", "前沿解数", "前沿成本区间/千元", "路径"],
		rows,
		title="表 6  不同置信水平下的最小成本可行解",
	)

	# 临界置信水平：最小成本方案的切换点，二分定位后写入 json 与图 6
	critical = None
	costs = [record["cost"] for record in records]
	switch = [i for i in range(1, len(costs)) if abs(costs[i] - costs[i - 1]) > 1e-6]
	if switch:
		index = switch[0]
		critical = critical_alpha(
			config,
			instance,
			logger,
			records[index - 1]["alpha"],
			records[index]["alpha"],
			0.5 * (costs[index - 1] + costs[index]),
		)
		logger.info(f"临界置信水平 α* = {critical:.4f}（最小成本方案在此由低价方案切换为高价方案）")

	# 图 6 用密集扫描画阶跃曲线：α 每 0.01 一档，成本与对应风险同图给出
	low, high, steps = config.alpha_sweep
	sweep = []
	for index in range(int(steps)):
		value = low + (high - low) * index / (int(steps) - 1)
		solution = _min_cost_at(config, instance, logger, value)
		if solution is None:
			sweep.append({"alpha": value, "cost": None, "risk": None})
			continue
		sweep.append(
			{
				"alpha": value,
				"cost": solution.cost,
				"risk": solution.risk,
				"service_name": config.service_name(solution.service),
			}
		)

	visualizer = Visualizer(config)
	visualizer.plot_alpha(
		records, os.path.join(output_dir, "fig7_alpha.png"), critical=critical, sweep=sweep
	)

	with open(os.path.join(output_dir, "alpha.json"), "w", encoding="utf-8") as handle:
		json.dump(
			{"records": records, "critical_alpha": critical, "sweep": sweep},
			handle,
			indent=2,
			ensure_ascii=False,
		)
	return {"rows": rows, "records": records, "critical_alpha": critical, "sweep": sweep}


if __name__ == "__main__":
	from sensitivity._cli import run_as_script

	run_as_script("alpha", run, "4.3 置信水平敏感性分析")
