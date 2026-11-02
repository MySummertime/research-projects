"""算例生成：北方能源化工基地至华东化工需求地的危险货物公铁联运场景（论文 4.1）。

网络按四层结构构造：
	供应点 o → 公路节点 → 发送端候选货场（表 1 的 S1—S3） → 铁路干线 → 到达货场 S0
	→ 公路节点 → 需求点 d

铁路干线与公路支线均按抽象坐标（x 向东、y 向北，单位 km）构造，弧长为节点间
欧氏距离；暴露系数按 (种子, 弧标识) 稳定抽样，保证算例可复现。
"""

from __future__ import annotations

import heapq
import json
import math
import random
import zlib
from dataclasses import dataclass, replace

from config import INSTANCE_DATA_VERSION, UTRRConfig, YardProfile
from src.core.network import (
	ARC_RAIL,
	ARC_ROAD,
	ARC_TRANSFER,
	LAYER_CLIENT,
	LAYER_RAIL,
	LAYER_ROAD,
	LAYER_YARD,
	SIDE_DESTINATION,
	SIDE_ORIGIN,
	Arc,
	FourLayerNetwork,
	Node,
	Yard,
)


@dataclass
class CaseInstance:
	"""算例实例：网络 + 时限 + 元数据。"""

	network: FourLayerNetwork
	deadline: float
	alpha: float
	name: str
	metadata: dict

	def summary(self) -> dict:
		info = {
			"name": self.name,
			"deadline_hours": round(self.deadline, 3),
			"alpha": self.alpha,
			"quantity_t": self.network.config.q,
		}
		info.update(self.network.counts())
		info.update(self.metadata)
		return info


