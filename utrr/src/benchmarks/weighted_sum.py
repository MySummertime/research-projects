# -*- coding: utf-8 -*-
"""加权和法（Weighted-Sum, WST）外部基准——独立实现的精确标量化求解器。

对 (风险, 成本) 施加权重 w ∈ [0,1]，把双目标标量化为单目标

	min  (1-w)·成本 + w·风险     s.t.  等价时间 Tα ≤ D

以资源约束最短路（资源 = Tα）的标号设置法逐权重求解：每个节点维护
(Tα, 标量化目标) 上互不支配的标号集（按目标值排序 + 前缀最小时间，二分
判定支配），按目标值出堆扩展；目标增量非负，首次弹出终点即该权重下的
最优可行解。全部权重的输出并集为该方法的近似前沿。

固有局限：加权和只能取到 Pareto 前沿凸包上的点（supported solutions），
非凸段必然缺失。此为该经典方法的性质而非实现缺陷，用于对比本文算法的
完整前沿覆盖能力。
"""
from __future__ import annotations

import bisect
import heapq
import time

from src.core.network import ARC_TRANSFER

TOL = 1e-9


class _Bucket:
	"""按目标值排序的标号集；前缀最小时间支持 O(log n) 支配判定。"""

	__slots__ = ("objs", "times", "labels", "mins")

	def __init__(self):
		self.objs: list = []
		self.times: list = []
		self.labels: list = []
		self.mins: list = []

	def dominated(self, obj: float, t: float) -> bool:
		k = bisect.bisect_right(self.objs, obj + TOL)
		return k > 0 and self.mins[k - 1] <= t + TOL

	def insert(self, obj: float, t: float, label) -> None:
		p = bisect.bisect_left(self.objs, obj)
		self.objs.insert(p, obj)
		self.times.insert(p, t)
		self.labels.insert(p, label)
		prev = self.mins[p - 1] if p > 0 else float("inf")
		self.mins.insert(p, min(prev, t))
		for i in range(p + 1, len(self.times)):
			self.mins[i] = min(self.mins[i], self.mins[i - 1])


def _arc_contributions(net, arc, lam: float, covered: float, config):
	"""返回 (成本增量, 风险增量, Tα 增量, 累计铁路运距)。

	铁路成本按式（5）边际增量法：首条铁路弧含固定费率 b，其后为变动费率；
	公路、转运弧的成本即弧属性。转运弧的旅行时间记在货场 μ/σ 上。
	"""
	if arc.kind == ARC_TRANSFER:
		yard = net.yards[net.nodes[arc.i].yard]
		talpha = yard.mu + lam * yard.sigma
		cost = arc.cost
	elif arc.is_rail:
		talpha = arc.travel_time
		eta = config.service_type(arc.service).eta
		cost = net.tariff.segment_cost(
			covered, arc.distance, eta, config.q * config.hazmat_cost_factor
		)
	else:
		talpha = arc.travel_time
		cost = arc.cost
	return cost, arc.risk, talpha, covered + (arc.distance if arc.is_rail else 0.0)


def _min_tail_times(net, config, lam: float) -> dict:
	"""自各节点到终点的最小 Tα 尾程（资源可行性下界，反向 Dijkstra）。"""
	import heapq as _hq
	dist = {node: float("inf") for node in net.nodes}
	dist[net.destination] = 0.0
	heap = [(0.0, net.destination)]
	while heap:
		d, node = _hq.heappop(heap)
		if d > dist[node]:
			continue
		for arc in net.in_arcs.get(node, []):
			_, _, step_t, _ = _arc_contributions(net, arc, lam, 1.0, config)
			nd = d + step_t
			if nd < dist[arc.i] - TOL:
				dist[arc.i] = nd
				_hq.heappush(heap, (nd, arc.i))
	return dist


def solve_weighted_sum(instance, config, weights=None) -> dict:
	"""对给定权重集合求解标量化问题，返回近似前沿与统计。"""
	weights = tuple(weights) if weights is not None else tuple(config.sweep_weights)
	lam = config.lambda_alpha()
	deadline = instance.deadline
	net = instance.network
	min_tail = _min_tail_times(net, config, lam)

	started = time.perf_counter()
	points: dict = {}
	num_expanded = 0
	for w in weights:
		root = {"obj": 0.0, "t": 0.0, "covered": 0.0, "svc": -1,
				"node": net.origin, "parent": None, "arc": None}
		buckets: dict = {node: _Bucket() for node in net.nodes}
		buckets[net.origin].insert(0.0, 0.0, root)
		seq = 0
		heap: list = [(0.0, 0.0, seq, net.origin, root)]
		best_dest = None
		while heap:
			obj, talpha, _seq, node, label = heapq.heappop(heap)
			num_expanded += 1
			if node == net.destination:
				# 目标增量非负、堆按目标序：首次弹出终点即该权重下的最优可行解
				best_dest = label
				break
			for arc in net.out_arcs.get(node, []):
				# 服务连续性：换乘服务类型只能在货场转运后进行（与式（5）口径一致）
				svc = label["svc"]
				if arc.is_rail and svc >= 0 and svc != arc.service:
					continue
				step_cost, step_risk, step_t, covered = _arc_contributions(
					net, arc, lam, label["covered"], config
				)
				step_obj = (1.0 - w) * step_cost + w * step_risk
				n_obj, n_t = obj + step_obj, talpha + step_t
				if n_t > deadline + config.tolerance:
					continue
				if n_t + min_tail.get(arc.j, float("inf")) > deadline + config.tolerance:
					continue
				bucket = buckets[arc.j]
				if bucket.dominated(n_obj, n_t):
					continue
				child = {"obj": n_obj, "t": n_t, "covered": covered,
						 "svc": (-1 if arc.kind == ARC_TRANSFER else
								 (arc.service if arc.is_rail else svc)),
						 "node": arc.j, "parent": label, "arc": arc}
				bucket.insert(n_obj, n_t, child)
				seq += 1
				heapq.heappush(heap, (n_obj, n_t, seq, arc.j, child))
		if best_dest is None:
			continue
		# 父指针回溯，逐弧核算 (成本, 风险, Tα)
		arcs = []
		cursor = best_dest
		while cursor["arc"] is not None:
			arcs.append(cursor["arc"])
			cursor = cursor["parent"]
		arcs.reverse()
		cost = risk = 0.0
		covered = 0.0
		for arc in arcs:
			step_cost, step_risk, _, covered = _arc_contributions(net, arc, lam, covered, config)
			cost += step_cost
			risk += step_risk
		talpha = best_dest["t"]
		key = (round(cost, 4), round(risk, 6))
		points[key] = {
			"cost": cost,
			"risk": risk,
			"equivalent_time": talpha,
			"weight": w,
			"path": [arcs[0].i] + [a.j for a in arcs],
		}
	wall_time = time.perf_counter() - started
	ordered = sorted(points.values(), key=lambda p: p["risk"])
	return {
		"algorithm": "weighted_sum",
		"points": ordered,
		"num_points": len(ordered),
		"weights": list(weights),
		"labels_expanded": num_expanded,
		"wall_time": wall_time,
	}
