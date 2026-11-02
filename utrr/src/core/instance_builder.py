"""算例装配与派生：所有实验获取 CaseInstance 的唯一入口。

	build_instance(config)      按 data_source 从真实路网 JSON 或合成生成器构造算例
	derive_instance(base, ...)  在既有算例上叠加参数扰动（波动、节点风险口径、时限），
	                            保证敏感性实验只改变一个因素、拓扑完全一致
"""

from __future__ import annotations

from dataclasses import replace

from config import DATA_SOURCE_REAL, DATA_SOURCE_SYNTHETIC, UTRRConfig
from src.core.instance_generator import CaseInstance, InstanceGenerator, load_instance
from src.core.real_case import load_real_case


def build_instance(config: UTRRConfig) -> CaseInstance:
	"""按配置构造基准算例（优先使用显式指定的算例文件）。"""
	if config.instance_file:
		return load_instance(config.instance_file, config)
	if config.data_source == DATA_SOURCE_REAL:
		return load_real_case(config)
	if config.data_source == DATA_SOURCE_SYNTHETIC:
		return InstanceGenerator(config).build()
	raise ValueError(f"未知的数据来源：{config.data_source}")


def derive_instance(
	base: CaseInstance,
	config: UTRRConfig | None = None,
	*,
	deadline: float | None = None,
	sigma_scale: float = 1.0,
	node_risk_scale: float = 1.0,
	include_node_risk: bool | None = None,
) -> CaseInstance:
	"""在基准算例上派生新算例。

	sigma_scale      货场转运时间波动参数的整体缩放（0 即"按期望值决策"的确定型模型）
	node_risk_scale  θ、ρ 耦合系数相对基准的缩放
	include_node_risk 是否计入节点转运风险（覆盖基准配置）
	deadline         新的运到时限；缺省沿用基准值
	"""
	cfg = config or base.network.config
	src = base.network.config

	yards = {
		name: replace(yard, sigma=yard.sigma * sigma_scale) for name, yard in base.network.yards.items()
	}
	include = src.include_node_risk if include_node_risk is None else include_node_risk
	theta = src.node_risk_theta * node_risk_scale
	rho = src.node_risk_rho * node_risk_scale

	arcs = []
	for arc in base.network.arcs:
		if not arc.is_transfer:
			arcs.append(arc)
			continue
		yard = yards[base.network.nodes[arc.i].yard]
		arcs.append(
			replace(
				arc,
				risk=(
					yard.node_risk(src.q, theta, rho, src.hazmat_risk_factor) if include else 0.0
				),
				cost=round(yard.transfer_cost(src.q), 2),
			)
		)

	net = base.network.clone(config=cfg, yards=yards, arcs=arcs)
	return CaseInstance(
		network=net,
		deadline=base.deadline if deadline is None else float(deadline),
		alpha=base.alpha,
		name=base.name,
		metadata=dict(base.metadata),
	)
