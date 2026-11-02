"""四层危险货物公铁联运网络 G = (N, A)（论文第 1 节、式（6））。

节点分层（方案 Q 符号体系）：
	N_c 客户层（供应点 o、需求点 d）
	N_r 公路层（公路内部节点）
	N_t 转运层（货场，按"入/出"拆分为两个节点，以转运虚拟弧相连）
	N_l 铁路层（铁路中间节点）

弧集合：
	A_r 公路弧（公路内部弧 + 公铁接驳弧）
	A_l 铁路弧（按服务类型 k 区分）
	A_t 转运虚拟弧（货场内装卸、暂存、安检、等待、换装过程）
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field

from config import UTRRConfig
from src.core.tariff import DecreasingTariff

LAYER_CLIENT = "client"
LAYER_ROAD = "road"
LAYER_YARD = "yard"
LAYER_RAIL = "rail"

ARC_ROAD = "road"
ARC_RAIL = "rail"
ARC_TRANSFER = "transfer"

SIDE_ORIGIN = "origin"
SIDE_DESTINATION = "destination"

INF = float("inf")


@dataclass(frozen=True)
class Node:
	"""网络节点。"""

	node_id: str
	layer: str
	x: float
	y: float
	name: str = ""
	side: str = SIDE_ORIGIN  # origin / destination / middle
	yard: str | None = None  # 货场节点所属货场名
	port: str | None = None  # 货场节点的入/出口标识：in / out


@dataclass(frozen=True)
class Arc:
	"""网络弧。铁路弧的运输成本依赖累计运距，由费率函数在标号扩展时计算。"""

	i: str
	j: str
	kind: str
	distance: float  # 弧长 l_ij（km）
	travel_time: float  # 确定性运输时间 t_ij（h），转运虚拟弧为 0（时间不确定）
	risk: float  # 弧段风险 r_ij；转运虚拟弧为货场节点风险 r_i^t
	cost: float  # 公路/转运成本；铁路弧为 0，扩展时按式（5）计算
	service: int | None = None  # 铁路弧所属服务类型 k
	line: str = ""  # 铁路弧所属线路名（用于路径的通道级概括）

	@property
	def is_road(self) -> bool:
		return self.kind == ARC_ROAD

	@property
	def is_rail(self) -> bool:
		return self.kind == ARC_RAIL

	@property
	def is_transfer(self) -> bool:
		return self.kind == ARC_TRANSFER


@dataclass(frozen=True)
class Yard:
	"""货场及其转运时间不确定参数。"""

	name: str
	in_node: str
	out_node: str
	qualified: bool
	mu: float
	sigma: float
	unit_cost: float
	fixed_cost: float
	accident_prob: float
	exposure: float

	def node_risk(self, quantity: float, theta: float, rho: float, factor: float = 1.0) -> float:
		"""节点转运风险 r_i^t = q·p_i^t·POP_i^t·(1 + θ·μ_i + ρ·σ_i)·ζ_s（式（2））。

		accident_prob 为单位中转事故概率（黄丽霞 §5.5.2(9)），exposure 为中转事故
		后果 POP；μ_i、σ_i 含班列衔接等待（矩匹配）。
		"""
		return (
			quantity
			* self.accident_prob
			* self.exposure
			* (1.0 + theta * self.mu + rho * self.sigma)
			* factor
		)

	def transfer_cost(self, quantity: float) -> float:
		"""货场中转成本 = 固定作业费 + 单位箱数作业费（黄丽霞表 5-12，元/箱）。"""
		return self.fixed_cost + quantity * self.unit_cost


@dataclass
class Bounds:
	"""各节点到终点的可采纳下界（时间/风险/成本）。"""

	time: dict = field(default_factory=dict)
	risk: dict = field(default_factory=dict)
	cost: dict = field(default_factory=dict)

	def get_time(self, node: str) -> float:
		return self.time.get(node, INF)

	def get_risk(self, node: str) -> float:
		return self.risk.get(node, INF)

	def get_cost(self, node: str) -> float:
		return self.cost.get(node, INF)


class FourLayerNetwork:
	"""四层公铁联运网络。"""

	def __init__(self, config: UTRRConfig):
		self.config = config
		self.tariff = DecreasingTariff(config)
		self.nodes: dict[str, Node] = {}
		self.arcs: list[Arc] = []
		self.out_arcs: dict[str, list[Arc]] = {}
		self.in_arcs: dict[str, list[Arc]] = {}
		self.yards: dict[str, Yard] = {}
		self.origin: str = ""
		self.destination: str = ""
		self._bounds: dict[int, Bounds] = {}
		self._forward_bounds: dict[int, Bounds] = {}
		self._hop_from: dict[str, int] | None = None
		self._hop_to: dict[str, int] | None = None

	# ------------------------------------------------------------------
	# 构建
	# ------------------------------------------------------------------
	def add_node(self, node: Node) -> Node:
		if node.node_id in self.nodes:
			raise ValueError(f"节点重复：{node.node_id}")
		self.nodes[node.node_id] = node
		self.out_arcs.setdefault(node.node_id, [])
		self.in_arcs.setdefault(node.node_id, [])
		return node

	def add_arc(self, arc: Arc) -> Arc:
		for endpoint in (arc.i, arc.j):
			if endpoint not in self.nodes:
				raise KeyError(f"弧端点不存在：{endpoint}")
		self.arcs.append(arc)
		self.out_arcs[arc.i].append(arc)
		self.in_arcs[arc.j].append(arc)
		self._bounds.clear()
		self._forward_bounds.clear()
		self._hop_from = None
		self._hop_to = None
		return arc

	def add_yard(self, yard: Yard) -> Yard:
		self.yards[yard.name] = yard
		return yard

	def clone(self, config=None, yards: dict | None = None, arcs: list | None = None) -> "FourLayerNetwork":
		"""复制网络拓扑，可按需替换货场参数与弧集（敏感性实验的派生算例）。

		节点与弧均为不可变对象，可直接共享；下界与跳数缓存由 add_arc 自动失效。
		"""
		new = FourLayerNetwork(config or self.config)
		new.origin = self.origin
		new.destination = self.destination
		for node in self.nodes.values():
			new.add_node(node)
		new.yards = dict(self.yards if yards is None else yards)
		for arc in self.arcs if arcs is None else arcs:
			new.add_arc(arc)
		return new

	# ------------------------------------------------------------------
	# 弧参数计算
	# ------------------------------------------------------------------
	def rail_time(self, distance: float, service: int, speed_factor: float = 1.0) -> float:
		"""铁路弧运输时间 t_ij^{l,k} = l_ij / v_k（纯运行时间，参数体系修订后无途中停时）。"""
		spec = self.config.service_type(service)
		return distance / spec.speed

	def road_time(self, distance: float) -> float:
		"""公路弧运输时间 t_ij^r。"""
		return distance / self.config.road_speed

	def rail_risk(self, distance: float, exposure: float, service: int) -> float:
		"""铁路弧风险 r_ij^{l,k} = q·l_ij·p^l·POP·κ_k·ζ_s（黄丽霞 §5.5.2(9) 口径）。"""
		spec = self.config.service_type(service)
		return (
			self.config.q
			* distance
			* self.config.rail_unit_acc_prob
			* exposure
			* spec.risk_multiplier
			* self.config.hazmat_risk_factor
		)

	def road_risk(self, distance: float, exposure: float) -> float:
		"""公路弧风险 r_ij^r = q·l_ij·p^r·POP·ζ_s。"""
		return (
			self.config.q
			* distance
			* self.config.road_unit_acc_prob
			* exposure
			* self.config.hazmat_risk_factor
		)

	# ------------------------------------------------------------------
	# 查询
	# ------------------------------------------------------------------
	def arcs_out(self, node: str, kinds: tuple | None = None) -> list[Arc]:
		if kinds is None:
			return self.out_arcs.get(node, [])
		return [arc for arc in self.out_arcs.get(node, []) if arc.kind in kinds]

	def arcs_in(self, node: str, kinds: tuple | None = None) -> list[Arc]:
		if kinds is None:
			return self.in_arcs.get(node, [])
		return [arc for arc in self.in_arcs.get(node, []) if arc.kind in kinds]

	def layer_nodes(self, layer: str) -> list[str]:
		return [nid for nid, node in self.nodes.items() if node.layer == layer]

	def coord(self, node: str) -> tuple:
		n = self.nodes[node]
		return (n.x, n.y)

	def is_rail_node(self, node: str) -> bool:
		return self.nodes[node].layer == LAYER_RAIL

	def distance_between(self, u: str, v: str) -> float:
		ux, uy = self.coord(u)
		vx, vy = self.coord(v)
		return ((ux - vx) ** 2 + (uy - vy) ** 2) ** 0.5

	# ------------------------------------------------------------------
	# 下界预计算（Step 2）：各节点到终点的最短时间、最小风险与最小成本
	# ------------------------------------------------------------------
	def _bound_rate(self, service: int) -> float:
		"""成本下界所用的单位铁路费率：混编时取各服务类型边际费率的最小值。"""
		if service >= 0:
			return self.tariff.min_rate(self.config.service_type(service).eta)
		return min(
			self.tariff.min_rate(spec.eta) for spec in self.config.service_types
		)

	def bounds(self, service: int) -> Bounds:
		"""返回给定服务类型下各节点到终点的可采纳下界。

		- 时间下界：以 t_ij 为权（T_α ≥ T0 的累加，故为 T_α 的合法下界）；
		- 风险下界：以 r_ij 为权；
		- 成本下界：铁路弧取边际费率下限 η_k·a3·l_ij（边际费率随运距递减至 a3），
		  公路与转运弧取实际成本。
		"""
		if service in self._bounds:
			return self._bounds[service]
		rate = self._bound_rate(service)
		bounds = Bounds()
		for weight_fn, target in (
			(lambda arc: arc.travel_time, bounds.time),
			(lambda arc: arc.risk, bounds.risk),
			(lambda arc: rate * arc.distance if arc.is_rail else arc.cost, bounds.cost),
		):
			target.update(self._dijkstra(weight_fn, service, reverse=True))
		self._bounds[service] = bounds
		return bounds

	def bounds_from_origin(self, service: int) -> Bounds:
		"""返回自起点至各节点的可采纳下界（供后向标号剪枝使用）。"""
		if service in self._forward_bounds:
			return self._forward_bounds[service]
		rate = self._bound_rate(service)
		bounds = Bounds()
		for weight_fn, target in (
			(lambda arc: arc.travel_time, bounds.time),
			(lambda arc: arc.risk, bounds.risk),
			(lambda arc: rate * arc.distance if arc.is_rail else arc.cost, bounds.cost),
		):
			target.clear()
			target.update(self._dijkstra(weight_fn, service, reverse=False))
		self._forward_bounds[service] = bounds
		return bounds

	def _dijkstra(self, weight_fn, service: int, reverse: bool) -> dict:
		"""单源 Dijkstra；reverse=True 时在反向图上从终点出发。

		service < 0 表示逐弧选择服务类型（混编），此时铁路弧不受服务类型限制，
		且调用方的权函数须对混编给出可采纳下界。
		"""
		dist = {node: INF for node in self.nodes}
		start = self.destination if reverse else self.origin
		dist[start] = 0.0
		adj = self.in_arcs if reverse else self.out_arcs
		heap = [(0.0, start)]
		while heap:
			d, node = heapq.heappop(heap)
			if d > dist[node] + 1e-15:
				continue
			for arc in adj.get(node, []):
				if arc.is_rail and service >= 0 and arc.service != service:
					continue
				other = arc.i if reverse else arc.j
				candidate = d + weight_fn(arc)
				if candidate + 1e-15 < dist[other]:
					dist[other] = candidate
					heapq.heappush(heap, (candidate, other))
		return dist

	# ------------------------------------------------------------------
	# 运到时限标定
	# ------------------------------------------------------------------
	def min_equivalent_time(self, lam: float) -> float:
		"""以 t_ij（公路/铁路）与 μ_i + λ_α·σ_i（转运虚拟弧）为权的最短等价时间。

		取 λ_α 后即为"置信水平 α 下最快可达"的等价时间，用于标定运到时限 D。
		"""
		dist = {node: INF for node in self.nodes}
		dist[self.origin] = 0.0
		heap = [(0.0, self.origin)]
		while heap:
			d, node = heapq.heappop(heap)
			if d > dist[node] + 1e-12:
				continue
			if node == self.destination:
				return d
			for arc in self.out_arcs.get(node, []):
				if arc.is_transfer:
					info = self.yards[self.nodes[arc.i].yard]
					weight = info.mu + lam * info.sigma
				else:
					weight = arc.travel_time
				candidate = d + weight
				if candidate < dist[arc.j] - 1e-12:
					dist[arc.j] = candidate
					heapq.heappush(heap, (candidate, arc.j))
		return INF

	# ------------------------------------------------------------------
	# 跳数（用于双向汇合的搜索区域划分）
	# ------------------------------------------------------------------
	def hop_from_origin(self) -> dict:
		if self._hop_from is None:
			self._hop_from = self._bfs_hops(reverse=False)
		return self._hop_from

	def hop_to_destination(self) -> dict:
		if self._hop_to is None:
			self._hop_to = self._bfs_hops(reverse=True)
		return self._hop_to

	def _bfs_hops(self, reverse: bool) -> dict:
		"""无权 BFS 跳数；reverse=True 时在反向图上从终点出发。"""
		start = self.destination if reverse else self.origin
		adj = self.in_arcs if reverse else self.out_arcs
		hops = {node: -1 for node in self.nodes}
		hops[start] = 0
		queue = [start]
		while queue:
			nxt = []
			for node in queue:
				for arc in adj.get(node, []):
					other = arc.i if reverse else arc.j
					if hops[other] < 0:
						hops[other] = hops[node] + 1
						nxt.append(other)
			queue = nxt
		return hops

	# ------------------------------------------------------------------
	# 统计与序列化
	# ------------------------------------------------------------------
	def counts(self) -> dict:
		"""返回网络规模统计。"""
		stats = {
			"num_nodes": len(self.nodes),
			"num_arcs": len(self.arcs),
			"num_yards": len(self.yards),
		}
		for layer in (LAYER_CLIENT, LAYER_ROAD, LAYER_YARD, LAYER_RAIL):
			stats[f"num_{layer}_nodes"] = len(self.layer_nodes(layer))
		for kind in (ARC_ROAD, ARC_RAIL, ARC_TRANSFER):
			stats[f"num_{kind}_arcs"] = sum(1 for a in self.arcs if a.kind == kind)
		# 铁路总里程：按无向站对去重（正反向弧各一条），再除以服务类型份数
		pairs = {}
		for arc in self.arcs:
			if arc.is_rail:
				pairs[(min(arc.i, arc.j), max(arc.i, arc.j))] = arc.distance
		stats["total_rail_length_km"] = round(
			sum(pairs.values()) / max(1, len(self.config.service_codes)), 1
		)
		return stats
