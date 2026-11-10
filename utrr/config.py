"""UTRR 模型参数与绘图常量。

UTRR = Uncertain Transfer time Road-Rail intermodal routing
论文：不确定转运时间与运到时限下危险货物公铁联运路径优化

本文件是本项目唯一的参数中枢：算例规模、成本/风险/时间参数、货场等级、
铁路服务类型、求解开关与绘图常量全部集中于此。main.py 与 sensitivity/ 下的
实验脚本只读取 UTRRConfig，不在别处硬编码数值。
"""

from __future__ import annotations

import copy
import json
import math
import os
from dataclasses import asdict, dataclass, field
from typing import Dict, List


INSTANCE_DATA_VERSION = "utrr-case-v2"

# ============================================================
# 路径中心（绝对路径，保证从任何工作目录启动脚本都能正确读写）
# ============================================================
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
RESULTS_ROOT = os.path.join(PROJECT_ROOT, "results")  # 每次实验生成 <实验名>_<时间戳> 子目录
INSTANCE_PATH = os.path.join(DATA_DIR, "case", "instance.json")  # 可选的外部算例文件

# 数据来源标识
DATA_SOURCE_REAL = "real"  # 真实路网（由 src/core/real_case.py 转换为四层网络）
DATA_SOURCE_SYNTHETIC = "synthetic"  # 合成算例（src/core/instance_generator.py）

# 真实路网 JSON：新疆—长三角算例（data/real_case_xj_yrd/build_network.py 生成）
REAL_CASE_PATH = os.path.join(DATA_DIR, "real_case_xj_yrd", "network.json")


# 置信水平模式下正态不确定变量的可靠度分位系数 λ_α
CONFIDENCE_MODE_NORMAL = "normal"  # λ_α = (√3/π)·ln(α/(1−α))

# 铁路服务类型的选择粒度
SERVICE_SELECTION_SEGMENT = "segment"  # 逐铁路弧独立选择（式（4）中 y_ij^k 的原始含义）
SERVICE_SELECTION_PATH = "path"  # 全路径统一服务类型（相当于附加 y_ij^k 不随弧变化的约束）


@dataclass(frozen=True)
class ServiceType:
	"""铁路班列服务类型 k ∈ K：集装箱班列、普快班列、快速班列。

	η_k 为服务类型成本系数（"成本系数"），κ_k 为服务类型风险系数（"风险系数"），
	两者均取黄丽霞（2017）表 5-10 的运输服务相关参数（依平均速度 60/50/80 km/h
	标定）；stop_hours 已随参数体系修订取消（时间为纯运行时间）。
	"""

	code: int
	name_cn: str
	name_en: str
	eta: float
	speed: float
	stop_hours: float
	risk_multiplier: float

	@property
	def short(self) -> str:
		"""用于表头与文件名的短名。"""
		return f"k{self.code}"


@dataclass(frozen=True)
class HazmatClass:
	"""危险货物类别（第 3、6、8 类）及其费用、风险修正系数。

	取值参照文献对桃浦、紫金山、吉山、黑石铺四个危险货物专办站 1990—1997 年
	分类运量的统计：第 3、6、8 类运量最大。费用系数体现包装、隔离、押运与
	应急要求，风险系数体现泄漏后的后果强度。
	"""

	code: int
	name_cn: str
	name_en: str
	cost_factor: float
	risk_factor: float


@dataclass(frozen=True)
class YardProfile:
	"""货场等级参数（论文表 1）。

	mu/sigma 为货场转运时间（正态不确定变量 N(e, σ)）的期望值与波动参数，
	unit_cost/fixed_cost 为转运作业成本，accident_prob/exposure 为节点风险的
	事故概率与暴露强度参数。
	"""

	name: str
	qualified: bool
	mu: float
	sigma: float
	unit_cost: float
	fixed_cost: float
	accident_prob: float
	exposure: float


