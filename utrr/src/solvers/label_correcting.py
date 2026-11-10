"""双向多维标号修正算法（论文第 3 节，式（12）—（14））。

标号 L_i = (i, R, C, T0, μ, σ, d, S, P)：
	R  累计风险，C 累计成本，T0 累计确定性时间，
	μ/σ 累计转运时间期望值与波动参数，d 累计铁路运距，
	S/P 由标号链隐式承担（逐弧记录，回溯得到）。

机会约束时间 T_α = T0 + μ + λ_α·σ，作为支配维度与剪枝依据。
"""

from __future__ import annotations

import bisect
import time
from dataclasses import dataclass, field

from config import UTRRConfig
from src.core.instance_generator import CaseInstance
from src.core.network import ARC_RAIL, FourLayerNetwork
from src.core.uncertainty import achieved_reliability, equivalent_time

INF = float("inf")

# 服务类型编码的哨兵值：-1 表示逐弧选择（一条路径可混编多种服务类型）
SERVICE_ANY = -1


# ----------------------------------------------------------------------
# 数据结构
# ----------------------------------------------------------------------
@dataclass(slots=True)
class Label:
	"""多维标号。"""

	node: str
	risk: float
	cost: float
	t0: float
	mu: float
	sigma: float
	dist: float
	service: int
	parent: "Label | None" = None
	arc: object | None = None  # 生成该标号所用的弧
	depth: int = 0

	def equivalent_time(self, lam: float) -> float:
		return equivalent_time(self.t0, self.mu, self.sigma, lam)

	def nodes_along(self) -> list:
		"""返回从标号回溯得到的节点序列（不含方向含义）。"""
		chain = []
		cursor = self
		while cursor is not None:
			chain.append(cursor.node)
			cursor = cursor.parent
		return chain


@dataclass
class SearchStats:
	"""求解过程统计（用于 4.7 剪枝效率分析）。"""

	service: int = 0
	direction: str = "bidirectional"
	labels_generated: int = 0
	labels_expanded: int = 0
	labels_dominated: int = 0
	labels_chance_pruned: int = 0
	labels_bounds_pruned: int = 0
	labels_kept: int = 0
	peak_labels_per_node: int = 0
	truncated: bool = False
	wall_time: float = 0.0
	prune_rate: float = 0.0

	def as_dict(self) -> dict:
		return {
			"service": self.service,
			"direction": self.direction,
			"labels_generated": self.labels_generated,
			"labels_expanded": self.labels_expanded,
			"labels_dominated": self.labels_dominated,
			"labels_chance_pruned": self.labels_chance_pruned,
			"labels_bounds_pruned": self.labels_bounds_pruned,
			"labels_kept": self.labels_kept,
			"peak_labels_per_node": self.peak_labels_per_node,
			"truncated": self.truncated,
			"wall_time": round(self.wall_time, 6),
			"prune_rate": round(self.prune_rate, 6),
		}


class ParetoFront:
	"""风险-成本非支配前沿，支持 O(log n) 的左下支配查询（用于下界剪枝）。"""

	def __init__(self, tolerance: float = 1e-9):
		self.tolerance = tolerance
		self._risk: list[float] = []
		self._cost: list[float] = []

	def add(self, risk: float, cost: float) -> None:
		"""加入一个可行解；若被现有前沿支配则忽略。"""
		index = bisect.bisect_right(self._risk, risk + self.tolerance) - 1
		if index >= 0 and self._cost[index] <= cost + self.tolerance:
			return
		# 删除被新点支配的右侧点
		remove_from = bisect.bisect_right(self._risk, risk + self.tolerance)
		remove_to = remove_from
		while remove_to < len(self._risk) and self._cost[remove_to] >= cost - self.tolerance:
			remove_to += 1
		insert_at = bisect.bisect_left(self._risk, risk - self.tolerance)
		del self._risk[insert_at:remove_to]
		del self._cost[insert_at:remove_to]
		self._risk.insert(insert_at, risk)
		self._cost.insert(insert_at, cost)

	def dominates_lower_left(self, risk_bound: float, cost_bound: float) -> bool:
		"""若存在 (R_s, C_s) 使 R_s ≤ risk_bound 且 C_s ≤ cost_bound，返回 True。

		此时任何以 (risk_bound, cost_bound) 为下界继续扩展的路径都必然被该解支配，
		可安全剪枝。
		"""
		index = bisect.bisect_right(self._risk, risk_bound + self.tolerance) - 1
		return index >= 0 and self._cost[index] <= cost_bound + self.tolerance

	def as_list(self) -> list:
		return [(r, c) for r, c in zip(self._risk, self._cost)]

	def __len__(self) -> int:
		return len(self._risk)


