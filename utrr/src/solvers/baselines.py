"""对比方案与基线算法（论文 4.2 四类方案、4.7 启发式基线）。"""

from __future__ import annotations

from config import UTRRConfig
from src.core.instance_generator import CaseInstance
from src.solvers.label_correcting import ParetoLabelSolver, Solution, pareto_filter


# ----------------------------------------------------------------------
# 4.2 四类对比方案
# ----------------------------------------------------------------------
SCHEME_COST_MIN = "cost_min"
SCHEME_RISK_MIN = "risk_min"
SCHEME_DETERMINISTIC = "deterministic"
SCHEME_PROPOSED = "proposed"

SCHEME_LABELS = {
	SCHEME_COST_MIN: ("成本最小", "Cost minimum"),
	SCHEME_RISK_MIN: ("风险最小", "Risk minimum"),
	SCHEME_DETERMINISTIC: ("确定性时间", "Deterministic time"),
	SCHEME_PROPOSED: ("本文机会约束", "Chance-constrained"),
}


def solve_cost_min(config: UTRRConfig, instance: CaseInstance, logger=None) -> dict:
	"""方案 1：单目标成本最小，不施加运到时限约束。"""
	solver = ParetoLabelSolver(config, instance, logger)
	return solver.solve_scalar("cost", lam=None)


def solve_risk_min(config: UTRRConfig, instance: CaseInstance, logger=None) -> dict:
	"""方案 2：单目标风险最小，不施加运到时限约束。"""
	solver = ParetoLabelSolver(config, instance, logger)
	return solver.solve_scalar("risk", lam=None)


def solve_deterministic(config: UTRRConfig, instance: CaseInstance, logger=None) -> dict:
	"""方案 3：转运时间取期望值，运到时限作为硬约束 T0 + Σμ_i ≤ D。

	等价于取 λ_α = 0 的机会约束，即忽略转运时间波动、不给可靠性缓冲。
	"""
	solver = ParetoLabelSolver(config, instance, logger)
	return solver.solve_scalar("cost", lam=0.0)


def solve_proposed(config: UTRRConfig, instance: CaseInstance, logger=None) -> dict:
	"""方案 4：风险-成本双目标 + 机会约束 M{T̃ ≤ D} ≥ α。"""
	solver = ParetoLabelSolver(config, instance, logger)
	return solver.solve_pareto()


def solve_all_schemes(config: UTRRConfig, instance: CaseInstance, logger=None) -> dict:
	"""依次求解 4 类方案，返回每类方案的代表解与统计。"""
	results = {}
	for scheme, runner in (
		(SCHEME_COST_MIN, solve_cost_min),
		(SCHEME_RISK_MIN, solve_risk_min),
		(SCHEME_DETERMINISTIC, solve_deterministic),
		(SCHEME_PROPOSED, solve_proposed),
	):
		if logger is not None:
			logger.info(f"\n>>> 求解方案：{SCHEME_LABELS[scheme][0]}")
		payload = runner(config, instance, logger)
		solutions = payload.get("solutions", [])
		payload["scheme"] = scheme
		payload["representative"] = _representative(scheme, solutions)
		results[scheme] = payload
		if logger is not None:
			best = payload["representative"]
			if best is None:
				logger.warning("  无可行解")
			else:
				logger.info(
					f"  代表解：服务类型 {best.service_label(config)}，"
					f"成本 ¥{best.cost:,.2f}，风险 {best.risk:.6f}，"
					f"等价时间 {best.equivalent_time():.2f} h，"
					f"可靠度 {best.reliability(instance.deadline):.4f}"
				)
	return results


def _representative(scheme: str, solutions: list) -> Solution | None:
	"""为每类方案挑选一个代表解。

	- 成本最小 / 确定性时间 / 风险最小：即其单目标最优解；
	- 本文方案：取 Pareto 前沿的拐点（距两端点连线最远者），代表"风险-成本
	  边际交换率发生转折"的方案，避免以单一目标极值代表前沿。
	"""
	if not solutions:
		return None
	if scheme == SCHEME_PROPOSED:
		return knee_point(solutions)
	return solutions[0]