@dataclass
class UTRRConfig:
	"""不确定转运时间下危险货物公铁联运路径优化问题的配置。"""

	# ============================================================
	# 算例与标识
	# ============================================================
	instance_name: str = INSTANCE_DATA_VERSION  # 写入实例文件的版本标识
	seed: int = 20261027  # 暴露系数抽样与规模算例生成的随机种子

	# ============================================================
	# 算例规模（4.1 基准算例 + 4.7 可扩展性算例）
	# ============================================================
	n_yards: int = 3  # 发送端候选货场数量（表 1 为 3 个）
	n_rail_layers: int = 6  # 铁路干线层数（每层为一批可并行的中间铁路节点）
	n_rail_rows: int = 2  # 每层铁路节点行数
	n_road_origin: int = 3  # 供应端公路节点数量
	n_road_destination: int = 3  # 需求端公路节点数量

	# ============================================================
	# 运量与运到时限
	# ============================================================
	q: float = 12.0  # 危险货物运输量（40 ft 箱数），单批次单品类
	alpha: float = 0.90  # 机会约束置信水平 α（基准值）
	confidence_mode: str = CONFIDENCE_MODE_NORMAL  # λ_α 的取值口径
	deadline_hours: float | None = 98.0  # 运到时限 D = 98 h（约 4 天，扫描择优）

	# ============================================================
	# 危险货物类别（上标 s）
	# ============================================================
	# 需求按 OD 指定品类，构算例时写入 hazmat_class；单算例内品类唯一。
	hazmat_classes: tuple = (
		HazmatClass(3, "第3类 易燃液体", "Class 3 flammable liquid", 1.50, 1.00),
		HazmatClass(6, "第6类 毒性物质", "Class 6 toxic substance", 2.00, 1.10),
		HazmatClass(8, "第8类 腐蚀性物质", "Class 8 corrosive substance", 1.50, 1.20),
	)
	hazmat_class: int = 8  # 当前算例的品类编码

	# ============================================================
	# 公路运输参数（上标 r）——黄丽霞（2017）表 5-11（95306 运价口径，元/箱）
	# ============================================================
	road_speed: float = 80.0  # 公路平均行驶速度（km/h）
	road_cost_fixed: float = 675.0  # 公路运输固定费率（元/箱）
	road_cost_per_km: float = 36.0  # 公路运输变动费率（元/(箱·km)）
	road_unit_acc_prob: float = 0.25e-6  # 单位公路运输事故概率（1/(箱·km)）

	# ============================================================
	# 铁路运输参数（上标 l, k）——黄丽霞（2017）表 5-11（95306 运价口径，元/箱）
	# ============================================================
	rail_cost_fixed: float = 680.0  # 铁路运输固定费率（元/箱，40 ft 箱运行基价）
	rail_cost_per_km: float = 2.754  # 铁路运输变动费率（元/(箱·km)，40 ft 箱发到基价）
	# 运量分档的规模经济效益：(运量上限/箱, 固定费率倍数, 变动费率倍数)
	# 依据 40 ft 集装箱运行基价与发到基价的分档折扣关系设定（黄丽霞表 5-11）。
	rail_volume_tiers: tuple = (
		(10.0, 1.00, 1.00),
		(20.0, 1.05, 0.80),
		(40.0, 1.10, 0.70),
	)
	rail_unit_acc_prob: float = 0.11e-6  # 单位铁路运输事故概率（1/(箱·km)）

	# 服务类型修正系数（成本系数：黄丽霞 2017 表 5-10；风险系数按在途暴露时间
	# 口径 κ = v基准/v_k 推导，基准 80 km/h，风险与在途暴露时间成正比）
	service_types: tuple = (
		ServiceType(0, "集装箱班列", "Container block train", 1.00, 60.0, 0.00, 1.33),
		ServiceType(1, "普快班列", "Ordinary express block train", 0.83, 50.0, 0.00, 1.60),
		ServiceType(2, "快速班列", "Fast express block train", 1.33, 80.0, 0.00, 1.00),
	)
	# 服务类型的选择粒度：segment 逐弧选择（默认，与式（4）一致）；
	# path 则整条路径只用一种服务类型，用于 4.6 节的服务类型对比。
	service_selection: str = SERVICE_SELECTION_SEGMENT

	# ============================================================
	# 货场中转参数（黄丽霞 2017 表 5-12、§5.5.2(9)）
	# ============================================================
	# 中转类型：origin=公→铁（发送货场装车）、transit=铁→铁（中转换装）、
	# destination=铁→公（到达货场卸车）。转运时间为正态不确定变量 N(e,σ)：
	# e 取黄丽霞的中转时间 4 h/8 h/批，σ 为算例设定值。
	transfer_time: tuple = (8.0, 4.0, 8.0)  # 转运时间期望 e（公铁、铁铁、铁公，h/批）
	transfer_sigma: float = 4.0  # 转运时间波动参数 σ（算例设定，h）
	transfer_cost_per_box: tuple = (500.0, 200.0, 500.0)  # 中转成本（元/箱）
	transfer_risk_factor: tuple = (1.0, 0.5, 1.0)  # 中转风险系数
	transfer_acc_prob: float = 422.61e-6  # 单位中转事故概率（1/次）
	pop_transport: float = 1.64e5  # 道路、铁路运输事故后果 POP（人）
	pop_transfer: float = 6.25e4  # 中转/暂存事故后果 POP（人）
	# 节点风险耦合系数（算例设定值）：(1+θμ+ρσ)，敏感性按 θ、ρ 双参数切片覆盖（4.5）
	node_risk_theta: float = 0.005
	node_risk_rho: float = 0.005

	# ============================================================
	# 网络几何（km，抽象坐标系：x 向东、y 向北）
	# ============================================================
	geometry_road_span: float = 70.0  # 供应端公路支线跨度
	geometry_yard_x: tuple = (95.0, 155.0)  # 发送端货场 x 区间
	geometry_rail_start_x: float = 200.0  # 铁路干线起点 x
	geometry_rail_layer_gap: float = 170.0  # 相邻铁路层间距
	geometry_rail_row_gap: float = 90.0  # 铁路行间距
	geometry_tail_road_length: float = 60.0  # 到达货场至需求点之间的接驳弧长

	# ============================================================
	# 求解开关
	# ============================================================
	include_node_risk: bool = True  # 是否计入货场节点转运风险（4.5 风险口径对比）
	bidirectional: bool = True  # 策略④：双向汇合
	enable_chance_pruning: bool = True  # 策略①：机会可行性剪枝
	enable_pruning: bool = True  # 策略③：下界剪枝（历史参数名，等价 bound pruning）
	enable_dominance: bool = True  # 策略②：Pareto 支配剪枝（关闭即全标号枚举）
	max_labels_per_node: int = 20000  # 单节点保留标号上限（保护性硬约束）
	max_solutions: int = 5000  # 终点 Pareto 解集规模上限
	tolerance: float = 1e-9  # 数值比较容差

	# ============================================================
	# 实验设置（4.2—4.7）
	# ============================================================
	alpha_grid: tuple = (0.50, 0.70, 0.80, 0.85, 0.90, 0.95, 0.99)  # 4.3 置信水平
	alpha_sweep: tuple = (0.50, 0.995, 25)  # 4.3 图 7 的扫描（下限、上限、点数）
	period_grid: tuple = (0.0, 2.0, 4.0, 6.0, 8.0)  # 4.4 转运时间波动 σ（h，案例设定档位，σ=0 为确定性情形）
	node_risk_theta_grid: tuple = (0.0, 0.005, 0.01)  # 4.5 θ 切片取值（0、基准、2 倍，h⁻¹）
	node_risk_rho_grid: tuple = (0.0, 0.005, 0.01)  # 4.5 ρ 切片取值（0、基准、2 倍，h⁻¹）
	demand_grid: tuple = (5.0, 8.0, 10.0, 12.0, 18.0, 20.0, 22.0, 30.0, 38.0, 40.0)  # 4.7 运量（箱，覆盖 10/20/40 箱分档边界）
	demand_override: float | None = None  # 运量显式覆盖（4.7 用，非 None 时取代 OD 定义的需求）
	deadline_scale_grid: tuple = (1.0, 1.2, 1.5)  # 4.6 时限严格度（相对基准 D）
	deadline_sweep: tuple = (0.80, 1.60, 17)  # 4.6 图 10 的时限扫描（下限、上限、点数）
	scalability_sizes: tuple = (  # 4.7 规模算例：(铁路层数, 行数, 发送端货场数)
		(4, 2, 3),
		(8, 2, 6),
		(12, 2, 9),
		(16, 3, 12),
	)
	# 4.7 完整枚举校验的节点数上限：≤ 该值时额外跑"关闭支配+剪枝"的完整枚举，
	# 验证本文算法前沿一致；52 节点约 2.0×10^6 标号/30 s，82 节点组合爆炸故不跑。
	# Full enumeration is retained only for genuinely small networks.  The
	# 52-node case is already large enough to generate millions of labels and
	# adds no correctness evidence beyond the 24- and 38-node checks.
	scalability_full_enum_max_nodes: int = 38
	sweep_weights: tuple = (0.0, 0.05, 0.1, 0.2, 0.35, 0.5, 0.65, 0.8, 0.9, 0.95, 1.0)
	# 4.7 加权和启发式基线使用的权重网格（权重作用于风险项）

	# ============================================================
	# 输出
	# ============================================================
	save_pdf: bool = False  # 是否同时输出矢量 PDF
	save_tiff: bool = True  # 是否同时输出 TIFF（期刊投稿常用位图格式）
	tiff_compression: str = "tiff_lzw"  # TIFF 压缩方式

	# ============================================================
	# 数据来源：真实路网（JSON）或合成算例
	# ============================================================
	data_source: str = DATA_SOURCE_REAL  # "real" | "synthetic"
	instance_file: str = ""  # 非空则直接读取该算例 JSON（绕过 data_source）
	real_case_path: str = REAL_CASE_PATH  # 真实路网 JSON
	real_case_od: int = 3  # 采用 od_pairs 中的第几条 OD（从 0 计）；基准算例为 OD4（短里程 vs 少转运权衡）
	# "calibrated" 用 deadline_factor × 最小可能时间；"window" 用 OD 自带时限；
	# "ratio" 用 OD 需求品类与里程推算的参照时限
	real_case_deadline_mode: str = "calibrated"
	real_case_min_deadline_hours: float = 12.0  # 时限下限，避免小时级算例出现负缓冲
	real_rail_min_length: float = 0.0  # 短于该长度的铁路弧视为站内作业予以忽略（km）

	# ============================================================
	# 派生量
	# ============================================================
	def lambda_alpha(self, alpha: float | None = None) -> float:
		"""返回可靠度分位系数 λ_α。

		正态不确定变量 N(e, σ) 的 α 分位数为 e + (√3/π)·σ·ln(α/(1−α))。
		"""
		a = float(self.alpha if alpha is None else alpha)
		if not 0.0 < a < 1.0:
			raise ValueError(f"置信水平必须位于 (0, 1)，当前为 {a}")
		return math.sqrt(3.0) / math.pi * math.log(a / (1.0 - a))

	def hazmat(self) -> HazmatClass:
		"""按品类编码返回危险货物类别参数。"""
		for spec in self.hazmat_classes:
			if spec.code == self.hazmat_class:
				return spec
		raise KeyError(f"未定义的危险货物类别编码：{self.hazmat_class}")

	@property
	def hazmat_name(self) -> str:
		return self.hazmat().name_cn

	@property
	def hazmat_cost_factor(self) -> float:
		"""品类费用修正系数（作用于铁路与公路运费）。"""
		return self.hazmat().cost_factor

	@property
	def hazmat_risk_factor(self) -> float:
		"""品类风险修正系数（作用于弧段风险与节点风险）。"""
		return self.hazmat().risk_factor

	@property
	def boxes(self) -> float:
		"""运量（40 ft 箱数）。"""
		return float(self.q)

	def volume_tier(self) -> tuple:
		"""返回运量分档对应的 (固定费率倍数, 变动费率倍数)。

		运量按 OD 指定，同一算例内为常数，故该倍数只改变费率函数的常数项，
		不引入新的标号维度，式（5）的望远镜性质保持不变。
		"""
		boxes = self.boxes
		last = self.rail_volume_tiers[-1]
		for upper, fixed, variable in self.rail_volume_tiers:
			if boxes <= upper:
				return fixed, variable
		return last[1], last[2]

	def service_type(self, code: int) -> ServiceType:
		"""按服务类型编码返回服务类型参数。"""
		for spec in self.service_types:
			if spec.code == code:
				return spec
		raise KeyError(f"未定义的服务类型编码：{code}")

	@property
	def service_codes(self) -> tuple:
		"""全部铁路服务类型编码。"""
		return tuple(spec.code for spec in self.service_types)

	@property
	def segment_service(self) -> bool:
		"""是否为逐弧选择服务类型（否则整条路径统一服务类型）。"""
		return self.service_selection == SERVICE_SELECTION_SEGMENT

	def service_name(self, code: int) -> str:
		"""服务类型编码转中文名；编码为负表示多种服务类型混编。"""
		if code is None or code < 0:
			return "混编"
		return self.service_type(code).name_cn

	def with_overrides(self, **kwargs) -> "UTRRConfig":
		"""返回带指定覆盖项的新配置（用于敏感性实验，避免污染基准配置）。"""
		clone = copy.deepcopy(self)
		for key, value in kwargs.items():
			if not hasattr(clone, key):
				raise AttributeError(f"未知配置项：{key}")
			setattr(clone, key, value)
		return clone

	def to_dict(self) -> dict:
		"""转为字典，向量类型转成列表以便 JSON 序列化。"""
		data = asdict(self)
		for key, value in list(data.items()):
			if isinstance(value, tuple):
				data[key] = list(value)
		return data

	def save_to_json(self, filepath: str) -> None:
		"""将模型配置与绘图配置写入同一个 JSON 文件。"""
		visual = {
			key: value
			for key, value in vars(PlotProperties).items()
			if not key.startswith("_") and not callable(value)
		}
		payload = {"model_config": self.to_dict(), "visual_config": visual}
		with open(filepath, "w", encoding="utf-8") as handle:
			json.dump(payload, handle, indent=4, ensure_ascii=False)