@dataclass
class Solution:
	"""完整路径解。"""

	arcs: tuple
	service: int
	risk: float
	cost: float
	t0: float
	mu: float
	sigma: float
	dist: float
	lam: float
	risk_n: float = 0.0  # 归一化风险（绘图与加权和使用）
	cost_n: float = 0.0  # 归一化成本
	# 各服务类型的铁路运距（km）：逐弧选择服务类型时一条路径可能混编多种服务
	service_km: dict = field(default_factory=dict)

	# ---------------- 派生指标 ----------------
	def service_shares(self) -> dict:
		"""各服务类型的铁路运距占比。"""
		total = sum(self.service_km.values())
		if total <= 0:
			return {}
		return {code: km / total for code, km in self.service_km.items() if km > 0}

	def service_label(self, config: UTRRConfig) -> str:
		"""服务类型的中文描述：单一类型直接取名，混编按运距占比降序拼接。"""
		shares = self.service_shares()
		if not shares:
			return config.service_name(self.service)
		ordered = sorted(shares.items(), key=lambda item: -item[1])
		if len(ordered) == 1:
			return config.service_name(ordered[0][0])
		return "＋".join(config.service_name(code) for code, _ in ordered)

	def mean_eta(self, config: UTRRConfig) -> float:
		"""按铁路运距占比加权的服务类型修正系数（用于线性费率对比等折算）。"""
		shares = self.service_shares()
		if not shares:
			return config.service_type(self.service).eta if self.service >= 0 else 1.0
		return sum(shares[code] * config.service_type(code).eta for code in shares)

	# ---------------- 派生指标 ----------------
	def equivalent_time(self) -> float:
		return equivalent_time(self.t0, self.mu, self.sigma, self.lam)

	def reliability(self, deadline: float) -> float:
		return achieved_reliability(self.t0, self.mu, self.sigma, deadline, self.lam)

	def node_sequence(self) -> list:
		if not self.arcs:
			return []
		sequence = [self.arcs[0].i]
		for arc in self.arcs:
			sequence.append(arc.j)
		return sequence

	def signature(self) -> tuple:
		return tuple((arc.i, arc.j, arc.service) for arc in self.arcs)

	def yards_used(self, network: FourLayerNetwork) -> list:
		"""返回途经货场（按途经顺序）。"""
		yards = []
		for arc in self.arcs:
			if arc.is_transfer:
				name = network.nodes[arc.i].yard
				if name not in yards:
					yards.append(name)
		return yards

	def cost_breakdown(self, network: FourLayerNetwork, config: UTRRConfig) -> dict:
		"""按公路/铁路/货场拆解成本，铁路成本按式（5）逐弧重算。

		逐弧选择服务类型时每条铁路弧按其自身服务类型的 η_k 计费，故不能整体
		用一个 η 折算。混编解的 self.service 只是"主导服务类型"（用于展示与
		排序），逐弧计价必须取 arc.service，否则整条混编路径会被主导类型的
		η_k 统一计价，成本分解不再等于总成本。
		"""
		tariff = network.tariff
		road = rail = yard = 0.0
		covered = 0.0
		for arc in self.arcs:
			if arc.is_transfer:
				yard += arc.cost
			elif arc.is_road:
				road += arc.cost
			else:
				code = arc.service if arc.service is not None else self.service
				eta = config.service_type(code).eta
				rail += (
					tariff.segment_cost(covered, arc.distance, eta, config.q)
					* config.hazmat_cost_factor
				)
				covered += arc.distance
		return {"road_cost": road, "rail_cost": rail, "yard_cost": yard}

	def risk_breakdown(self) -> dict:
		"""按弧段/节点拆解风险。"""
		arc_risk = sum(a.risk for a in self.arcs if not a.is_transfer)
		node_risk = sum(a.risk for a in self.arcs if a.is_transfer)
		return {"arc_risk": arc_risk, "node_risk": node_risk}

	def to_dict(self, network: FourLayerNetwork, config: UTRRConfig, deadline: float) -> dict:
		"""序列化为字典（写入 solution.json 与实验汇总表）。"""
		costs = self.cost_breakdown(network, config)
		risks = self.risk_breakdown()
		return {
			"service": self.service,
			"service_name": self.service_label(config),
			"service_shares": self.service_shares(),
			"risk": self.risk,
			"cost": self.cost,
			"t0": self.t0,
			"mu": self.mu,
			"sigma": self.sigma,
			"equivalent_time": self.equivalent_time(),
			"reliability": self.reliability(deadline),
			"rail_distance": self.dist,
			"arc_risk": risks["arc_risk"],
			"node_risk": risks["node_risk"],
			"node_risk_share": (risks["node_risk"] / self.risk) if self.risk > 0 else 0.0,
			"road_cost": costs["road_cost"],
			"rail_cost": costs["rail_cost"],
			"yard_cost": costs["yard_cost"],
			"yards": self.yards_used(network),
			"transfers": sum(1 for a in self.arcs if a.is_transfer),
			"nodes": self.node_sequence(),
			"arcs": [
				{"i": a.i, "j": a.j, "kind": a.kind, "service": a.service, "distance": a.distance}
				for a in self.arcs
			],
		}


