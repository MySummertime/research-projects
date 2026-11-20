"""真实路网 JSON → 四层网络的适配器。

数据契约（本项目自有格式，由 data/real_case/build_network.py 生成）：

	payload = {
	  "name": "...", "version": "xj-yrd-v2", "coordinate_system": "lonlat",
	  "line_meta":  {"兰新线": {"section": "兰州—乌鲁木齐南", "km": 1892.0,
	                            "grade": "A", "note": "逐站里程累计"}},
	  "rail_nodes": [{"id": "LZ", "name": "兰州", "lon": 103.79, "lat": 36.06}],
	  "rail_arcs":  [{"i": "LZ", "j": "YD", "km": 111.0, "line": "兰新线",
	                  "speed_factor": 1.0, "exposure": 0.55}],
	  "yards":      [{"id": "Y8", "name": "兰州北", "rail_node": "LZ",
	                  "station": "兰州", "facility": "兰州北编组站",
	                  "tier": "A", "qualified": true}],
	  "od_pairs":   [{"id": "OD1", "hazmat": 8, "demand_t": 320.0,
	                  "origin": {"name": "...", "lon": .., "lat": ..},
	                  "destination": {"name": "...", "lon": .., "lat": ..},
	                  "origin_yards": [{"yard": "Y1", "km": 28.0}, ...],
	                  "destination_yard": {"yard": "Y16", "km": 55.0},
	                  "transit_yards": ["Y8", "Y9", ...],
	                  "deadline_h": null}]
	}

字段约定：
	km            弧长（km），取公开线路里程
	speed_factor  该线允许速度相对班列标称速度的折减系数（φ_ij）
	exposure      该线沿线人口暴露系数 e_ij，决定弧段风险的真实差异
	tier          A = 危险货物专办站（对应表 1 的 S1 级），B = 普通货场可换装（S2 级）
	qualified     是否可办理换装；不具备者只有通过能力，不生成转运虚拟弧

转换规则（与论文 4.1 的四层结构一一对应）：
	客户层  —— OD 的装货点 o 与卸货点 d
	公路层  —— 客户点与首末货场之间的接驳弧（按 OD 给定的实测公路里程）
	转运层  —— 该 OD 涉及的货场：发送端候选、干线中途转运点、到达货场；
	           每个货场按"入/出"拆分，以转运虚拟弧相连
	铁路层  —— 全部真实车站；铁路弧按服务类型 k 复制，并带上该线的速度折减与
	           暴露系数

只实体化与该 OD 相关的货场，其余车站仅作为通过节点，避免无关货场放大搜索空间。
"""

from __future__ import annotations

import json
import math

from config import UTRRConfig
from src.core.instance_generator import CaseInstance
from src.core.network import (
	ARC_RAIL,
	ARC_ROAD,
	ARC_TRANSFER,
	LAYER_CLIENT,
	LAYER_RAIL,
	LAYER_YARD,
	Arc,
	FourLayerNetwork,
	Node,
	Yard,
)

EARTH_RADIUS_KM = 6371.0088

# 货场等级 → 表 1 的货场参数档位
TIER_PROFILE = {"A": "S1", "B": "S2"}  # 货场等级→合成算例档位（真实算例仅用资质标志）


# ----------------------------------------------------------------------
# 读取与规范化
# ----------------------------------------------------------------------
def read_payload(path: str) -> dict:
	with open(path, encoding="utf-8") as handle:
		return json.load(handle)


def haversine(a: tuple, b: tuple) -> float:
	"""经纬度大圆距离（km），仅在未给定公路里程时用于估算接驳距离。"""
	lon1, lat1 = math.radians(a[0]), math.radians(a[1])
	lon2, lat2 = math.radians(b[0]), math.radians(b[1])
	dlon, dlat = lon2 - lon1, lat2 - lat1
	h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
	return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