class ColorPalette:
	"""学术图形配色：以灰度为主、便于黑白印刷，彩色仅作辅助区分。"""

	DEFAULT_BLACK = "#000000"
	DEFAULT_GRAY = "#999999"
	DEFAULT_WHITE = "#FFFFFF"

	TERRACOTTA = "#C26B48"
	CELADON = "#94C1B7"
	SAGE_GREEN = "#ABBCAA"
	WARM_SAND = "#DDBF91"
	PALE_LIME = "#DDE4B6"
	SLATE = "#5B6770"

	# 网络要素
	NETWORK_TOPOLOGY: List[Dict[str, str]] = [
		{"ROAD": "#7F7F7F"},
		{"RAIL": "#000000"},
		{"TRANSFER": TERRACOTTA},
		{"CLIENT": "#000000"},
		{"YARD": WARM_SAND},
		{"RAIL_NODE": "#FFFFFF"},
	]

	# 方案对比 / 系列曲线
	SERIES: List[str] = [DEFAULT_BLACK, SLATE, TERRACOTTA, CELADON, SAGE_GREEN, WARM_SAND]
	SERIES_MARKERS: List[str] = ["o", "s", "^", "D", "v", "P"]
	SERIES_LINESTYLES: List[str] = ["-", "--", "-.", ":", (0, (5, 2)), (0, (1, 1))]

	# 风险构成堆叠柱
	RISK_ARC = "#7F7F7F"
	RISK_NODE = TERRACOTTA