class InstanceGenerator:
	"""按 UTRRConfig 构造基准算例与规模扩展算例。"""

	def __init__(self, config: UTRRConfig):
		self.config = config

	def build(
		self,
		n_yards: int | None = None,
		n_rail_layers: int | None = None,
		n_rail_rows: int | None = None,
		deadline_factor: float | None = None,
		deadline_override: float | None = None,
		sigma_scale: float = 1.0,
		name: str | None = None,
	) -> CaseInstance:
		"""构造算例网络并标定运到时限。

		sigma_scale : 货场转运时间波动参数的整体缩放系数（4.4 波动敏感性），
			取 0 即"按期望值决策"的确定型模型。
		deadline_override : 直接指定 D（用于在波动/风险口径实验间保持时限不变）。
		"""
		cfg = self.config
		yards_count = int(n_yards or cfg.n_yards)
		layers = int(n_rail_layers or cfg.n_rail_layers)
		rows = int(n_rail_rows or cfg.n_rail_rows)

		net = FourLayerNetwork(cfg)
		net.origin = "o"
		net.destination = "d"

		# ---------------- 客户层 ----------------
		rail_end_x = cfg.geometry_rail_start_x + (layers - 1) * cfg.geometry_rail_layer_gap
		net.add_node(Node("o", LAYER_CLIENT, 0.0, 0.0, "供应点", SIDE_ORIGIN))
		net.add_node(
			Node(
				"d",
				LAYER_CLIENT,
				rail_end_x + 2.0 * cfg.geometry_tail_road_length + 100.0,
				0.0,
				"需求点",
				SIDE_DESTINATION,
			)
		)

		# ---------------- 公路层：供应端 ----------------
		origin_roads = self._road_chain(
			net,
			prefix="R",
			count=cfg.n_road_origin,
			x_start=cfg.geometry_road_span * 0.25,
			x_end=cfg.geometry_road_span * 0.75,
			y_spread=70.0,
		)

		# ---------------- 转运层：发送端候选货场 ----------------
		yard_specs = self._yard_specs(yards_count)
		yard_positions = []
		for index, spec in enumerate(yard_specs):
			x = cfg.geometry_yard_x[0] + (cfg.geometry_yard_x[1] - cfg.geometry_yard_x[0]) * (
				index / max(1, yards_count - 1)
			)
			y = 45.0 - 45.0 * (index % 3)
			yard_positions.append((spec, x, y))

		# ---------------- 铁路层 ----------------
		rail_nodes = []
		for layer in range(layers):
			for row in range(rows):
				node_id = f"L{layer + 1}{chr(ord('a') + row)}"
				x = cfg.geometry_rail_start_x + layer * cfg.geometry_rail_layer_gap
				y = (row - (rows - 1) / 2.0) * cfg.geometry_rail_row_gap
				net.add_node(Node(node_id, LAYER_RAIL, x, y, f"铁路节点{layer + 1}{row + 1}"))
				rail_nodes.append((layer, row, node_id))

		# ---------------- 转运层：到达货场 ----------------
		arrival = self._role_profile("destination")
		arrival_x = rail_end_x + cfg.geometry_tail_road_length
		net.add_node(Node("S0_in", LAYER_YARD, arrival_x, 0.0, "到达货场入口", SIDE_DESTINATION, "S0", "in"))
		net.add_node(Node("S0_out", LAYER_YARD, arrival_x + 5.0, 0.0, "到达货场出口", SIDE_DESTINATION, "S0", "out"))
		net.add_yard(Yard("S0", "S0_in", "S0_out", True, arrival["mu"], arrival["sigma"],
						 arrival["unit_cost"], arrival["fixed_cost"], arrival["accident_prob"], arrival["exposure"]))

		# ---------------- 公路层：需求端 ----------------
		destination_roads = self._road_chain(
			net,
			prefix="Q",
			count=cfg.n_road_destination,
			x_start=arrival_x + cfg.geometry_tail_road_length * 0.9,
			x_end=arrival_x + cfg.geometry_tail_road_length * 1.9,
			y_spread=60.0,
		)

		# ---------------- 弧：公路接驳 ----------------
		for node_id in origin_roads:
			self._add_road(net, "o", node_id)
			self._add_road(net, node_id, "o")
		for left, right in zip(origin_roads, origin_roads[1:]):
			self._add_road(net, left, right)
			self._add_road(net, right, left)

		# 货场节点（发送端）
		for spec, x, y in yard_positions:
			in_id, out_id = f"{spec.name}_in", f"{spec.name}_out"
			net.add_node(Node(in_id, LAYER_YARD, x, y, f"{spec.name}入口", SIDE_ORIGIN, spec.name, "in"))
			net.add_node(Node(out_id, LAYER_YARD, x + 5.0, y, f"{spec.name}出口", SIDE_ORIGIN, spec.name, "out"))
			net.add_yard(Yard(spec.name, in_id, out_id, spec.qualified, spec.mu, spec.sigma,
							  spec.unit_cost, spec.fixed_cost, spec.accident_prob, spec.exposure))
			# 公路接入：由最近的若干公路节点接入货场入口
			for road_id in self._nearest(origin_roads, net, in_id, k=2):
				self._add_road(net, road_id, in_id)

		# 需求端货场出口接公路
		for road_id in destination_roads:
			self._add_road(net, "S0_out", road_id)
			self._add_road(net, road_id, "d")

		# ---------------- 弧：转运虚拟弧 ----------------
		if abs(sigma_scale - 1.0) > 1e-12:
			for yard_name, yard in list(net.yards.items()):
				net.yards[yard_name] = replace(yard, sigma=yard.sigma * sigma_scale)
		for yard in net.yards.values():
			if yard.qualified:
				self._add_transfer(net, yard)
			# 不具备资质的货场不生成转运虚拟弧（货场兼容性剪枝，Step 1 预处理）

		# ---------------- 弧：铁路运输 ----------------
		first_layer = [(row, nid) for layer, row, nid in rail_nodes if layer == 0]
		for spec, x, y in yard_positions:
			out_id = f"{spec.name}_out"
			if not spec.qualified:
				continue
			for row, rail_id in first_layer:
				if abs(net.nodes[rail_id].y - y) <= cfg.geometry_rail_row_gap * 1.6:
					self._add_rail(net, out_id, rail_id)

		by_layer: dict[int, list] = {}
		for layer, row, node_id in rail_nodes:
			by_layer.setdefault(layer, []).append((row, node_id))
		for layer in range(layers - 1):
			for row, node_id in by_layer[layer]:
				for next_row, next_id in by_layer[layer + 1]:
					if abs(next_row - row) <= 1:
						self._add_rail(net, node_id, next_id)

		for row, node_id in by_layer[layers - 1]:
			self._add_rail(net, node_id, "S0_in")

		# ---------------- 运到时限标定 ----------------
		lam = cfg.lambda_alpha()
		reference = self._min_equivalent_time(net, lam)
		factor = float(deadline_factor if deadline_factor is not None else 1.2)
		if deadline_override is not None:
			deadline = float(deadline_override)
		elif cfg.deadline_hours:
			deadline = float(cfg.deadline_hours)
		else:
			deadline = reference * factor

		metadata = {
			"description": "北方能源化工基地至华东化工需求地危险货物公铁联运算例",
			"n_rail_layers": layers,
			"n_rail_rows": rows,
			"n_yards": yards_count,
			"min_equivalent_time_hours": round(reference, 4),
			"deadline_factor": factor,
			"lambda_alpha": round(lam, 6),
			"confidence_mode": cfg.confidence_mode,
		}
		instance = CaseInstance(net, deadline, cfg.alpha, name or INSTANCE_DATA_VERSION, metadata)
		instance.metadata["counts"] = net.counts()
		return instance

	# ------------------------------------------------------------------
	# 内部构造工具
	# ------------------------------------------------------------------
	def _road_chain(
		self,
		net: FourLayerNetwork,
		prefix: str,
		count: int,
		x_start: float,
		x_end: float,
		y_spread: float,
	) -> list:
		"""生成供应端/需求端的公路节点序列（节点直接加入网络）。"""
		nodes = []
		for index in range(count):
			frac = (index + 1) / (count + 1)
			x = x_start + (x_end - x_start) * frac
			y = (index - (count - 1) / 2.0) * (y_spread / max(1, count - 1)) * 2.0
			node_id = f"{prefix}{index + 1}"
			net.add_node(Node(node_id, LAYER_ROAD, round(x, 3), round(y, 3), f"公路节点{index + 1}"))
			nodes.append(node_id)
		return nodes

	def _yard_specs(self, count: int) -> list:
		"""按中转角色参数扩展发送货场规格（公→铁 角色，含班列衔接等待）。"""
		cfg = self.config
		base = self._role_profile("origin")
		specs = []
		for index in range(count):
			name = f"S{index + 1}"
			specs.append(
				YardProfile(
					name,
					True,
					base["mu"],
					base["sigma"],
					base["unit_cost"],
					base["fixed_cost"],
					base["accident_prob"],
					base["exposure"],
				)
			)
		return specs

	def _role_profile(self, side: str) -> dict:
		"""中转角色参数（黄丽霞表 5-12）：e 取 8/4/8 h，σ 为算例设定值。"""
		cfg = self.config
		idx = {"origin": 0, "transit": 1, "destination": 2}[side]
		return {
			"mu": float(cfg.transfer_time[idx]),
			"sigma": float(cfg.transfer_sigma),
			"unit_cost": float(cfg.transfer_cost_per_box[idx]),
			"fixed_cost": 0.0,
			"accident_prob": cfg.transfer_acc_prob * cfg.transfer_risk_factor[idx],
			"exposure": cfg.pop_transfer,
		}

	def _nearest(self, candidates: list, net: FourLayerNetwork, target: str, k: int) -> list:
		ranked = sorted(candidates, key=lambda node: net.distance_between(node, target))
		return ranked[:k]

	def _add_road(self, net: FourLayerNetwork, i: str, j: str) -> None:
		distance = round(net.distance_between(i, j), 3)
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

	def _add_rail(self, net: FourLayerNetwork, i: str, j: str) -> None:
		distance = round(net.distance_between(i, j), 3)
		if distance <= 0.0:
			return
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
				)
			)

	def _add_transfer(self, net: FourLayerNetwork, yard: Yard) -> None:
		cfg = self.config
		risk = yard.node_risk(
			cfg.q, cfg.node_risk_theta, cfg.node_risk_rho, cfg.hazmat_risk_factor
		)
		if not cfg.include_node_risk:
			risk = 0.0
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
	# 时限标定
	# ------------------------------------------------------------------
	def _min_equivalent_time(self, net: FourLayerNetwork, lam: float) -> float:
		"""以 t_ij（公路/铁路）与 μ_i + λ_α·σ_i（转运虚拟弧）为权的 Dijkstra。"""
		return net.min_equivalent_time(lam)