# ----------------------------------------------------------------------
# 主转换
# ----------------------------------------------------------------------
class RealCaseBuilder:
	"""把真实路网 JSON 装配为四层网络算例。"""

	def __init__(self, config: UTRRConfig):
		self.config = config
		self.warnings: list = []

	def build(self, payload: dict) -> CaseInstance:
		cfg = self.config
		od_pairs = payload.get("od_pairs") or []
		if not od_pairs:
			raise ValueError("路网 JSON 缺少 od_pairs，无法确定客户点与时限")
		if not 0 <= cfg.real_case_od < len(od_pairs):
			raise IndexError(f"real_case_od={cfg.real_case_od} 超出 OD 对数 {len(od_pairs)}")
		od = od_pairs[cfg.real_case_od]

		# 运量与品类由 OD 决定：写回配置，使弧成本、风险与求解口径保持一致
		cfg.q = float(cfg.demand_override if cfg.demand_override is not None else od["demand_boxes"])
		cfg.hazmat_class = int(od["hazmat"])

		self.rail_nodes = {node["id"]: node for node in payload["rail_nodes"]}
		self.yards_raw = {yard["id"]: yard for yard in payload["yards"]}
		self.coord = {nid: (float(n["lon"]), float(n["lat"])) for nid, n in self.rail_nodes.items()}

		used = self._yard_scope(od)
		net = FourLayerNetwork(cfg)
		net.origin = "o"
		net.destination = "d"

		# ---------------- 客户层 ----------------
		origin = od["origin"]
		destination = od["destination"]
		ox, oy = float(origin["lon"]), float(origin["lat"])
		dx, dy = float(destination["lon"]), float(destination["lat"])
		net.add_node(Node("o", LAYER_CLIENT, ox, oy, origin["name"]))
		net.add_node(Node("d", LAYER_CLIENT, dx, dy, destination["name"]))

		# ---------------- 铁路层 ----------------
		# 挂接货场的车站拆成"到达侧 a / 出发侧 b"两个节点：到达侧可经货场转运到出发侧
		# （或经零成本通过弧直接贯通）。若货场与车站共用同一节点，进出货场会重复访问
		# 该节点而被简单路径约束拒绝，中途换装便无从发生。
		self.yard_by_rail = {self.yards_raw[yid]["rail_node"]: yid for yid in used}
		for nid, info in self.rail_nodes.items():
			x, y = self.coord[nid]
			if nid in self.yard_by_rail:
				net.add_node(Node(f"L{nid}_a", LAYER_RAIL, x, y, info["name"]))
				net.add_node(Node(f"L{nid}_b", LAYER_RAIL, x, y, info["name"]))
			else:
				net.add_node(Node(f"L{nid}", LAYER_RAIL, x, y, info["name"]))

		# ---------------- 转运层 ----------------
		destination_yard = od["destination_yard"]["yard"]
		transit = set(od["transit_yards"])
		origin_yards = [item["yard"] for item in od["origin_yards"]]
		for yid in used:
			raw = self.yards_raw[yid]
			x, y = self.coord[raw["rail_node"]]
			side = (
				"destination"
				if yid == destination_yard
				else ("transit" if yid in transit and yid not in origin_yards else "origin")
			)
			profile = self._role_profile(side)
			for port in ("in", "out"):
				net.add_node(
					Node(
						f"{yid}_{port}",
						LAYER_YARD,
						x,
						y,
						f"{raw['name']}货场{'入口' if port == 'in' else '出口'}",
						side,
						yid,
						port,
					)
				)
			net.add_yard(
				Yard(
					name=yid,
					in_node=f"{yid}_in",
					out_node=f"{yid}_out",
					qualified=bool(raw.get("qualified", True)),
					mu=profile["mu"],
					sigma=profile["sigma"],
					unit_cost=profile["unit_cost"],
					fixed_cost=profile["fixed_cost"],
					accident_prob=profile["accident_prob"],
					exposure=profile["exposure"],
				)
			)

		# ---------------- 弧 ----------------
		for item in od["origin_yards"]:
			yid = item["yard"]
			self._add_road(net, "o", f"{yid}_in", self._link_km(origin, yid, item.get("km")))
		tail = od["destination_yard"]
		self._add_road(
			net, f"{destination_yard}_out", "d", self._link_km(destination, destination_yard, tail.get("km"))
		)

		for yid in used:
			rail_node = self.yards_raw[yid]["rail_node"]
			in_node, out_node = f"L{rail_node}_a", f"L{rail_node}_b"
			# 通过弧：不换装的车流直接由到达侧进入出发侧，零时间零成本
			self._add_link(net, in_node, out_node)
			# 转运弧两侧：到达侧进得去、出发侧出得来
			self._add_link(net, in_node, f"{yid}_in")
			self._add_link(net, f"{yid}_out", out_node)
			if net.yards[yid].qualified:
				self._add_transfer(net, net.yards[yid])

		for arc in payload["rail_arcs"]:
			distance = float(arc["km"])
			if distance <= cfg.real_rail_min_length:
				continue
			self._add_rail(net, arc, distance)

		# ---------------- 运到时限 ----------------
		lam = cfg.lambda_alpha()
		reference = net.min_equivalent_time(lam)
		if reference == float("inf"):
			raise ValueError("路网中不存在自供应点至需求点的可行联运路径，请检查弧段连通性")
		window = float(od.get("deadline_h") or 0.0)
		if cfg.deadline_hours:
			deadline, mode = float(cfg.deadline_hours), "manual"
		elif cfg.real_case_deadline_mode == "window" and window > 0:
			deadline, mode = window, "window"
		else:
			deadline = max(reference * 1.2, cfg.real_case_min_deadline_hours)
			mode = "calibrated"

		spec = cfg.hazmat()
		metadata = {
			"description": f"{payload.get('name', 'real-case')}（{od.get('id', '')}）",
			"data_source": "real",
			"source_file": cfg.real_case_path,
			"od_id": od.get("id"),
			"od_task": od.get("task", ""),
			"od_quantity_teu": cfg.q,
			"boxes": round(cfg.boxes, 2),
			"volume_tier": list(cfg.volume_tier()),
			"hazmat_code": spec.code,
			"hazmat_name": spec.name_cn,
			"hazmat_cost_factor": spec.cost_factor,
			"hazmat_risk_factor": spec.risk_factor,
			"origin": origin["name"],
			"destination": destination["name"],
			"candidate_yards": {item["yard"]: self.yards_raw[item["yard"]]["name"] for item in od["origin_yards"]},
			"transit_yards": {yid: self.yards_raw[yid]["name"] for yid in od["transit_yards"]},
			"arrival_yard": self.yards_raw[destination_yard]["name"],
			"yard_cities": {yid: self.yards_raw[yid]["name"] for yid in used},
			"yard_tiers": {yid: self.yards_raw[yid]["tier"] for yid in used},
			"min_equivalent_time_hours": round(reference, 4),
			"deadline_mode": mode,
			"transfer_sigma": cfg.transfer_sigma,
			"lambda_alpha": round(lam, 6),
			"confidence_mode": cfg.confidence_mode,
			"coordinate_system": payload.get("coordinate_system", "lonlat"),
			"warnings": list(self.warnings),
		}
		metadata["counts"] = net.counts()
		metadata["line_summary"] = self._line_summary(payload)
		return CaseInstance(net, deadline, cfg.alpha, f"xj-yrd-{od.get('id', cfg.real_case_od + 1)}", metadata)

	# ------------------------------------------------------------------
	# 货场范围与参数
	# ------------------------------------------------------------------
	def _yard_scope(self, od: dict) -> list:
		"""该 OD 需要实体化的货场：发送端候选 + 中途转运点 + 到达货场。"""
		scope: list = []
		for yid in [item["yard"] for item in od["origin_yards"]] + list(od["transit_yards"]):
			if yid not in scope:
				scope.append(yid)
		destination_yard = od["destination_yard"]["yard"]
		if destination_yard not in scope:
			scope.append(destination_yard)
		for yid in scope:
			if yid not in self.yards_raw:
				raise KeyError(f"{od.get('id')} 引用了不存在的货场：{yid}")
		return scope

	def _role_profile(self, side: str) -> dict:
		"""按中转角色给出转运时间 N(e,σ) 与成本、风险参数（黄丽霞表 5-12）。

		origin=公→铁（装车）、transit=铁→铁（换装）、destination=铁→公（卸车）；
		e 取黄丽霞的中转时间 8/4/8 h/批，σ 为算例设定值。
		"""
		cfg = self.config
		idx = {"origin": 0, "transit": 1, "destination": 2}[side]
		return {
			"qualified": True,
			"mu": float(cfg.transfer_time[idx]),
			"sigma": float(cfg.transfer_sigma),
			"unit_cost": float(cfg.transfer_cost_per_box[idx]),
			"fixed_cost": 0.0,
			"accident_prob": cfg.transfer_acc_prob * cfg.transfer_risk_factor[idx],
			"exposure": cfg.pop_transfer,
		}

	def _link_km(self, client: dict, yard_id: str, km: float | None) -> float:
		"""接驳公路里程：OD 给定值优先，否则按绕行系数估大圆距离。"""
		if km:
			return float(km)
		raw = self.yards_raw[yard_id]
		yard_xy = self.coord[raw["rail_node"]]
		distance = haversine((float(client["lon"]), float(client["lat"])), yard_xy)
		self.warnings.append(f"货场 {raw['name']} 未给定接驳里程，按大圆距离 × 1.25 估算")
		return distance * 1.25

	# ------------------------------------------------------------------
	# 弧构造
	# ------------------------------------------------------------------
	def _add_road(self, net: FourLayerNetwork, i: str, j: str, distance: float) -> None:
		distance = round(float(distance), 3)
		if distance <= 0.0:
			return
		cfg = self.config
		net.add_arc(
			Arc(
				i=i,
				j=j,
				kind=ARC_ROAD,
				distance=distance,
				travel_time=round(net.road_time(distance), 4),
				risk=net.road_risk(distance, cfg.pop_transport),
				cost=round(
					cfg.q
					* (cfg.road_cost_fixed + cfg.road_cost_per_km * distance)
					* cfg.hazmat_cost_factor,
					2,
				),
			)
		)

	def _add_link(self, net: FourLayerNetwork, i: str, j: str) -> None:
		"""站内连接弧：零里程、零时间、零风险、零成本，仅用于打通货场与车站。"""
		net.add_arc(
			Arc(i=i, j=j, kind=ARC_ROAD, distance=0.0, travel_time=0.0, risk=0.0, cost=0.0)
		)

	def _rail_endpoint(self, nid: str, side: str) -> str:
		"""车站节点编号：挂接货场的车站按到达侧/出发侧区分，其余为单节点。"""
		return f"L{nid}_{side}" if nid in self.yard_by_rail else f"L{nid}"

	def _add_rail(self, net: FourLayerNetwork, raw: dict, distance: float) -> None:
		i = self._rail_endpoint(raw["i"], "b")
		j = self._rail_endpoint(raw["j"], "a")
		for spec in self.config.service_types:
			net.add_arc(
				Arc(
					i=i,
					j=j,
					kind=ARC_RAIL,
					distance=distance,
					travel_time=round(net.rail_time(distance, spec.code), 4),
					risk=net.rail_risk(distance, self.config.pop_transport, spec.code),
					cost=0.0,
					service=spec.code,
					line=raw.get("line", ""),
				)
			)

	def _add_transfer(self, net: FourLayerNetwork, yard: Yard) -> None:
		cfg = self.config
		risk = (
			yard.node_risk(cfg.q, cfg.node_risk_theta, cfg.node_risk_rho, cfg.hazmat_risk_factor)
			if cfg.include_node_risk
			else 0.0
		)
		net.add_arc(
			Arc(
				i=yard.in_node,
				j=yard.out_node,
				kind=ARC_TRANSFER,
				distance=0.0,
				travel_time=0.0,
				risk=risk,
				cost=round(yard.transfer_cost(cfg.q), 2),
			)
		)

	# ------------------------------------------------------------------
	# 数据摘要
	# ------------------------------------------------------------------
	def _line_summary(self, payload: dict) -> dict:
		"""按线别汇总里程（正反向弧只计一次），便于核对算例与论文表 1 的一致性。"""
		summary: dict = {}
		seen: set = set()
		for arc in payload["rail_arcs"]:
			item = summary.setdefault(
				arc["line"],
				{
					"km": 0.0,
					"speed_factor": arc.get("speed_factor", 1.0),
					"exposure": arc.get("exposure", 1.0),
				},
			)
			key = (arc["line"], arc["i"], arc["j"])
			if key in seen:
				continue
			seen.add(key)
			seen.add((arc["line"], arc["j"], arc["i"]))
			item["km"] = round(item["km"] + float(arc["km"]), 3)
		return summary


# ----------------------------------------------------------------------
# 对外入口
# ----------------------------------------------------------------------
def load_real_case(config: UTRRConfig) -> CaseInstance:
	"""读取真实路网 JSON 并转换为四层网络算例。"""
	payload = read_payload(config.real_case_path)
	return RealCaseBuilder(config).build(payload)


def list_od_pairs(path: str) -> list:
	"""列出算例中全部 OD 对的概要（供 main.py 多 OD 遍历使用）。"""
	payload = read_payload(path)
	return [
		{
			"index": index,
			"id": od.get("id"),
			"hazmat": od.get("hazmat"),
			"demand_teu": od.get("demand_teu"),
			"origin": od.get("origin", {}).get("name"),
			"destination": od.get("destination", {}).get("name"),
			"task": od.get("task", ""),
		}
		for index, od in enumerate(payload.get("od_pairs", []))
	]