def get_color_by_key(config_list: List[Dict[str, str]], key: str) -> str:
	"""按键名取出颜色值。"""
	for item in config_list:
		if key in item:
			return item[key]
	raise KeyError(f"配色表中不存在键：{key}")


class PlotProperties:
	"""统一的绘图参数与样式常量（按《交通运输工程学报》单栏 7.0 cm 图宽设计）。"""

	# 字体：中文仿宋、西文/数字/数学 Times New Roman（paper-figures）
	FONT_FAMILY_EN = "Times New Roman"
	FONT_FAMILY_CN = "FangSong"
	FONT_SIZE_TITLE = 9.0
	FONT_SIZE_AXIS_LABEL = 8.5
	FONT_SIZE_TICK = 7.5
	FONT_SIZE_LEGEND = 7.5
	FONT_SIZE_ANNOTATION = 7.0
	FONT_SIZE_BASE = 8.0

	# 画布：单栏 7.0 cm，双栏 14.5 cm
	FIG_WIDTH_CM_SINGLE = 7.0
	FIG_WIDTH_CM_DOUBLE = 14.5
	FIG_WIDTH_CM_FULL = 16.59  # 通栏（双栏排版占双栏）文字宽度：9404 twips
	CM_PER_INCH = 2.54
	FIG_ASPECT = 0.78
	DPI = 1000  # paper-figures：TIFF/PNG 均 1000 dpi、透明底
	PAD_INCHES = 0.04

	# 线型与标记
	SPINE_LINE_WIDTH = 0.8
	TICK_LENGTH = 2.5
	TICK_WIDTH = 0.8
	LINE_WIDTH = 1.2
	LINE_WIDTH_AUX = 0.9
	MARKER_SIZE = 4.0
	GRID_LINE_STYLE = "--"
	GRID_ALPHA = 0.35
	GRID_LINE_WIDTH = 0.5

	# 网络图
	NODE_SIZE_CLIENT = 55.0
	NODE_SIZE_YARD = 42.0
	NODE_SIZE_RAIL = 26.0
	NODE_SIZE_ROAD = 18.0
	NODE_LINE_WIDTH = 0.9
	EDGE_WIDTH_ROAD = 0.9
	EDGE_WIDTH_RAIL = 1.4
	EDGE_ALPHA = 0.55
	EDGE_ALPHA_HIGHLIGHT = 0.95

	# 图题（置于图下方，中英对照）
	CAPTION_CN = ""
	CAPTION_EN = ""
	CAPTION_PAD = 0.02