def knee_point(solutions: list) -> Solution | None:
	"""返回风险-成本前沿的拐点（到前沿两端点连线距离最大者）。"""
	if not solutions:
		return None
	front = pareto_filter(solutions)
	if len(front) <= 2:
		return front[len(front) // 2] if front else None
	first, last = front[0], front[-1]
	span_risk = last.risk - first.risk
	span_cost = first.cost - last.cost
	norm = (span_risk**2 + span_cost**2) ** 0.5
	if norm <= 1e-12:
		return front[len(front) // 2]
	best, best_distance = front[0], -1.0
	for solution in front:
		# 点到两端点连线的距离（归一化），取最大者
		residual = span_cost * (solution.risk - first.risk) + span_risk * (
			solution.cost - first.cost
		)
		distance = abs(residual) / norm
		if distance > best_distance:
			best, best_distance = solution, distance
	return best


# ----------------------------------------------------------------------
# 4.7 加权和启发式基线
# ----------------------------------------------------------------------
def solve_weighted_sum_sweep(config: UTRRConfig, exact_front: list) -> dict:
	"""加权和标量化启发式：以精确前沿上的支持解（supported solutions）为输出。

	对权重 w ∈ [0, 1] 逐点最小化 w·R̂ + (1−w)·Ĉ，只能取到 Pareto 前沿凸包上的
	点；前沿非凸段的解必然遗漏。该基线用于量化启发式解质量的损失。
	"""
	supported: dict = {}
	for weight in config.sweep_weights:
		best, best_value = None, float("inf")
		for solution in exact_front:
			value = weight * solution.risk_n + (1.0 - weight) * solution.cost_n
			if value < best_value - 1e-12:
				best, best_value = solution, value
		if best is not None:
			supported[best.signature()] = best
	approx = pareto_filter(list(supported.values()))
	return {
		"solutions": approx,
		"weights": list(config.sweep_weights),
		"num_supported": len(approx),
		"num_exact": len(exact_front),
		"coverage": (len(approx) / len(exact_front)) if exact_front else 0.0,
	}


def normalize_front(front: list) -> None:
	"""为前沿解附加归一化坐标（risk_n, cost_n），供加权和与超体积计算使用。"""
	if not front:
		return
	risk = [s.risk for s in front]
	cost = [s.cost for s in front]
	r_lo, r_hi = min(risk), max(risk)
	c_lo, c_hi = min(cost), max(cost)
	span_r = (r_hi - r_lo) or 1.0
	span_c = (c_hi - c_lo) or 1.0
	for solution in front:
		solution.risk_n = (solution.risk - r_lo) / span_r
		solution.cost_n = (solution.cost - c_lo) / span_c


def hypervolume_2d(front: list, ref_risk: float, ref_cost: float) -> float:
	"""二维超体积（最小化口径，参考点为 (ref_risk, ref_cost)）。"""
	if not front:
		return 0.0
	points = sorted((s.risk, s.cost) for s in front if s.risk <= ref_risk and s.cost <= ref_cost)
	volume = 0.0
	prev_cost = ref_cost
	for risk, cost in points:
		if cost < prev_cost:
			volume += (ref_risk - risk) * (prev_cost - cost)
			prev_cost = cost
	return volume


def front_quality_gap(exact: list, approx: list) -> float:
	"""近似前沿相对精确前沿的最大归一化差距（越大表示启发式解质量越差）。"""
	if not exact or not approx:
		return 1.0
	normalize_front(exact + approx)
	worst = 0.0
	for solution in exact:
		closest = min(
			((solution.risk_n - other.risk_n) ** 2 + (solution.cost_n - other.cost_n) ** 2) ** 0.5
			for other in approx
		)
		worst = max(worst, closest)
	return worst
