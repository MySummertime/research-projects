"""铁路按箱分档费率与弧级边际增量成本（论文式（4）（5））。

费率取黄丽霞（2017）表 5-11（中国铁路 95306 运价口径）：40 ft 箱固定费率
680 元/箱、变动费率 2.754 元/(箱·km)，并按运量分 10/20/40 TEU 三档对固定、
变动费率乘以（1.00, 1.00）、（1.05, 0.80）、（1.10, 0.70）的规模经济系数。
"""

from __future__ import annotations

from config import UTRRConfig


class DecreasingTariff:
	"""按运量分档的线性费率函数 f(L) = b + a·L（元/箱）及其弧级折算。

	b = rail_cost_fixed × 固定费率倍数，a = rail_cost_per_km × 变动费率倍数；
	运量按 OD 给定，分档倍数在一个算例内是常数。式（5）的望远镜性质对线性
	f(L) 依然成立：首条铁路弧取 η_k·f(l_ij) 计入固定费用，其余取 η_k·[f(d+l)−f(d)]，
	沿路径累加后全程成本恰为 η_k·f(L)。
	"""

	def __init__(self, config: UTRRConfig):
		fixed_factor, variable_factor = config.volume_tier()
		self.a = float(config.rail_cost_per_km) * variable_factor
		self.a1 = self.a2 = self.a3 = self.a  # 兼容旧接口（成本下界/修正成本斜率）
		self.b1 = float(config.rail_cost_fixed) * fixed_factor
		self.b2 = self.b3 = self.b1
		self.fixed_factor = fixed_factor
		self.variable_factor = variable_factor
		if self.a <= 0.0 or self.b1 <= 0.0:
			raise ValueError("费率参数必须为正")

	def fare_per_ton(self, distance: float) -> float:
		"""返回运距 distance 下的全程单位运费 f(L)（元/箱）。"""
		length = max(0.0, float(distance))
		return self.a * length + self.b1

	def marginal_rate(self, distance: float) -> float:
		"""返回运距 distance 处的边际费率 f'(L)（元/(箱·km)）。"""
		return self.a

	def segment_cost(
		self,
		covered: float,
		segment: float,
		eta: float,
		quantity: float,
		first: bool | None = None,
	) -> float:
		"""按边际增量法折算单条铁路弧的成本（式（5））。

		covered 为该弧前（后）已累计的铁路运距 d_i；segment 为弧长 l_ij；
		eta 为服务类型成本系数 η_k；quantity 为运量 q（TEU）。
		"""
		is_first = (covered <= 0.0) if first is None else first
		if is_first:
			return eta * self.fare_per_ton(segment) * quantity
		return eta * (self.fare_per_ton(covered + segment) - self.fare_per_ton(covered)) * quantity

	def first_segment_cost(self, segment: float, eta: float, quantity: float) -> float:
		"""首条铁路弧成本 η_k·f(l_ij)·q。"""
		return eta * self.fare_per_ton(segment) * quantity

	def min_rate(self, eta: float = 1.0) -> float:
		"""返回单位运距成本下界 η·a（用于成本下界预计算）。"""
		return eta * self.a