# ----------------------------------------------------------------------
# 序列化
# ----------------------------------------------------------------------
def instance_to_dict(instance: CaseInstance) -> dict:
	"""把算例转为可写入 JSON 的字典。"""
	net = instance.network
	cfg = net.config
	return {
		"name": instance.name,
		"version": cfg.instance_name,
		"origin": net.origin,
		"destination": net.destination,
		"deadline_hours": round(instance.deadline, 6),
		"alpha": instance.alpha,
		"quantity_t": cfg.q,
		"metadata": instance.metadata,
		"network": {
			"nodes": [
				{
					"id": node.node_id,
					"layer": node.layer,
					"x": node.x,
					"y": node.y,
					"name": node.name,
					"side": node.side,
					"yard": node.yard,
					"port": node.port,
				}
				for node in net.nodes.values()
			],
			"arcs": [
				{
					"i": arc.i,
					"j": arc.j,
					"kind": arc.kind,
					"distance": arc.distance,
					"travel_time": arc.travel_time,
					"risk": arc.risk,
					"cost": arc.cost,
					"service": arc.service,
				}
				for arc in net.arcs
			],
			"yards": [
				{
					"name": yard.name,
					"in_node": yard.in_node,
					"out_node": yard.out_node,
					"qualified": yard.qualified,
					"mu": yard.mu,
					"sigma": yard.sigma,
					"unit_cost": yard.unit_cost,
					"fixed_cost": yard.fixed_cost,
					"accident_prob": yard.accident_prob,
					"exposure": yard.exposure,
				}
				for yard in net.yards.values()
			],
			"counts": net.counts(),
		},
		"service_types": [
			{
				"code": spec.code,
				"name_cn": spec.name_cn,
				"name_en": spec.name_en,
				"eta": spec.eta,
				"speed": spec.speed,
				"stop_hours": spec.stop_hours,
				"risk_multiplier": spec.risk_multiplier,
			}
			for spec in cfg.service_types
		],
	}