# ----------------------------------------------------------------------
# 主求解器
# ----------------------------------------------------------------------
class ParetoLabelSolver:
	"""双向多维标号修正算法求解器。"""

	def __init__(self, config: UTRRConfig, instance: CaseInstance, logger=None):
		self.config = config
		self.instance = instance
		self.network = instance.network
		self.logger = logger
		self.deadline = instance.deadline
		self.front = ParetoFront(config.tolerance)
		self._stats: list[SearchStats] = []

	def _log(self, message: str) -> None:
		if self.logger is not None:
			self.logger.info(message)

	# ------------------------------------------------------------------
	# 对外接口
	# ------------------------------------------------------------------
	def _service_scope(self, services: tuple | None) -> tuple:
		"""待搜索的服务类型集合：逐弧选择时只需一次混编搜索（编码 -1）。"""
		if services is not None:
			return services
		if self.config.segment_service:
			return (SERVICE_ANY,)
		return self.config.service_codes

	def solve_pareto(self, services: tuple | None = None, use_deadline: bool = True) -> dict:
		"""求解风险-成本 Pareto 最优路径集。

		use_deadline=False 时不计运到时限约束，得到"完全前沿"，用于刻画机会
		约束把哪些解挡在可行域之外（4.2 节图 5）。
		"""
		start = time.perf_counter()
		lam = self.config.lambda_alpha()
		dims = ("risk", "cost", "time")
		collected: list[Solution] = []
		stats_list = []
		for service in self._service_scope(services):
			solutions, stats = self._solve_service(service, dims, lam, use_deadline=use_deadline)
			collected.extend(solutions)
			stats_list.append(stats)
			self._log(
				f"  服务类型 {self.config.service_name(service)}："
				f"生成标号 {stats.labels_generated}，剪枝率 {stats.prune_rate:.1%}，"
				f"候选解 {len(solutions)}，耗时 {stats.wall_time:.3f}s"
			)
		# 删除服务类型间的重复路径（同一批弧，服务类型不同也视为不同路径）
		unique = {}
		for solution in collected:
			key = solution.signature()
			if key not in unique or solution.cost < unique[key].cost:
				unique[key] = solution
		pareto = pareto_filter(list(unique.values()))
		wall = time.perf_counter() - start
		self._log(f"  Pareto 前沿规模：{len(pareto)}")
		return {
			"solutions": pareto,
			"stats": [s.as_dict() for s in stats_list],
			"wall_time": wall,
			"lambda_alpha": lam,
			"deadline": self.deadline,
			"alpha": self.config.alpha,
		}

	def solve_scalar(
		self,
		objective: str,
		lam: float | None = None,
		services: tuple | None = None,
	) -> dict:
		"""求解单目标方案。

		objective : "cost" 或 "risk"
		lam : 非空表示施加机会约束 M{T̃ ≤ D} ≥ α（时间 T_α ≤ D）；
			  为 None 表示不施加运到时限约束。
		"""
		start = time.perf_counter()
		effective_lam = self.config.lambda_alpha() if lam is None else lam
		dims = (objective, "time") if lam is not None else (objective,)
		best: Solution | None = None
		stats_list = []
		for service in self._service_scope(services):
			solutions, stats = self._solve_service(
				service, dims, effective_lam, use_deadline=(lam is not None)
			)
			stats_list.append(stats)
			for solution in solutions:
				if best is None or self._scalar_key(solution, objective) < self._scalar_key(best, objective):
					best = solution
		return {
			"solutions": [] if best is None else [best],
			"stats": [s.as_dict() for s in stats_list],
			"wall_time": time.perf_counter() - start,
			"lambda_alpha": effective_lam,
			"deadline": self.deadline,
			"alpha": self.config.alpha,
			"objective": objective,
		}

	@staticmethod
	def _scalar_key(solution: Solution, objective: str) -> tuple:
		"""单目标排序键；主目标相同则按次目标与成本打破平局。"""
		if objective == "cost":
			return (round(solution.cost, 6), solution.risk)
		return (round(solution.risk, 9), solution.cost)

	# ------------------------------------------------------------------
	# 单一服务类型的标号搜索
	# ------------------------------------------------------------------
	def _solve_service(
		self,
		service: int,
		dims: tuple,
		lam: float,
		use_deadline: bool,
	) -> tuple:
		stats = SearchStats(service=service)
		stats.direction = "bidirectional" if self.config.bidirectional else "forward"
		bounds = self.network.bounds(service)
		self.front = ParetoFront(self.config.tolerance)
		clock = time.perf_counter()

		if self.config.bidirectional:
			solutions = self._search_bidirectional(service, dims, lam, use_deadline, bounds, stats)
		else:
			solutions = self._search_forward(service, dims, lam, use_deadline, bounds, stats)

		stats.wall_time = time.perf_counter() - clock
		pruned = stats.labels_dominated + stats.labels_chance_pruned + stats.labels_bounds_pruned
		stats.prune_rate = pruned / stats.labels_generated if stats.labels_generated else 0.0
		self._stats.append(stats)
		return solutions, stats

	# ------------------------------------------------------------------
	# 前向搜索
	# ------------------------------------------------------------------
	def _search_forward(self, service, dims, lam, use_deadline, bounds, stats) -> list:
		buckets: dict[str, list[Label]] = {node: [] for node in self.network.nodes}
		root = Label(self.network.origin, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, service, None, None, 0)
		buckets[self.network.origin].append(root)
		queue: list[Label] = [root]
		solutions: list[Solution] = []

		while queue:
			label = queue.pop()
			stats.labels_expanded += 1
			for arc in self.network.arcs_out(label.node):
				if arc.is_rail and service >= 0 and arc.service != service:
					continue
				child = self._extend(label, arc, service, reverse=False)
				if child is None:
					continue
				stats.labels_generated += 1
				if not self._screen(child, buckets, dims, lam, use_deadline, bounds, stats):
					continue
				buckets[child.node].append(child)
				queue.append(child)
				if child.node == self.network.destination:
					solution = self._build_solution_forward(child, lam, service, use_deadline)
					if solution is not None:
						solutions.append(solution)
						self.front.add(solution.risk, solution.cost)
		stats.labels_kept = sum(len(v) for v in buckets.values())
		stats.peak_labels_per_node = max((len(v) for v in buckets.values()), default=0)
		return pareto_filter(solutions)

	# ------------------------------------------------------------------
	# 双向搜索
	# ------------------------------------------------------------------
	def _search_bidirectional(self, service, dims, lam, use_deadline, bounds, stats) -> list:
		hop_from = self.network.hop_from_origin()
		hop_to = self.network.hop_to_destination()
		origin_bounds = self.network.bounds_from_origin(service)

		def forward_allowed(node: str) -> bool:
			"""前向标号在该节点是否继续扩展（铁路层按跳数切分搜索区域）。"""
			if not self.network.is_rail_node(node):
				return True
			return hop_from.get(node, -1) <= hop_to.get(node, 10**6)

		def backward_allowed(node: str) -> bool:
			if not self.network.is_rail_node(node):
				return True
			return hop_to.get(node, 10**6) < hop_from.get(node, -1)

		# ---- 前向：起点 → 铁路层切分点 ----
		forward: dict[str, list[Label]] = {node: [] for node in self.network.nodes}
		root = Label(self.network.origin, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, service, None, None, 0)
		forward[self.network.origin].append(root)
		queue = [root]
		while queue:
			label = queue.pop()
			if not forward_allowed(label.node):
				continue
			stats.labels_expanded += 1
			for arc in self.network.arcs_out(label.node):
				if arc.is_rail and service >= 0 and arc.service != service:
					continue
				child = self._extend(label, arc, service, reverse=False)
				if child is None:
					continue
				stats.labels_generated += 1
				if not self._screen(child, forward, dims, lam, use_deadline, bounds, stats):
					continue
				forward[child.node].append(child)
				queue.append(child)

		# ---- 后向：终点 → 铁路层切分点 ----
		backward: dict[str, list[Label]] = {node: [] for node in self.network.nodes}
		tail = Label(self.network.destination, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, service, None, None, 0)
		backward[self.network.destination].append(tail)
		solutions: list[Solution] = []
		queue = [tail]
		while queue:
			label = queue.pop()
			if not backward_allowed(label.node):
				continue
			stats.labels_expanded += 1
			for arc in self.network.arcs_in(label.node):
				if arc.is_rail and service >= 0 and arc.service != service:
					continue
				child = self._extend(label, arc, service, reverse=True)
				if child is None:
					continue
				stats.labels_generated += 1
				if not self._screen(child, backward, dims, lam, use_deadline, origin_bounds, stats):
					continue
				backward[child.node].append(child)
				queue.append(child)
				# 增量汇合产生已知完整解，使后续标号可使用风险-成本向量下界剪枝。
				# _merge 会校验服务连续性、简单路径和机会约束，不合格配对不会进入前沿。
				if self.network.is_rail_node(child.node):
					for label_f in forward.get(child.node, []):
						solution = self._merge(label_f, child, service, lam, use_deadline)
						if solution is None:
							continue
						solutions.append(solution)
						self.front.add(solution.risk, solution.cost)

		# ---- 汇合：仅在铁路层节点拼接，避免转运资源重复计数 ----
		for node in self.network.layer_nodes("rail"):
			front_labels = forward.get(node, [])
			back_labels = backward.get(node, [])
			if not front_labels or not back_labels:
				continue
			for label_f in front_labels:
				for label_b in back_labels:
					solution = self._merge(label_f, label_b, service, lam, use_deadline)
					if solution is None:
						continue
					solutions.append(solution)
					self.front.add(solution.risk, solution.cost)

		stats.labels_kept = sum(len(v) for v in forward.values()) + sum(len(v) for v in backward.values())
		stats.peak_labels_per_node = max(
			max((len(v) for v in forward.values()), default=0),
			max((len(v) for v in backward.values()), default=0),
		)
		return pareto_filter(solutions)

	# ------------------------------------------------------------------
	# 资源扩展（式（14））
	# ------------------------------------------------------------------
	def _extend(self, label: Label, arc, service: int, reverse: bool) -> Label | None:
		"""沿弧扩展一个标号。

		reverse=True 时表示后向扩展：新标号位于弧的起点 i，语义为"从 i 到终点"，
		铁路成本按剩余运距 d（终点侧已累计）折算，与式（5）的望远镜性质对称。

		service < 0 表示逐弧选择服务类型：铁路弧按其自身服务类型计费，且换装服务
		类型只能在货场完成——标号记录了当前所处服务类型（-1 表示刚在货场完成
		转运、可重新选择），未经过货场时不得中途改乘其它等级列车。
		"""
		cfg = self.config
		mixed = service < 0
		current = label.service

		if arc.is_rail and mixed and current >= 0 and current != arc.service:
			return None  # 中途换服务类型须先经货场转运

		risk = label.risk + arc.risk
		cost = label.cost
		t0 = label.t0 + arc.travel_time
		mu, sigma, dist = label.mu, label.sigma, label.dist

		if arc.is_transfer:
			yard = self.network.yards[self.network.nodes[arc.i].yard]
			cost += arc.cost
			mu += yard.mu
			sigma += yard.sigma
			if mixed:
				current = -1  # 已完成转运，后续铁路弧可重新选择服务类型
		elif arc.is_road:
			cost += arc.cost
		else:
			eta = cfg.service_type(arc.service if mixed else service).eta
			cost += (
				self.network.tariff.segment_cost(dist, arc.distance, eta, cfg.q)
				* cfg.hazmat_cost_factor
			)
			dist += arc.distance
			if mixed:
				current = arc.service

		node = arc.i if reverse else arc.j
		# 简单路径约束：禁止回到标号链上已访问的节点（正成本下最优路径必为简单路径）
		if label.node == node:
			return None
		cursor = label
		while cursor is not None:
			if cursor.node == node:
				return None
			cursor = cursor.parent
		return Label(node, risk, cost, t0, mu, sigma, dist, current, label, arc, label.depth + 1)

	# ------------------------------------------------------------------
	# 剪枝与支配筛选
	# ------------------------------------------------------------------
	def _screen(self, label, buckets, dims, lam, use_deadline, bounds, stats) -> bool:
		"""对一个新标号依次执行机会可行性、下界与支配剪枝；返回 False 表示删除。

		bounds 由调用方按搜索方向提供：前向标号用"到终点"下界，后向标号用
		"自起点"下界，保证剪枝可采纳。
		"""
		cfg = self.config
		if use_deadline and cfg.enable_chance_pruning:
			remaining_time = bounds.get_time(label.node)
			if remaining_time == INF:
				stats.labels_chance_pruned += 1
				return False
			if label.equivalent_time(lam) + remaining_time > self.deadline + cfg.tolerance:
				stats.labels_chance_pruned += 1
				return False

		if cfg.enable_pruning:
			risk_bound = label.risk + bounds.get_risk(label.node) if "risk" in dims else -INF
			cost_bound = label.cost + bounds.get_cost(label.node) if "cost" in dims else -INF
			if risk_bound == INF or cost_bound == INF:
				stats.labels_bounds_pruned += 1
				return False
			if risk_bound > -INF and cost_bound > -INF:
				if self.front.dominates_lower_left(risk_bound, cost_bound):
					stats.labels_bounds_pruned += 1
					return False

		if cfg.enable_dominance:
			bucket = buckets[label.node]
			kept = []
			for other in bucket:
				# 混编模式下同一节点可能并存处于不同服务类型的标号，其后续铁路
				# 计费系数 η_k 不同，成本维度不可直接比较，故只在同服务类型内支配。
				if other.service != label.service:
					kept.append(other)
					continue
				if self._dominates(other, label, dims, lam):
					stats.labels_dominated += 1
					return False
				if self._dominates(label, other, dims, lam):
					stats.labels_dominated += 1
				else:
					kept.append(other)
			if len(kept) != len(bucket):
				bucket[:] = kept

		if len(buckets[label.node]) >= cfg.max_labels_per_node:
			stats.truncated = True
			return False
		return True

	def _dominates(self, a: Label, b: Label, dims: tuple, lam: float) -> bool:
		"""同节点同服务类型的多维 Pareto 支配判断（论文 3.2）。

		成本维度按论文支配规则分两支比较：d_a ≥ d_b 时直接比 C；d_a < d_b 时比
		修正成本 W = V + η_k·a3·d（V = C − η_k·f(d)）。该修正使"少走了铁路里程"
		的标号不会因表面成本更低而错误支配。
		"""
		tol = self.config.tolerance
		strict = False
		for dim in dims:
			if dim == "risk":
				if a.risk > b.risk + tol:
					return False
				strict |= a.risk < b.risk - tol
			elif dim == "time":
				ta, tb = a.equivalent_time(lam), b.equivalent_time(lam)
				if ta > tb + tol:
					return False
				strict |= ta < tb - tol
			elif dim == "cost":
				if a.service < 0 or b.service < 0:
					# 刚完成转运的标号尚未确定后续服务类型，η_k 未定，成本修正无定义；
					# 此时只采用充分分支：铁路运距不短于对方时方可比较原始成本。
					if a.dist < b.dist - tol:
						return False
					if a.cost > b.cost + tol:
						return False
					strict |= a.cost < b.cost - tol
					continue
				va, vb = self._corrected_cost(a), self._corrected_cost(b)
				if a.dist >= b.dist - tol:
					if a.cost > b.cost + tol:
						return False
					strict |= a.cost < b.cost - tol
				else:
					wa, wb = self._weight_cost(a, va), self._weight_cost(b, vb)
					if wa > wb + tol:
						return False
					strict |= wa < wb - tol
			else:  # pragma: no cover - 配置错误
				raise KeyError(f"未知支配维度：{dim}")
		return strict

	def _corrected_cost(self, label: Label) -> float:
		"""V(L) = C(L) − ζ_s·η_k·f(d)·q，剥离已计入的铁路全程运费。"""
		eta = self.config.service_type(label.service).eta
		return (
			label.cost
			- self.config.hazmat_cost_factor
			* eta
			* self.network.tariff.fare_per_ton(label.dist)
			* self.config.q
		)

	def _weight_cost(self, label: Label, corrected: float) -> float:
		"""W(L) = V(L) + ζ_s·η_k·a3·d·q。"""
		eta = self.config.service_type(label.service).eta
		return (
			corrected
			+ self.config.hazmat_cost_factor
			* eta
			* self.network.tariff.a3
			* label.dist
			* self.config.q
		)

	# ------------------------------------------------------------------
	# 解构造
	# ------------------------------------------------------------------
	def _chain(self, label: Label) -> list:
		arcs = []
		cursor = label
		while cursor is not None and cursor.arc is not None:
			arcs.append(cursor.arc)
			cursor = cursor.parent
		return arcs

	def _recompute(self, arcs: tuple, service: int) -> dict:
		"""沿弧序列重算全部累计量（成本按式（5）逐弧计费）。

		双向汇合、混编服务类型都涉及"两条半程拼接后重新计费"，逐弧重算可避免
		各分支各写一套折算公式而产生口径不一致。
		"""
		cfg = self.config
		risk = cost = t0 = mu = sigma = dist = 0.0
		service_km: dict = {}
		for arc in arcs:
			risk += arc.risk
			t0 += arc.travel_time
			if arc.is_transfer:
				yard = self.network.yards[self.network.nodes[arc.i].yard]
				cost += arc.cost
				mu += yard.mu
				sigma += yard.sigma
			elif arc.is_road:
				cost += arc.cost
			else:
				code = arc.service if service < 0 else service
				eta = cfg.service_type(code).eta
				cost += (
					self.network.tariff.segment_cost(dist, arc.distance, eta, cfg.q)
					* cfg.hazmat_cost_factor
				)
				dist += arc.distance
				service_km[code] = service_km.get(code, 0.0) + arc.distance
		return {
			"risk": risk,
			"cost": cost,
			"t0": t0,
			"mu": mu,
			"sigma": sigma,
			"dist": dist,
			"service_km": service_km,
		}

	def _build_solution_forward(
		self, label: Label, lam: float, service: int, use_deadline: bool
	) -> Solution | None:
		arcs = tuple(reversed(self._chain(label)))
		return self._make_solution(arcs, service, lam, use_deadline)

	def _merge(self, label_f: Label, label_b: Label, service: int, lam: float, use_deadline: bool) -> Solution | None:
		"""拼接前向与后向标号，核算全程成本与机会约束可行性。

		拼接在铁路层节点上进行，若该节点恰为货场出口，左右两半可能分属不同服务
		类型，故成本按逐弧重算而非整段折算。
		"""
		arcs = tuple(reversed(self._chain(label_f))) + tuple(self._chain(label_b))
		if not arcs:
			return None
		if (
			label_f.service >= 0
			and label_b.service >= 0
			and label_f.service != label_b.service
		):
			# 前向半程末段与后向半程首段的列车等级不一致，却又都没在汇合点转运，
			# 属物理上不成立的中途换编组，须舍弃。
			return None
		return self._make_solution(arcs, service, lam, use_deadline)

	def _make_solution(
		self, arcs: tuple, service: int, lam: float, use_deadline: bool = True
	) -> Solution | None:
		if not arcs:
			return None
		sequence = [arcs[0].i] + [arc.j for arc in arcs]
		if sequence[0] != self.network.origin or sequence[-1] != self.network.destination:
			return None
		if len(set(sequence)) != len(sequence):
			return None
		if not any(arc.kind == ARC_RAIL for arc in arcs):
			return None
		values = self._recompute(arcs, service)
		if use_deadline and equivalent_time(
			values["t0"], values["mu"], values["sigma"], lam
		) > self.deadline + self.config.tolerance:
			return None
		dominant = service
		if service < 0:
			service_km = values["service_km"]
			dominant = max(service_km, key=service_km.get) if service_km else -1
		return Solution(
			arcs=arcs,
			service=dominant,
			risk=values["risk"],
			cost=values["cost"],
			t0=values["t0"],
			mu=values["mu"],
			sigma=values["sigma"],
			dist=values["dist"],
			lam=lam,
			service_km=values["service_km"] if service < 0 else {
				dominant: values["dist"]
			},
		)


# ----------------------------------------------------------------------
# Pareto 过滤
# ----------------------------------------------------------------------
def pareto_filter(solutions: list, tolerance: float = 1e-9) -> list:
	"""按 (risk, cost) 对解集做非支配过滤，返回按风险升序排列的前沿。"""
	if not solutions:
		return []
	ordered = sorted(solutions, key=lambda s: (s.risk, s.cost))
	front = []
	best_cost = INF
	for solution in ordered:
		if solution.cost < best_cost - tolerance:
			front.append(solution)
			best_cost = solution.cost
	# 风险相同的解只保留成本最小者
	dedup: dict = {}
	for solution in front:
		key = round(solution.risk, 9)
		if key not in dedup or solution.cost < dedup[key].cost:
			dedup[key] = solution
	return sorted(dedup.values(), key=lambda s: (s.risk, s.cost))
