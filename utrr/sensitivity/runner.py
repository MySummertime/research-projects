"""敏感性实验的共享工具与调度表。"""

from __future__ import annotations

from config import UTRRConfig
from src.core.instance_builder import build_instance, derive_instance
from src.core.instance_generator import CaseInstance
from src.core.uncertainty import achieved_reliability
from src.solvers.label_correcting import Solution, pareto_filter


# ----------------------------------------------------------------------
# 算例
# ----------------------------------------------------------------------
def base_instance(config: UTRRConfig) -> CaseInstance:
	"""构造基准算例（数据来源由 config.data_source 决定）。"""
	return build_instance(config)


def scaled_instance(
	base: CaseInstance,
	config: UTRRConfig,
	*,
	deadline: float | None = None,
	sigma_scale: float = 1.0,
	node_risk_scale: float = 1.0,
	include_node_risk: bool | None = None,
) -> CaseInstance:
	"""在基准算例上派生算例（拓扑不变，仅改参数口径）。"""
	return derive_instance(
		base,
		config,
		deadline=deadline,
		sigma_scale=sigma_scale,
		node_risk_scale=node_risk_scale,
		include_node_risk=include_node_risk,
	)


# ----------------------------------------------------------------------
# 解的评价
# ----------------------------------------------------------------------
def path_sigma(solution: Solution, instance: CaseInstance) -> float:
	"""按算例当前货场参数重算路径的转运时间波动参数之和。"""
	total = 0.0
	for arc in solution.arcs:
		if arc.is_transfer:
			total += instance.network.yards[instance.network.nodes[arc.i].yard].sigma
	return total


def path_mu(solution: Solution, instance: CaseInstance) -> float:
	"""按算例当前货场参数重算路径的转运时间期望之和。"""
	total = 0.0
	for arc in solution.arcs:
		if arc.is_transfer:
			total += instance.network.yards[instance.network.nodes[arc.i].yard].mu
	return total


def true_reliability(solution: Solution, instance: CaseInstance, deadline: float) -> float:
	"""用算例当前（真实）货场参数评价路径的实际运到时限可靠度。"""
	sigma = path_sigma(solution, instance)
	mu = path_mu(solution, instance)
	return achieved_reliability(solution.t0, mu, sigma, deadline, solution.lam)


def front_extremes(front: list) -> dict:
	"""返回前沿上的最小成本解与最小风险解。"""
	if not front:
		return {"cost_optimal": None, "risk_optimal": None, "size": 0}
	filtered = pareto_filter(front)
	cost_optimal = min(filtered, key=lambda s: (s.cost, s.risk))
	risk_optimal = min(filtered, key=lambda s: (s.risk, s.cost))
	return {"cost_optimal": cost_optimal, "risk_optimal": risk_optimal, "size": len(filtered)}


def service_mix(front: list) -> dict:
	"""统计前沿中铁路运距在各服务类型上的分布。

	逐弧选择服务类型时一条路径可能混编多种列车等级，故按运距占比加权，
	而不是把每个解整条计到一个服务类型上。
	"""
	km = {}
	if not front:
		return {}
	for solution in front:
		for code, distance in solution.service_km.items():
			km[code] = km.get(code, 0.0) + distance
	total = sum(km.values())
	if total <= 0:
		return {}
	return {code: distance / total for code, distance in km.items()}


def yard_mix(front: list, instance: CaseInstance) -> dict:
	"""统计前沿解中首发货场的占比。"""
	mix = {}
	if not front:
		return mix
	for solution in front:
		yards = solution.yards_used(instance.network)
		name = yards[0] if yards else "-"
		mix[name] = mix.get(name, 0) + 1
	return {name: count / len(front) for name, count in mix.items()}


# ----------------------------------------------------------------------
# 调度表：实验名 → (模块, 说明)
# ----------------------------------------------------------------------
EXPERIMENTS = {
	"alpha": "sensitivity.sensitivity_alpha",
	"sigma": "sensitivity.sensitivity_sigma",
	"node_risk": "sensitivity.sensitivity_node_risk",
	"deadline_service": "sensitivity.sensitivity_deadline_service",
    "demand": "sensitivity.sensitivity_demand",
	"scalability": "sensitivity.sensitivity_scalability",
}


def run_named_experiment(name: str, config: UTRRConfig, output_dir: str, logger) -> dict:
	"""按名称运行单个敏感性实验，结果直接写入 output_dir（results/<实验名>_<时间戳>，平铺不嵌套）。"""
	import importlib
	import os

	if name not in EXPERIMENTS:
		raise KeyError(f"未知实验：{name}，可选 {sorted(EXPERIMENTS)}")
	module = importlib.import_module(EXPERIMENTS[name])
	os.makedirs(output_dir, exist_ok=True)
	return module.run(config, output_dir, logger, instance=build_instance(config))
