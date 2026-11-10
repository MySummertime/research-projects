"""控制台报告与表格文本生成。"""

from __future__ import annotations

from config import UTRRConfig
from src.core.instance_generator import CaseInstance
from src.solvers.baselines import SCHEME_LABELS
from src.solvers.label_correcting import Solution
from src.utils.numeric_format import (
	format_number,
	format_reliability,
)


def path_text(solution: Solution, instance: CaseInstance) -> str:
	"""把路径渲染为 o→Y1→吐鲁番→…→d 的站点序列（货场以入/出合并显示）。

	挂接货场的车站按"到达侧/出发侧"拆成了两个节点（_a / _b），展示时合并为
	一个站名，避免同一车站出现两次。
	"""
	sequence = solution.node_sequence()
	display = []
	for node in sequence:
		info = instance.network.nodes[node]
		if info.layer == "yard" and info.yard:
			token = info.yard
		elif info.layer == "client":
			token = "o" if node == instance.network.origin else "d"
		else:
			token = info.name or (node[:-2] if node.endswith(("_a", "_b")) else node)
		if display and display[-1] == token:
			continue
		display.append(token)
	return "→".join(display)


def route_station_text(solution: Solution, instance: CaseInstance) -> str:
	"""把路径渲染为"车站→线路名（沿途车站）→…→车站"，供表5“完整路径”列使用。

	依次展示途经的所有车站名与线路名；括号内为在该线路上到达的车站，
	起讫车站单列于首尾箭头之外。
	示例：奎屯→兰新线（宝鸡，兰州）→淮海线（南京，苏州）→上海
	"""
	network = instance.network

	def sname(node: str) -> str:
		info = network.nodes[node]
		if info.name:
			return info.name
		return node[:-2] if node.endswith(("_a", "_b")) else node

	entries = []
	for arc in solution.arcs:
		if arc.is_transfer or arc.is_road:
			continue
		entries.append((arc.line or "铁路", sname(arc.j)))
	if not entries:
		return ""
	start = sname(solution.arcs[0].i) if solution.arcs else ""
	for arc in solution.arcs:
		if not (arc.is_transfer or arc.is_road):
			start = sname(arc.i)
			break
	end = entries[-1][1]
	legs = []  # [线路, [到达站...]]
	for line, j in entries:
		if not legs or legs[-1][0] != line:
			legs.append((line, []))
		if not legs[-1][1] or legs[-1][1][-1] != j:
			legs[-1][1].append(j)
	if legs[-1][1] and legs[-1][1][-1] == end:
		legs[-1][1].pop()
	parts = [start]
	for line, stations in legs:
		parts.append(f"{line}（{'，'.join(stations)}）" if stations else line)
	parts.append(end)
	return "→".join(parts)


def route_text(solution: Solution, instance: CaseInstance, config: UTRRConfig) -> str:
	"""把路径概括为"通道 + 班列等级"的形式，供表格使用。

	示例：o→Y1→〔兰新线/快速班列 1 892 km〕→Y8→〔陇海线+宁西线/集装箱班列 1 752 km〕
	      →Y16→d

	逐弧选择服务类型时一条路径可能混编，因此按"连续同等级"分段，段内列出途经
	线路并汇总里程。
	"""
	parts = ["o"]
	segment = None  # [服务类型, 线路列表, 里程]

	def flush():
		nonlocal segment
		if segment is None:
			return
		code, lines, distance = segment
		parts.append(f"〔{'+'.join(lines)}/{config.service_name(code)} {distance:,.0f} km〕")
		segment = None

	for arc in solution.arcs:
		if arc.is_transfer:
			flush()
			parts.append(instance.network.nodes[arc.i].yard)
		elif arc.is_road:
			if arc.distance <= 0.0:
				continue
			flush()
			if parts[-1] != "公路":
				parts.append("公路")
		else:
			code = arc.service if arc.service is not None else -1
			if segment is not None and segment[0] == code:
				if arc.line and arc.line not in segment[1]:
					segment[1].append(arc.line)
				segment[2] += arc.distance
			else:
				flush()
				segment = [code, [arc.line] if arc.line else ["铁路"], arc.distance]
	flush()
	parts.append("d")
	return "→".join(parts)


def mode_text(solution: Solution, instance: CaseInstance) -> str:
	"""把路径渲染为运输方式序列，如 公路→铁路→公路。"""
	segments = []
	for arc in solution.arcs:
		if arc.is_road and arc.distance <= 0.0:
			continue  # 站内连接弧不计入运输方式序列
		label = {"road": "公路", "rail": "铁路", "transfer": "转运"}[arc.kind]
		if not segments or segments[-1] != label:
			segments.append(label)
	return "→".join(segments)


def solution_line(solution: Solution, instance: CaseInstance, config: UTRRConfig) -> str:
	"""单行摘要，用于日志与表格。"""
	return (
		f"{solution.service_label(config)} | "
		f"¥{solution.cost:>12,.2f} | R={solution.risk:.6f} | "
		f"T0={solution.t0:.2f} μ={solution.mu:.2f} σ={solution.sigma:.2f} | "
		f"Tα={solution.equivalent_time():.2f} h | "
		f"M={format_reliability(solution.reliability(instance.deadline))} | "
		f"{path_text(solution, instance)}"
	)