def instance_from_dict(payload: dict, config: UTRRConfig) -> CaseInstance:
	"""从字典重建算例（用于 --mode solve 读取已生成的实例）。"""
	net = FourLayerNetwork(config)
	net.origin = payload["origin"]
	net.destination = payload["destination"]
	for node in payload["network"]["nodes"]:
		net.add_node(
			Node(
				node_id=node["id"],
				layer=node["layer"],
				x=float(node["x"]),
				y=float(node["y"]),
				name=node.get("name", ""),
				side=node.get("side", SIDE_ORIGIN),
				yard=node.get("yard"),
				port=node.get("port"),
			)
		)
	for yard in payload["network"]["yards"]:
		net.add_yard(
			Yard(
				name=yard["name"],
				in_node=yard["in_node"],
				out_node=yard["out_node"],
				qualified=bool(yard["qualified"]),
				mu=float(yard["mu"]),
				sigma=float(yard["sigma"]),
				unit_cost=float(yard["unit_cost"]),
				fixed_cost=float(yard["fixed_cost"]),
				accident_prob=float(yard["accident_prob"]),
				exposure=float(yard["exposure"]),
			)
		)
	for arc in payload["network"]["arcs"]:
		net.add_arc(
			Arc(
				i=arc["i"],
				j=arc["j"],
				kind=arc["kind"],
				distance=float(arc["distance"]),
				travel_time=float(arc["travel_time"]),
				risk=float(arc["risk"]),
				cost=float(arc["cost"]),
				service=arc.get("service"),
			)
		)
	return CaseInstance(
		network=net,
		deadline=float(payload["deadline_hours"]),
		alpha=float(payload.get("alpha", config.alpha)),
		name=payload.get("name", config.instance_name),
		metadata=payload.get("metadata", {}),
	)


def save_instance(instance: CaseInstance, directory: str) -> str:
	"""把算例写入 directory/instance.json，并导出 csv 便于查看。"""
	import os

	os.makedirs(directory, exist_ok=True)
	payload = instance_to_dict(instance)
	path = os.path.join(directory, "instance.json")
	with open(path, "w", encoding="utf-8") as handle:
		json.dump(payload, handle, indent=2, ensure_ascii=False)

	import csv

	for key, rows in (
		("nodes", payload["network"]["nodes"]),
		("arcs", payload["network"]["arcs"]),
		("yards", payload["network"]["yards"]),
	):
		if not rows:
			continue
		with open(os.path.join(directory, f"{key}.csv"), "w", newline="", encoding="utf-8-sig") as handle:
			writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
			writer.writeheader()
			writer.writerows(rows)
	return path


def load_instance(path: str, config: UTRRConfig) -> CaseInstance:
	"""读取 instance.json。"""
	with open(path, encoding="utf-8") as handle:
		return instance_from_dict(json.load(handle), config)