def format_pareto_report(payload: dict, instance: CaseInstance, config: UTRRConfig) -> str:
	"""Pareto 解集报告。"""
	lines = []
	lines.append("=" * 78)
	lines.append("风险-成本 Pareto 最优路径集")
	lines.append("=" * 78)
	front = payload.get("solutions", [])
	lines.append(
		f"置信水平 α = {config.alpha:.2f}（λ_α = {payload.get('lambda_alpha', 0):.4f}，"
		f"{config.confidence_mode} 口径），运到时限 D = {instance.deadline:.2f} h"
	)
	lines.append(f"前沿规模：{len(front)}")
	lines.append("")
	lines.append(
		f"{'#':>3} {'服务类型':<8} {'成本/元':>13} {'风险':>11} {'T0/h':>7} "
		f"{'μ/h':>6} {'σ/h':>5} {'Tα/h':>7} {'M':>7} {'铁路/km':>8}  路径"
	)
	lines.append("-" * 78)
	for index, solution in enumerate(front, start=1):
		lines.append(
			f"{index:>3} {solution.service_label(config):<8} "
			f"{solution.cost:>13,.2f} {solution.risk:>11.6f} {solution.t0:>7.2f} "
			f"{solution.mu:>6.2f} {solution.sigma:>5.2f} {solution.equivalent_time():>7.2f} "
			f"{format_reliability(solution.reliability(instance.deadline)):>7} "
			f"{solution.dist:>8.1f}  {path_text(solution, instance)}"
		)
	lines.append("=" * 78)

	stats = payload.get("stats", [])
	if stats:
		lines.append("")
		lines.append("算法统计（按服务类型）")
		lines.append(
			f"{'服务类型':<8} {'生成标号':>9} {'扩展':>8} {'支配剪枝':>9} "
			f"{'机会剪枝':>9} {'下界剪枝':>9} {'剪枝率':>7} {'峰值/节点':>9} {'耗时/s':>8}"
		)
		for row in stats:
			lines.append(
				f"{config.service_name(row['service']):<8} "
				f"{row['labels_generated']:>9} {row['labels_expanded']:>8} "
				f"{row['labels_dominated']:>9} {row['labels_chance_pruned']:>9} "
				f"{row['labels_bounds_pruned']:>9} {row['prune_rate']:>7.1%} "
				f"{row['peak_labels_per_node']:>9} {row['wall_time']:>8.3f}"
			)
	lines.append(f"总耗时：{payload.get('wall_time', 0):.3f} s")
	return "\n".join(lines)


def format_scheme_report(schemes: dict, instance: CaseInstance, config: UTRRConfig) -> str:
	"""四类对比方案报告（对应论文表 2）。"""
	lines = []
	lines.append("=" * 78)
	lines.append("四类方案指标对比")
	lines.append("=" * 78)
	header = (
		f"{'方案':<12} {'服务类型':<8} {'总成本/元':>13} {'总风险':>11} "
		f"{'弧段风险':>10} {'节点风险':>10} {'M':>7} {'是否满足D':>9}"
	)
	lines.append(header)
	lines.append("-" * 78)
	for scheme, payload in schemes.items():
		solution = payload.get("representative")
		name_cn = SCHEME_LABELS[scheme][0]
		if solution is None:
			lines.append(f"{name_cn:<12} 无可行解")
			continue
		risks = solution.risk_breakdown()
		reliability = solution.reliability(instance.deadline)
		lines.append(
			f"{name_cn:<12} {solution.service_label(config):<8} "
			f"{solution.cost:>13,.2f} {solution.risk:>11.6f} "
			f"{risks['arc_risk']:>10.6f} {risks['node_risk']:>10.6f} "
			f"{format_reliability(reliability):>7} "
			f"{'是' if reliability >= config.alpha - 1e-9 else '否':>9}"
		)
	lines.append("-" * 78)
	for scheme, payload in schemes.items():
		solution = payload.get("representative")
		if solution is None:
			continue
		lines.append(
			f"  {SCHEME_LABELS[scheme][0]:<10} 路径：{path_text(solution, instance)}"
			f"（{mode_text(solution, instance)}）"
		)
	lines.append("=" * 78)
	return "\n".join(lines)


def format_instance_report(instance: CaseInstance) -> str:
	"""算例概况报告。"""
	net = instance.network
	counts = net.counts()
	lines = [
		"=" * 78,
		f"算例：{instance.metadata.get('description', instance.name)}",
		"=" * 78,
		f"节点总数 {counts['num_nodes']}（客户 {counts['num_client_nodes']}，公路 "
		f"{counts['num_road_nodes']}，转运 {counts['num_yard_nodes']}，铁路 {counts['num_rail_nodes']}）",
		f"弧总数 {counts['num_arcs']}（公路 {counts['num_road_arcs']}，铁路 "
		f"{counts['num_rail_arcs']}，转运 {counts['num_transfer_arcs']}）",
		f"货场 {counts['num_yards']} 个，运到时限 D = {instance.deadline:.3f} h，"
		f"最小可能时间 = {instance.metadata.get('min_equivalent_time_hours', 0):.3f} h",
		"",
		"货场转运参数：",
		f"{'货场':<6}{'资质':<6}{'μ/h':>7}{'σ/h':>7}{'转运成本/元':>13}{'节点风险':>12}",
	]
	for yard in net.yards.values():
		lines.append(
			f"{yard.name:<6}{'具备' if yard.qualified else '不具备':<6}{yard.mu:>7.2f}{yard.sigma:>7.2f}"
			f"{yard.transfer_cost(net.config.q):>13,.2f}"
			f"{yard.node_risk(net.config.q, net.config.node_risk_theta, net.config.node_risk_rho, net.config.hazmat_risk_factor):>12.6f}"
		)
	lines.append("=" * 78)
	return "\n".join(lines)
