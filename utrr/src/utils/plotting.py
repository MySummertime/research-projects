"""出版级绘图：四层网络、Pareto 前沿、敏感性曲线与算法性能图。

规格按 paper-figures：《交通运输工程学报》单栏图宽 7.0 cm、1000 dpi、透明底
TIFF+PNG；图内不写标题与图名；需区分系列时给完整无框图例；刻度朝内；
中文仿宋、数字/拉丁/数学 Times New Roman（mathtext）。图内数据点注释可用 $M$ 表示运到时限可靠度，坐标轴与图例使用“可靠度”全称。
"""

from __future__ import annotations

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.patheffects as path_effects  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.legend_handler import HandlerTuple  # noqa: E402
from matplotlib.ticker import MultipleLocator  # noqa: E402
from matplotlib.transforms import Bbox  # noqa: E402

from config import ColorPalette, PlotProperties  # noqa: E402
from src.core.network import LAYER_CLIENT, LAYER_RAIL, LAYER_ROAD, LAYER_YARD  # noqa: E402

# 节点的绘制次序：客户点最后画，避免被同址的货场方框盖住
_LAYER_ZORDER = {LAYER_ROAD: 0, LAYER_RAIL: 1, LAYER_YARD: 2, LAYER_CLIENT: 3}


class Visualizer:
	"""统一风格的学术图形生成器。"""

	def __init__(self, config):
		self.config = config
		self._apply_style()

	# ------------------------------------------------------------------
	# 基础设置
	# ------------------------------------------------------------------
	def _apply_style(self) -> None:
		plt.rcParams.update(
			{
				# 中文用仿宋；数字、英文字母与数学符号统一走 mathtext（Times New Roman）。
				# 混排（中文+mathtext）时双字体族回退会丢中文字形，文本族只留 FangSong。
				"font.family": ["FangSong"],
				"mathtext.fontset": "custom",
				"mathtext.rm": "Times New Roman",
				"mathtext.it": "Times New Roman:italic",
				"mathtext.bf": "Times New Roman:bold",
				"mathtext.sf": "Times New Roman",
				"mathtext.tt": "Times New Roman",
				"mathtext.cal": "Times New Roman",
				"font.size": PlotProperties.FONT_SIZE_BASE,
				"axes.labelsize": PlotProperties.FONT_SIZE_AXIS_LABEL,
				"axes.titlesize": PlotProperties.FONT_SIZE_TITLE,
				"xtick.labelsize": PlotProperties.FONT_SIZE_TICK,
				"ytick.labelsize": PlotProperties.FONT_SIZE_TICK,
				"legend.fontsize": PlotProperties.FONT_SIZE_LEGEND,
				"xtick.direction": "in",
				"ytick.direction": "in",
				"axes.unicode_minus": False,
				"axes.grid": True,
				"grid.linestyle": PlotProperties.GRID_LINE_STYLE,
				"grid.alpha": PlotProperties.GRID_ALPHA,
				"grid.linewidth": PlotProperties.GRID_LINE_WIDTH,
				"savefig.dpi": PlotProperties.DPI,
				"savefig.bbox": "tight",
				"savefig.pad_inches": PlotProperties.PAD_INCHES,
				"figure.dpi": 120,
			}
		)

	def _figure(self, width_cm: float, aspect: float = None):
		width = width_cm / PlotProperties.CM_PER_INCH
		height = width * (aspect if aspect else PlotProperties.FIG_ASPECT)
		return plt.figure(figsize=(width, height))

	@staticmethod
	def _style_axes(ax) -> None:
		ax.spines["top"].set_visible(False)
		ax.spines["right"].set_visible(False)
		ax.spines["bottom"].set_linewidth(PlotProperties.SPINE_LINE_WIDTH)
		ax.spines["left"].set_linewidth(PlotProperties.SPINE_LINE_WIDTH)
		ax.tick_params(
			direction="in",
			length=PlotProperties.TICK_LENGTH,
			width=PlotProperties.TICK_WIDTH,
			pad=2,
			labelsize=PlotProperties.FONT_SIZE_TICK,
		)
		# 数字刻度走 mathtext（Times New Roman）；已手工设定标签的轴不覆盖
		from matplotlib.ticker import FixedFormatter, FuncFormatter
		formatter = FuncFormatter(lambda v, _: f"${v:g}$")
		if not isinstance(ax.xaxis.get_major_formatter(), FixedFormatter):
			ax.xaxis.set_major_formatter(formatter)
		if not isinstance(ax.yaxis.get_major_formatter(), FixedFormatter):
			ax.yaxis.set_major_formatter(formatter)

	@staticmethod
	def _times_tick_font():
		from matplotlib import font_manager

		# 右轴刻度只用数字/小数点，直接绑 Times New Roman，避开 twinx+FangSong 回退无衬线
		path = font_manager.findfont("Times New Roman")
		return font_manager.FontProperties(fname=path, size=PlotProperties.FONT_SIZE_TICK)

	@classmethod
	def _style_twin_y(cls, ax2) -> None:
		"""右轴：刻度朝内；数字强制 Times New Roman，与左轴 mathtext 观感一致。"""
		ax2.spines["top"].set_visible(False)
		ax2.spines["right"].set_linewidth(PlotProperties.SPINE_LINE_WIDTH)
		ax2.tick_params(
			direction="in",
			length=PlotProperties.TICK_LENGTH,
			width=PlotProperties.TICK_WIDTH,
			pad=2,
			labelsize=PlotProperties.FONT_SIZE_TICK,
		)
		ax2.grid(False)
		ylim = ax2.get_ylim()
		yticks = [t for t in ax2.get_yticks() if ylim[0] <= t <= ylim[1]]
		ax2.set_yticks(yticks)
		# 用 $...$ 走 mathtext；再显式设 TNR，防止 secondary axis 掉字体
		fp = cls._times_tick_font()
		ax2.set_yticklabels([f"${t:g}$" for t in yticks], fontproperties=fp)

	def _save(self, fig, path: str) -> list:
		"""保存图片并返回生成的文件列表。

		图内不写标题与图名——图题统一由 Word 排版层在图下给出（中文在上、英文在下），
		避免图片裁切或缩放后图题错位、重复。
		"""
		os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
		base, _ = os.path.splitext(path)
		outputs = [f"{base}.png"]
		fig.savefig(f"{base}.png", dpi=PlotProperties.DPI, transparent=True)
		if getattr(self.config, "save_tiff", False):
			# 位图投稿格式：与 PNG 一致，保留透明通道（RGBA），LZW 压缩
			fig.savefig(
				f"{base}.tiff",
				dpi=PlotProperties.DPI,
				transparent=True,
				edgecolor="none",
				pil_kwargs={"compression": getattr(self.config, "tiff_compression", "tiff_lzw")},
			)
			outputs.append(f"{base}.tiff")
		if self.config.save_pdf:
			fig.savefig(f"{base}.pdf", transparent=True)
			outputs.append(f"{base}.pdf")
		plt.close(fig)
		return outputs

	# ------------------------------------------------------------------
	# 附图 S1：真实路网（论文图 1 为手绘四层网络示意图，不由此代码生成）
	# ------------------------------------------------------------------
	# 长三角汇集区放大插图的中心与跨度（°）、相对主图的放大倍数
	INSET_CENTER = (119.9, 31.25)
	INSET_SPAN = (5.6, 4.0)
	INSET_ZOOM = 2.2

	# 各标注的偏移（点）：真实路网中同一城市的车站与货场常常重合，逐个手工标定
	# 方位比自动搜索更稳；表内的标注直接按此放置，表外者回退到下面的候选表搜索。
	# 值形如 (dx, dy, 引线)——第三项为 True 时画一条细引线指向节点。
	LABEL_PREFERENCE = {
		"供应点 o": (0, -17, False),
		"奎屯": (0, 24, True),
		"石河子": (0, 12, True),
		"乌鲁木齐西": (11, 4, True),
		"兰州北": (0, 11, False),
		"西安": (0, 11, False),
		"郑州北": (0, 11, False),
		"商丘": (0, -14, False),
		"南京东": (0, 11, False),
		"芜湖": (-8, -14, False),
		"上海桃浦": (0, 12, False),
		"需求点 d": (0, -15, False),
	}

	# 标注位置的候选偏移（点）：依次尝试，取第一个不与已有标注冲突且不出画布者
	LABEL_OFFSETS = (
		(0, 9),
		(0, -11),
		(9, 3),
		(-9, 3),
		(9, -9),
		(-9, -9),
		(0, 18),
		(0, -20),
		(15, 0),
		(-15, 0),
		(14, 12),
		(-14, 12),
		(14, -14),
		(-14, -14),
		(0, 17),
		(0, 26),
		(0, -26),
		(22, 8),
		(-22, 8),
		(22, -10),
		(-22, -10),
	)

	def _anchor_label(self, ax, text, x, y, dx, dy, leader=False) -> None:
		"""按手工标定的偏移放置一条标注。"""
		ha = "center" if dx == 0 else ("left" if dx > 0 else "right")
		props = None
		if leader:
			props = dict(
				arrowstyle="-",
				color=ColorPalette.DEFAULT_BLACK,
				lw=0.45,
				shrinkA=2.0,
				shrinkB=4.5,
				alpha=0.75,
			)
		ann = ax.annotate(
			text,
			(x, y),
			textcoords="offset points",
			xytext=(dx, dy),
			ha=ha,
			va="baseline",
			fontsize=PlotProperties.FONT_SIZE_ANNOTATION,
			arrowprops=props,
			zorder=6,
		)
		ann.set_path_effects([path_effects.withStroke(linewidth=2.2, foreground="white")])

	def _place_labels(self, ax, entries, obstacles=()) -> None:
		"""按优先级放置标注，自动避让重叠与画布越界。

		entries 为 (文本, x, y, 优先偏移序列)；obstacles 为 (x, y, 标记尺寸) 的
		障碍点序列——节点标记本身也算占位，避免文字压在方框上。逐个尝试候选偏移，
		若全部冲突则略去该标注：宁可少标一个车站，也不让文字叠成一团。
		"""
		fig = ax.figure
		fig.canvas.draw()
		renderer = fig.canvas.get_renderer()
		# 以坐标区（而非整幅画布）为边界，避免标注压到刻度数字与轴标题
		frame = ax.get_window_extent(renderer=renderer)
		placed: list = []
		for x, y, size in obstacles:
			px, py = ax.transData.transform((x, y))
			radius = (float(size) ** 0.5) * 0.5 * fig.dpi / 72.0 + 1.0
			placed.append(Bbox.from_extents(px - radius, py - radius, px + radius, py + radius))
		for text, x, y, offsets in entries:
			for dx, dy in tuple(offsets) + self.LABEL_OFFSETS:
				ha = "center" if dx == 0 else ("left" if dx > 0 else "right")
				# 偏移较远时补一条细引线，避免读者分不清注记归属
				leader = None
				if (dx * dx + dy * dy) ** 0.5 > 13.0:
					leader = dict(
						arrowstyle="-",
						color=ColorPalette.DEFAULT_BLACK,
						lw=0.45,
						shrinkA=2.0,
						shrinkB=4.5,
						alpha=0.75,
					)
				ann = ax.annotate(
					text,
					(x, y),
					textcoords="offset points",
					xytext=(dx, dy),
					ha=ha,
					va="baseline",
					fontsize=PlotProperties.FONT_SIZE_ANNOTATION,
					arrowprops=leader,
					zorder=6,
				)
				# 白色描边保证注记压在线网之上仍可辨认
				ann.set_path_effects(
					[path_effects.withStroke(linewidth=2.2, foreground="white")]
				)
				bbox = ann.get_window_extent(renderer=renderer)
				inside = (
					bbox.x0 >= frame.x0 + 1.5
					and bbox.x1 <= frame.x1 - 1.5
					and bbox.y0 >= frame.y0 + 1.5
					and bbox.y1 <= frame.y1 - 1.5
				)
				if inside and not any(bbox.overlaps(other) for other in placed):
					if os.environ.get("UTRR_DEBUG_LABELS"):
						print(f"  OK  {text:>8s} {(dx, dy)}")
					placed.append(bbox.expanded(1.05, 1.12))
					break
				if os.environ.get("UTRR_DEBUG_LABELS"):
					print(
						f"  --  {text:>8s} {(dx, dy)} inside={inside} "
						f"bbox=({bbox.x0:.0f},{bbox.y0:.0f},{bbox.x1:.0f},{bbox.y1:.0f}) "
						f"frame=({frame.x0:.0f},{frame.y0:.0f},{frame.x1:.0f},{frame.y1:.0f}) "
						f"hit={[idx for idx, other in enumerate(placed) if bbox.overlaps(other)]}"
					)
				ann.remove()

	def _draw_network(self, ax, net, solution, limit=None) -> None:
		"""在坐标系 ax 内绘制弧与节点；limit=(x0,x1,y0,y1) 时只画框内的弧。"""

		def inside(node) -> bool:
			if limit is None:
				return True
			return limit[0] <= node.x <= limit[1] and limit[2] <= node.y <= limit[3]

		for arc in net.arcs:
			if arc.is_rail:
				continue
			a, b = net.nodes[arc.i], net.nodes[arc.j]
			if not (inside(a) and inside(b)):
				continue
			ax.plot(
				[a.x, b.x],
				[a.y, b.y],
				color=ColorPalette.NETWORK_TOPOLOGY[0]["ROAD"],
				lw=PlotProperties.EDGE_WIDTH_ROAD,
				alpha=PlotProperties.EDGE_ALPHA,
				zorder=1,
			)
		for arc in net.arcs:
			if not arc.is_rail:
				continue
			a, b = net.nodes[arc.i], net.nodes[arc.j]
			if not (inside(a) and inside(b)):
				continue
			ax.plot(
				[a.x, b.x],
				[a.y, b.y],
				color=ColorPalette.NETWORK_TOPOLOGY[1]["RAIL"],
				lw=0.9,
				alpha=0.75,
				zorder=1,
			)

		# 选中路径：以较粗的暖色覆盖其经过的弧，方向由 o→d 的图注意义即可
		if solution is not None:
			for arc in solution.arcs:
				if arc.is_transfer or arc.distance <= 0.0:
					continue
				a, b = net.nodes[arc.i], net.nodes[arc.j]
				if not (inside(a) and inside(b)):
					continue
				ax.plot(
					[a.x, b.x],
					[a.y, b.y],
					color=ColorPalette.TERRACOTTA,
					lw=2.0,
					alpha=0.9,
					solid_capstyle="round",
					zorder=2,
				)

		styles = {
			LAYER_CLIENT: (ColorPalette.DEFAULT_BLACK, "s", PlotProperties.NODE_SIZE_CLIENT),
			LAYER_YARD: (ColorPalette.WARM_SAND, "s", PlotProperties.NODE_SIZE_YARD),
			LAYER_RAIL: (ColorPalette.DEFAULT_WHITE, "o", PlotProperties.NODE_SIZE_RAIL),
			LAYER_ROAD: (ColorPalette.DEFAULT_GRAY, "o", PlotProperties.NODE_SIZE_ROAD),
		}
		for node in sorted(net.nodes.values(), key=lambda n: _LAYER_ZORDER[n.layer]):
			if not inside(node):
				continue
			color, shape, size = styles[node.layer]
			ax.scatter(
				node.x,
				node.y,
				marker=shape,
				s=size,
				facecolor=color,
				edgecolor=ColorPalette.DEFAULT_BLACK,
				linewidth=PlotProperties.NODE_LINE_WIDTH,
				zorder=3,
			)

	def _inset_geometry(self, fig, ax):
		"""按主图的数据比例反算放大插图的位置与范围。"""
		pos = ax.get_position()
		fig_w_cm = fig.get_size_inches()[0] * 2.54
		fig_h_cm = fig.get_size_inches()[1] * 2.54
		ax_w_cm = pos.width * fig_w_cm
		ax_h_cm = pos.height * fig_h_cm
		x0, x1 = ax.get_xlim()
		y0, y1 = ax.get_ylim()
		cm_per_deg_x = ax_w_cm / (x1 - x0)
		cm_per_deg_y = ax_h_cm / (y1 - y0)

		span_x, span_y = self.INSET_SPAN
		cx, cy = self.INSET_CENTER
		limit = (cx - span_x / 2, cx + span_x / 2, cy - span_y / 2, cy + span_y / 2)
		w = span_x * cm_per_deg_x * self.INSET_ZOOM / fig_w_cm
		h = span_y * cm_per_deg_y * self.INSET_ZOOM / fig_h_cm
		# 贴在坐标区右上角，留出 2% 的边距
		rect = [pos.x1 - w - 0.010, pos.y1 - h - 0.012, w, h]
		return limit, rect

	def plot_network(self, instance, path: str, solution=None) -> list:
		net = instance.network
		fig = self._figure(PlotProperties.FIG_WIDTH_CM_DOUBLE, aspect=0.50)
		ax = fig.add_subplot(111)
		self._draw_network(ax, net, solution)

		if instance.metadata.get("coordinate_system") == "lonlat":
			ax.set_xlabel("经度 / (°)")
			ax.set_ylabel("纬度 / (°)")
		else:
			ax.set_xlabel("东西向坐标 / km")
			ax.set_ylabel("南北向坐标 / km")
		ax.set_xlim(84.0, 123.4)
		ax.set_ylim(28.4, 47.2)
		ax.set_xticks([85, 90, 95, 100, 105, 110, 115, 120])
		ax.set_yticks([30, 32, 34, 36, 38, 40, 42, 44])
		ax.grid(False)
		self._style_axes(ax)

		# 长三角汇集区货场密集，在主图上层叠加放大插图，避免标注互相压盖
		fig.canvas.draw()
		limit, rect = self._inset_geometry(fig, ax)
		inset = fig.add_axes(rect, zorder=5)
		inset.set_facecolor("white")
		self._draw_network(inset, net, solution, limit)
		inset.set_xlim(limit[0], limit[1])
		inset.set_ylim(limit[2], limit[3])
		inset.set_xticks([117.0, 119.0, 121.0])
		inset.set_yticks([30.0, 31.0, 32.0])
		inset.tick_params(direction="in", length=2.0, width=0.6, labelsize=6.0, pad=1.5)
		inset.grid(False)
		for spine in inset.spines.values():
			spine.set_visible(True)
			spine.set_linewidth(0.6)

		# 主图上标出插图的取景范围，并用引线指向插图
		rect_patch = plt.Rectangle(
			(limit[0], limit[2]),
			limit[1] - limit[0],
			limit[3] - limit[2],
			fill=False,
			edgecolor=ColorPalette.DEFAULT_BLACK,
			lw=0.6,
			ls=(0, (3, 2)),
			zorder=6,
		)
		ax.add_patch(rect_patch)
		fig.transFigure.inverted()  # 确保图坐标变换已建立
		for corner, target in (
			((limit[0], limit[3]), (rect[0], rect[1])),
			((limit[1], limit[3]), (rect[0] + rect[2], rect[1])),
		):
			p0 = ax.transData.transform(corner)
			p0 = fig.transFigure.inverted().transform(p0)
			fig.add_artist(
				Line2D(
					[p0[0], target[0]],
					[p0[1], target[1]],
					color=ColorPalette.DEFAULT_GRAY,
					lw=0.5,
					ls=(0, (4, 2)),
					zorder=4,
				)
			)

		# 标注：客户点与货场（货场标注所在城市，车站不逐一标注以免文字堆叠）
		yard_cities = instance.metadata.get("yard_cities", {})
		main_entries, inset_entries = [], []
		for node_id, node in net.nodes.items():
			if node.layer == LAYER_YARD:
				if node.port != "in":
					continue
				text = yard_cities.get(node.yard, node.yard)
			elif node.layer == LAYER_CLIENT:
				text = "供应点 o" if node_id == net.origin else "需求点 d"
			else:
				continue
			in_inset = limit[0] <= node.x <= limit[1] and limit[2] <= node.y <= limit[3]
			preset = self.LABEL_PREFERENCE.get(text)
			if preset is not None:
				self._anchor_label(inset if in_inset else ax, text, node.x, node.y, *preset)
			elif in_inset:
				inset_entries.append((text, node.x, node.y, []))
			else:
				main_entries.append((text, node.x, node.y, []))
		sizes = {
			LAYER_CLIENT: PlotProperties.NODE_SIZE_CLIENT,
			LAYER_YARD: PlotProperties.NODE_SIZE_YARD,
			LAYER_RAIL: PlotProperties.NODE_SIZE_RAIL,
			LAYER_ROAD: PlotProperties.NODE_SIZE_ROAD,
		}

		def in_box(node, box) -> bool:
			return box[0] <= node.x <= box[1] and box[2] <= node.y <= box[3]

		main_obstacles = [
			(n.x, n.y, sizes[n.layer])
			for n in net.nodes.values()
			if n.layer in (LAYER_YARD, LAYER_CLIENT) and not in_box(n, limit)
		]
		inset_obstacles = [
			(n.x, n.y, sizes[n.layer])
			for n in net.nodes.values()
			if n.layer in (LAYER_YARD, LAYER_CLIENT) and in_box(n, limit)
		]
		self._place_labels(ax, main_entries, main_obstacles)
		self._place_labels(inset, inset_entries, inset_obstacles)

		legend_items = [
			Line2D([0], [0], color=ColorPalette.DEFAULT_GRAY, lw=1.0, label="公路弧"),
			Line2D([0], [0], color=ColorPalette.DEFAULT_BLACK, lw=1.0, label="铁路弧"),
			Line2D([0], [0], marker="s", color="none", markerfacecolor=ColorPalette.DEFAULT_BLACK,
				   markeredgecolor=ColorPalette.DEFAULT_BLACK, markersize=5, label="客户点"),
			Line2D([0], [0], marker="s", color="none", markerfacecolor=ColorPalette.WARM_SAND,
				   markeredgecolor=ColorPalette.DEFAULT_BLACK, markersize=5, label="货场"),
			Line2D([0], [0], marker="o", color="none", markerfacecolor=ColorPalette.DEFAULT_WHITE,
				   markeredgecolor=ColorPalette.DEFAULT_BLACK, markersize=4, label="铁路车站"),
		]
		if solution is not None:
			legend_items.insert(2, Line2D(
				[0], [0], color=ColorPalette.TERRACOTTA, lw=1.7, label="选中路径"
			))
		ax.legend(
			handles=legend_items,
			loc="lower center",
			bbox_to_anchor=(0.5, 1.0),
			frameon=False,
			ncol=3,
			handlelength=1.4,
			columnspacing=1.0,
			borderaxespad=0.1,
			fontsize=PlotProperties.FONT_SIZE_ANNOTATION,
		)
		return self._save(fig, path)

	# ------------------------------------------------------------------
	# 图 5：风险-成本 Pareto 前沿
	# ------------------------------------------------------------------
	def plot_pareto(
		self,
		front: list,
		instance,
		path: str,
		schemes: dict | None = None,
		full_front: list | None = None,
	) -> list:
		fig = self._figure(PlotProperties.FIG_WIDTH_CM_SINGLE, aspect=0.80)
		ax = fig.add_subplot(111)
		alpha = self.config.alpha

		points_x, points_y = [], []
		# 完全前沿（不计运到时限）：说明机会约束把哪一段前沿挡在可行域之外
		if full_front:
			sorted_full = sorted(full_front, key=lambda s: s.risk)
			fx = [s.risk for s in sorted_full]
			fy = [s.cost / 10000.0 for s in sorted_full]
			ax.plot(
				fx,
				fy,
				color=ColorPalette.DEFAULT_GRAY,
				lw=PlotProperties.LINE_WIDTH_AUX,
				ls=(0, (4, 2)),
				zorder=1,
			)
			points_x += fx
			points_y += fy

		if front:
			sorted_front = sorted(front, key=lambda s: s.risk)
			points_x += [s.risk for s in sorted_front]
			points_y += [s.cost / 10000.0 for s in sorted_front]
			ax.plot(
				[s.risk for s in sorted_front],
				[s.cost / 10000.0 for s in sorted_front],
				color=ColorPalette.DEFAULT_BLACK,
				lw=PlotProperties.LINE_WIDTH,
				zorder=3,
			)
			ax.scatter(
				[s.risk for s in sorted_front],
				[s.cost / 10000.0 for s in sorted_front],
				s=PlotProperties.MARKER_SIZE**2 * 0.9,
				facecolor=ColorPalette.DEFAULT_WHITE,
				edgecolor=ColorPalette.DEFAULT_BLACK,
				linewidth=0.7,
				zorder=4,
			)

		# 前沿三方案：成本最小解、风险最小解、折中解（按风险排序居中的解）
		annotations = []
		scheme_handles = {}
		if schemes:
			marked = [
				("无时限成本最小", "no_deadline", "x", (8, 8), "left", "bottom"),
				("成本最小解", "cost_min", "s", (-6, -10), "right", "top"),
				("风险最小解", "risk_min", "^", (5, 8), "left", "bottom"),
				("折中解", "compromise", "*", (10, 9), "left", "bottom"),
			]
			for label, key, marker, offset, ha, va in marked:
				solution = schemes.get(key, {}).get("representative")
				if solution is None:
					continue
				x, y = solution.risk, solution.cost / 10000.0
				points_x.append(x)
				points_y.append(y)
				ax.scatter(
					x,
					y,
					marker=marker,
					s=(PlotProperties.MARKER_SIZE * 2.0) ** 2
					if marker == "*"
					else PlotProperties.MARKER_SIZE**2 * 1.8,
					facecolor=ColorPalette.TERRACOTTA
					if key == "compromise"
					else ColorPalette.DEFAULT_WHITE,
					edgecolor=ColorPalette.DEFAULT_BLACK,
					linewidth=0.8,
					zorder=5,
				)
				scheme_handles[key] = Line2D(
					[0],
					[0],
					marker=marker,
					color="none",
					markerfacecolor=ColorPalette.TERRACOTTA
					if key == "compromise"
					else ColorPalette.DEFAULT_WHITE,
					markeredgecolor=ColorPalette.DEFAULT_BLACK,
					markeredgewidth=0.7,
					markersize=7.0 if marker == "*" else 4.4,
					label=label,
				)
				# 方案名称进图例，点旁只标 M，避免图例与注记重复
				text = f"$M={solution.reliability(instance.deadline):.3f}$"
				annotations.append((text, x, y, offset, ha, va))

		pad_x = (max(points_x) - min(points_x)) * 0.26 if points_x else 1.0
		pad_y = (max(points_y) - min(points_y)) * 0.30 if points_y else 1.0
		bottom = 0.42
		ax.set_xlim(min(points_x) - pad_x, max(points_x) + pad_x)
		top = max(points_y) + pad_y
		ax.set_ylim(min(points_y) - pad_y * bottom / 0.30, top + (top - min(points_y)) * 0.06)

		for text, x, y, offset, ha, va in annotations:
			ax.annotate(
				text,
				(x, y),
				textcoords="offset points",
				xytext=offset,
				fontsize=PlotProperties.FONT_SIZE_ANNOTATION,
				linespacing=1.15,
				ha=ha,
				va=va,
				zorder=6,
				arrowprops=dict(
					arrowstyle="-",
					lw=0.5,
					color=ColorPalette.DEFAULT_GRAY,
					shrinkA=1.0,
					shrinkB=3.5,
				),
			)

		ax.set_xlabel("运输风险 / 人")
		ax.set_ylabel("运输成本 / 万元")
		ax.xaxis.set_major_locator(MultipleLocator(100.0))
		handles = [
			Line2D([0], [0], color=ColorPalette.DEFAULT_GRAY, lw=PlotProperties.LINE_WIDTH_AUX,
				   ls=(0, (4, 2)), label="完整前沿（不计时限）"),
			Line2D([0], [0], color=ColorPalette.DEFAULT_BLACK, lw=PlotProperties.LINE_WIDTH,
				   marker="o", markerfacecolor=ColorPalette.DEFAULT_WHITE,
				   markeredgecolor=ColorPalette.DEFAULT_BLACK, markersize=3.4,
				   label="机会约束前沿（可靠度不低于0.90）"),
		]
		# 图例 3 行 2 列、从左到右从上到下：完全前沿、Pareto 最优前沿、风险最小解、成本最小解、折中解
		# （matplotlib 按列填充，故按 列1 三行、列2 两行 的顺序给句柄）
		ordered = [
			handles[0],
			scheme_handles.get("no_deadline"),
			scheme_handles.get("compromise"),
			handles[1],
			scheme_handles.get("cost_min"),
			scheme_handles.get("risk_min"),
		]
		ax.legend(
			handles=[handle for handle in ordered if handle is not None],
			frameon=False,
			loc="lower center",
			bbox_to_anchor=(0.5, 1.005),
			ncol=2,
			handletextpad=0.5,
			handlelength=1.9,
			labelspacing=0.25,
			columnspacing=0.9,
			borderaxespad=0.1,
			fontsize=PlotProperties.FONT_SIZE_ANNOTATION,
		)
		self._style_axes(ax)
		return self._save(fig, path)

	def plot_algorithm_scaling(self, bench_records: list, ablation_records: list, path: str) -> list:
		"""图 12：BMLC 与外部算法对比。x 轴网络节点数，左轴求解时间，右轴工作量。"""
		fig = self._figure(PlotProperties.FIG_WIDTH_CM_SINGLE, aspect=0.90)
		ax = fig.add_subplot(111)
		name_to_nodes = {r["instance"]: r["num_nodes"] for r in bench_records}
		work_label = {
			"BMLC": "生成标号数",
			"WST": "扩展标号数",
			"Gurobi-MIP": "求解次数",
		}
		series = {
			"BMLC": ("o", ColorPalette.DEFAULT_BLACK, [], []),
			"WST": ("s", ColorPalette.TERRACOTTA, [], []),
			"Gurobi-MIP": ("D", ColorPalette.DEFAULT_GRAY, [], []),
		}
		for row in ablation_records:
			if row["variant"].startswith("完整算法"):
				series["BMLC"][2].append((name_to_nodes.get(row["instance"], 0), row["wall_time"]))
				series["BMLC"][3].append((name_to_nodes.get(row["instance"], 0), row["labels"]))
		for row in bench_records:
			series["WST"][2].append((row["num_nodes"], row["wst"]["wall_time"]))
			series["WST"][3].append((row["num_nodes"], row["wst"]["labels"]))
			if row.get("gurobi"):
				series["Gurobi-MIP"][2].append((row["num_nodes"], row["gurobi"]["wall_time"]))
				series["Gurobi-MIP"][3].append((row["num_nodes"], row["gurobi"]["num_solves"]))
		ax2 = ax.twinx()
		ax2.spines["top"].set_visible(False)
		ax2.grid(False)
		# 节点数跨度大（24–94），若用物理坐标作柱宽会缩成细线；改为类别坐标
		nodes = sorted({r["num_nodes"] for r in bench_records})
		xpos = {n: i for i, n in enumerate(nodes)}
		n_series = max(1, sum(1 for _, (_, _, tdata, _) in series.items() if tdata))
		width = 0.72 / n_series
		# 柱：无彩色填充，仅黑边+底纹区分；twin 轴默认盖住折线，需把左轴抬到上层
		plt.rcParams["hatch.color"] = ColorPalette.DEFAULT_BLACK
		plt.rcParams["hatch.linewidth"] = 0.55
		# BMLC：空白填充（无底纹）；其余算法用底纹区分
		hatches = {"BMLC": "", "WST": "////", "Gurobi-MIP": "xxxx"}
		bar_face = ColorPalette.DEFAULT_WHITE
		for i, (label, (marker, color, tdata, wdata)) in enumerate(series.items()):
			if not tdata:
				continue
			work_by_node = {d[0]: d[1] for d in wdata if d[0] > 0 and d[1] > 0}
			ax2.bar(
				[xpos[n] - 0.36 + (i + 0.5) * width for n in nodes],
				[work_by_node.get(n, 0.0) for n in nodes],
				width=width * 0.88, facecolor=bar_face, edgecolor=ColorPalette.DEFAULT_BLACK,
				linewidth=0.55, hatch=hatches[label], zorder=1,
			)
		for i, (label, (marker, color, tdata, wdata)) in enumerate(series.items()):
			if not tdata:
				continue
			td = sorted(d for d in tdata if d[0] > 0 and d[1] > 0)
			tex = "$\\mathrm{Gurobi}$" if label == "Gurobi-MIP" else f"$\\mathrm{{{label}}}$"
			ax.plot([xpos[d[0]] for d in td], [d[1] for d in td],
					marker=marker, color=color, lw=PlotProperties.LINE_WIDTH,
					ms=PlotProperties.MARKER_SIZE, label=tex, zorder=5)
		ax.set_zorder(ax2.get_zorder() + 1)
		ax.patch.set_visible(False)
		ax.set_yscale("log")
		ax2.set_yscale("log")
		ax.set_xticks(list(range(len(nodes))))
		ax.set_xticklabels([f"${v:g}$" for v in nodes])
		ax.set_xlim(-0.6, len(nodes) - 0.4)
		ax.set_xlabel("网络节点数")
		ax.set_ylabel("求解时间 / $\\mathrm{s}$")
		ax2.set_ylabel("工作量 / 次")
		# 图例两行：第一行为左轴折线指标，第二行为右轴柱状指标（列主序交错排布）
		handles = []
		labels = []
		for label, (marker, color, tdata, wdata) in series.items():
			if not tdata:
				continue
			tex = "$\\mathrm{Gurobi}$" if label == "Gurobi-MIP" else f"$\\mathrm{{{label}}}$"
			handles.append((
				Line2D([0], [0], color=color, lw=PlotProperties.LINE_WIDTH,
						 marker=marker, ms=PlotProperties.MARKER_SIZE),
				Patch(facecolor=bar_face, edgecolor=ColorPalette.DEFAULT_BLACK,
					  linewidth=0.55, hatch=hatches[label]),
			))
			labels.append(tex)
		ax.legend(handles=handles, labels=labels, frameon=False, loc="lower center",
				  bbox_to_anchor=(0.5, 1.0), ncol=3, handler_map={tuple: HandlerTuple(ndivide=None)},
				  fontsize=PlotProperties.FONT_SIZE_ANNOTATION,
				  handletextpad=0.5, handlelength=2.2, columnspacing=1.0,
				  borderaxespad=0.1)
		self._style_axes(ax)
		self._style_twin_y(ax2)
		return self._save(fig, path)

	def plot_ablation_scaling(self, ablation_records: list, path: str) -> list:
		"""图 11：BMLC 与消融变体对比。x 轴网络节点数，左轴求解时间，右轴剪枝率。"""
		fig = self._figure(PlotProperties.FIG_WIDTH_CM_SINGLE, aspect=0.90)
		ax = fig.add_subplot(111)
		code_of = {
			"完整算法（4策略）": "BMLC",
			"去除双向汇合（3策略）": "BMLC-B",
			"再去除下界剪枝（2策略）": "BMLC-BL",
			"仅保留Pareto支配（1策略）": "BMLC-BLC",
		}
		styles = {
			"BMLC": ("o", ColorPalette.DEFAULT_BLACK),
			"BMLC-B": ("s", ColorPalette.TERRACOTTA),
			"BMLC-BL": ("^", ColorPalette.SLATE),
			"BMLC-BLC": ("D", ColorPalette.DEFAULT_GRAY),
		}
		name_to_nodes = {"OD4真实算例": 94, "合成24节点": 24, "合成38节点": 38,
						 "合成52节点": 52, "合成82节点": 82}
		data = {code: [] for code in styles}
		for row in ablation_records:
			code = code_of.get(row["variant"])
			if code:
				data[code].append((name_to_nodes.get(row["instance"], 0),
								   row["wall_time"], row["prune_rate"] * 100.0))
		ax2 = ax.twinx()
		ax2.spines["top"].set_visible(False)
		ax2.grid(False)
		# 节点数跨度大（24–94），若用物理坐标作柱宽会缩成细线；改为类别坐标
		nodes = sorted({p[0] for code in styles for p in data[code]})
		xpos = {n: i for i, n in enumerate(nodes)}
		n_series = max(1, sum(1 for code in styles if data[code]))
		width = 0.72 / n_series
		# 柱：无彩色填充，仅黑边+底纹区分；twin 轴默认盖住折线，需把左轴抬到上层
		plt.rcParams["hatch.color"] = ColorPalette.DEFAULT_BLACK
		plt.rcParams["hatch.linewidth"] = 0.55
		# BMLC：空白填充（无底纹）；消融变体用底纹区分
		hatches = {"BMLC": "", "BMLC-B": "////", "BMLC-BL": "\\\\\\\\", "BMLC-BLC": "xxxx"}
		bar_face = ColorPalette.DEFAULT_WHITE
		for i, (code, (marker, color)) in enumerate(styles.items()):
			if not data[code]:
				continue
			pts = sorted(data[code])
			prune_by_node = {p[0]: p[2] for p in pts}
			ax2.bar(
				[xpos[n] - 0.36 + (i + 0.5) * width for n in nodes],
				[prune_by_node.get(n, 0.0) for n in nodes],
				width=width * 0.88, facecolor=bar_face, edgecolor=ColorPalette.DEFAULT_BLACK,
				linewidth=0.55, hatch=hatches[code], zorder=1,
			)
		for i, (code, (marker, color)) in enumerate(styles.items()):
			if not data[code]:
				continue
			pts = sorted(data[code])
			ax.plot([xpos[p[0]] for p in pts], [p[1] for p in pts], marker=marker, color=color,
					lw=PlotProperties.LINE_WIDTH, ms=PlotProperties.MARKER_SIZE,
					label=f"$\\mathrm{{{code}}}$", zorder=5)
		ax.set_zorder(ax2.get_zorder() + 1)
		ax.patch.set_visible(False)
		ax.set_yscale("log")
		ax.set_xticks(list(range(len(nodes))))
		ax.set_xticklabels([f"${v:g}$" for v in nodes])
		ax.set_xlim(-0.6, len(nodes) - 0.4)
		ax.set_xlabel("网络节点数")
		ax.set_ylabel("求解时间 / $\\mathrm{s}$")
		ax2.set_ylabel("剪枝率 / $\\%$")
		# 图例两行：第一行为左轴折线指标，第二行为右轴柱状指标（列主序交错排布）
		handles = []
		labels = []
		for code, (marker, color) in styles.items():
			if not data[code]:
				continue
			handles.append((
				Line2D([0], [0], color=color, lw=PlotProperties.LINE_WIDTH,
						 marker=marker, ms=PlotProperties.MARKER_SIZE),
				Patch(facecolor=bar_face, edgecolor=ColorPalette.DEFAULT_BLACK,
					  linewidth=0.55, hatch=hatches[code]),
			))
			labels.append(f"$\\mathrm{{{code}}}$")
		ax.legend(handles=handles, labels=labels, frameon=False, loc="lower center",
				  bbox_to_anchor=(0.5, 1.0), ncol=2, handler_map={tuple: HandlerTuple(ndivide=None)},
				  fontsize=PlotProperties.FONT_SIZE_ANNOTATION,
				  handletextpad=0.5, handlelength=2.2, columnspacing=1.0, labelspacing=0.25,
				  borderaxespad=0.1)
		self._style_axes(ax)
		self._style_twin_y(ax2)
		return self._save(fig, path)
	def plot_multi_od_fronts(self, od_fronts: list, path: str) -> list:
		"""多面板绘制各 OD 对的可行 Pareto 前沿。

		od_fronts: [{"label": "OD2", "front": [Solution, ...], "knee": Solution|None}, ...]
		每个面板的星形为该 OD 的拐点解（与图 5 的本文方案同标记）。
		"""
		ncols = 3
		nrows = (len(od_fronts) + 1) // ncols  # 末格放共享图例
		fig = self._figure(PlotProperties.FIG_WIDTH_CM_FULL, aspect=0.30 * nrows + 0.16)
		front_handle = Line2D(
			[0], [0], color=ColorPalette.DEFAULT_BLACK, lw=PlotProperties.LINE_WIDTH,
			marker="o", markerfacecolor=ColorPalette.DEFAULT_WHITE,
			markeredgecolor=ColorPalette.DEFAULT_BLACK, markersize=3.4, label="$\\mathrm{Pareto}$ 最优前沿",
		)
		knee_handle = Line2D(
			[0], [0], marker="*", color="none",
			markerfacecolor=ColorPalette.TERRACOTTA, markeredgecolor=ColorPalette.DEFAULT_BLACK,
			markeredgewidth=0.7, markersize=8.0, label="折中解",
		)
		for index, item in enumerate(od_fronts, start=1):
			ax = fig.add_subplot(nrows, ncols, index)
			front = item.get("front") or []
			if front:
				ordered = sorted(front, key=lambda s: s.risk)
				xs = [s.risk for s in ordered]
				ys = [s.cost / 10000.0 for s in ordered]
				ax.plot(xs, ys, color=ColorPalette.DEFAULT_BLACK,
						lw=PlotProperties.LINE_WIDTH, zorder=3)
				ax.scatter(xs, ys, s=PlotProperties.MARKER_SIZE**2 * 0.7,
						   facecolor=ColorPalette.DEFAULT_WHITE,
						   edgecolor=ColorPalette.DEFAULT_BLACK, linewidth=0.7, zorder=4)
			knee = item.get("knee")
			if knee is not None:
				ax.scatter(knee.risk, knee.cost / 10000.0, marker="*",
						   s=(PlotProperties.MARKER_SIZE * 1.5) ** 2,
						   facecolor=ColorPalette.TERRACOTTA,
						   edgecolor=ColorPalette.DEFAULT_BLACK, linewidth=0.7, zorder=5)
			ax.set_title(f"$\\mathrm{{{item['label']}}}$", fontsize=PlotProperties.FONT_SIZE_ANNOTATION)
			ax.set_xlabel("运输风险 / 人", fontsize=PlotProperties.FONT_SIZE_ANNOTATION)
			ax.set_ylabel("运输成本 / 万元", fontsize=PlotProperties.FONT_SIZE_ANNOTATION)
			self._style_axes(ax)
		# 图例置于图片最上方、水平单行
		fig.legend(
			handles=[front_handle, knee_handle],
			frameon=False,
			loc="upper center",
			bbox_to_anchor=(0.5, 1.0),
			ncol=2,
			handletextpad=0.5,
			handlelength=1.9,
			columnspacing=1.2,
			fontsize=PlotProperties.FONT_SIZE_ANNOTATION,
		)
		fig.tight_layout(rect=(0, 0, 1, 0.94))
		return self._save(fig, path)

	# ------------------------------------------------------------------
	# 图 6：置信水平敏感性
	# ------------------------------------------------------------------
	def plot_alpha(self, rows: list, path: str, critical: float = None, sweep: list = None) -> list:
		"""图 7：置信水平影响。x 轴取表 7 的 α 网格参数；临界点以标记绘于 α=0.80 与 0.99。"""
		fig = self._figure(PlotProperties.FIG_WIDTH_CM_SINGLE, aspect=0.88)
		ax = fig.add_subplot(111)
		series = rows
		alpha = [item["alpha"] for item in series]
		cost = [item["cost"] / 10000.0 for item in series]
		risk = [item["risk"] for item in series]

		ax.plot(
			alpha, cost, color=ColorPalette.DEFAULT_BLACK, drawstyle="steps-post",
			lw=PlotProperties.LINE_WIDTH, label="最小成本",
		)
		ax.scatter(
			alpha, cost, s=PlotProperties.MARKER_SIZE**2 * 0.7,
			facecolor=ColorPalette.DEFAULT_WHITE, edgecolor=ColorPalette.DEFAULT_BLACK,
			linewidth=0.6, zorder=4,
		)
		ax.set_xlabel("置信水平 $\\alpha$")
		ax.set_ylabel("运输成本 / 万元")
		self._style_axes(ax)

		ax2 = ax.twinx()
		ax2.plot(
			alpha, risk, marker="s", color=ColorPalette.TERRACOTTA, ls="--",
			lw=PlotProperties.LINE_WIDTH_AUX, ms=PlotProperties.MARKER_SIZE * 0.62,
			label="综合风险",
		)
		ax2.set_ylabel("运输风险 / 人")

		ax.set_xlim(min(alpha) - 0.012, max(alpha) + 0.012)
		ax.set_xticks(alpha)
		ax.set_xticklabels([f"${v:.2f}$" for v in alpha])
		span_cost = max(cost) - min(cost)
		span_risk = max(risk) - min(risk)
		ax.set_ylim(min(cost) - span_cost * 0.16, max(cost) + span_cost * 0.16)
		ax2.set_ylim(min(risk) - span_risk * 0.16, max(risk) + span_risk * 0.16)
		# ylim 定稿后再锁右轴 mathtext 刻度，避免 twinx 默认无衬线数字
		self._style_twin_y(ax2)

		# 置信水平换档点：α=0.80 与 0.99 处灰色竖虚线（与时限严格度同款），线左侧标 M 值
		cost_at = {round(item["alpha"], 2): item["cost"] / 10000.0 for item in series}
		for a, mlabel in ((0.85, "0.85"), (0.99, "0.99")):
			if round(a, 2) in cost_at:
				ax.axvline(a, color=ColorPalette.SLATE, lw=0.8, ls=(0, (3, 2)), zorder=1)
				ax.annotate(
					f"$M={mlabel}$",
					(a, max(cost) + span_cost * 0.10),
					textcoords="offset points",
					xytext=(-3, 0),
					ha="right",
					va="bottom",
					fontsize=PlotProperties.FONT_SIZE_ANNOTATION - 1.0,
					color=ColorPalette.SLATE,
					zorder=6,
				)
		handles = [
			Line2D([0], [0], color=ColorPalette.DEFAULT_BLACK, lw=PlotProperties.LINE_WIDTH,
				   marker="o", markerfacecolor=ColorPalette.DEFAULT_WHITE,
				   markeredgecolor=ColorPalette.DEFAULT_BLACK, markersize=3.6,
				   label="成本"),
			Line2D([0], [0], color=ColorPalette.TERRACOTTA, lw=PlotProperties.LINE_WIDTH_AUX,
				   ls="--", marker="s", markerfacecolor=ColorPalette.TERRACOTTA,
				   markeredgecolor=ColorPalette.TERRACOTTA, markersize=3.4,
				   label="风险"),
			Line2D([0], [0], color=ColorPalette.SLATE, lw=0.8, ls=(0, (3, 2)),
				   label="置信水平换档点"),
		]
		ax.legend(
			handles=handles,
			frameon=False,
			loc="lower center",
			bbox_to_anchor=(0.5, 1.0),
			ncol=3,
			handlelength=1.6,
			columnspacing=1.0,
			borderaxespad=0.15,
		)
		return self._save(fig, path)

	# ------------------------------------------------------------------
	# 图 7：测试周期敏感性
	# ------------------------------------------------------------------
	def plot_sigma(self, rows: list, path: str) -> list:
		"""图 8：四指标相对变化曲线（以 σ=0 确定性情形为基准），呈现表 8 行式数据之外的联动。"""
		fig = self._figure(PlotProperties.FIG_WIDTH_CM_SINGLE, aspect=0.82)
		ax = fig.add_subplot(111)
		scale = [row["sigma_h"] for row in rows]
		series = [
			("成本", [row["proposed_cost"] for row in rows], "o", ColorPalette.DEFAULT_BLACK),
			("风险", [row["proposed_risk"] for row in rows], "s", ColorPalette.TERRACOTTA),
			("可靠度", [row["reliability"] for row in rows], "^", ColorPalette.SLATE),
			("时间", [row["equivalent_time"] for row in rows], "D", ColorPalette.DEFAULT_GRAY),
		]
		for label, vals, marker, color in series:
			rel = [(v / vals[0] - 1.0) * 100.0 for v in vals]
			ax.plot(scale, rel, marker=marker, color=color, lw=PlotProperties.LINE_WIDTH,
					ms=PlotProperties.MARKER_SIZE, label=label)
		ax.axhline(0.0, color=ColorPalette.DEFAULT_GRAY, ls=":", lw=0.8)
		ax.set_xlabel("波动参数 / $\\mathrm{h}$")
		ax.set_ylabel("相对变化 / $\\%$")
		ax.set_xticks(scale)
		ax.set_xticklabels([f"${v:g}$" for v in scale])
		ax.set_xlim(min(scale) - 0.3, max(scale) + 0.3)
		ax.legend(
			frameon=False,
			loc="lower center",
			bbox_to_anchor=(0.5, 1.0),
			ncol=4,
			handletextpad=0.5,
			handlelength=1.7,
			columnspacing=0.9,
			borderaxespad=0.1,
		)
		self._style_axes(ax)
		return self._save(fig, path)

	# ------------------------------------------------------------------
	# 图 9：节点风险 θ–ρ 联合响应热力图
	# ------------------------------------------------------------------
	def plot_demand(self, rows: list, path: str) -> list:
		"""运量与成本最小可行方案的总成本和单位箱成本。"""
		if not rows:
			raise ValueError("运量敏感性结果为空")
		ordered = sorted(rows, key=lambda row: row["q"])
		fig = self._figure(PlotProperties.FIG_WIDTH_CM_SINGLE, aspect=0.82)
		ax = fig.add_subplot(111)
		quantities = [row["q"] for row in ordered]
		costs = [row["cost_min"]["cost"] / 10000.0 for row in ordered]
		ax.plot(quantities, costs, color=ColorPalette.DEFAULT_BLACK, marker="o",
				lw=PlotProperties.LINE_WIDTH, ms=PlotProperties.MARKER_SIZE, label="总成本")
		ax.set_xlabel("运量 / 箱")
		ax.set_ylabel("总成本 / 万元")
		self._style_axes(ax)
		ax2 = ax.twinx()
		ax2.plot(quantities, [cost / q for cost, q in zip(costs, quantities)],
				 color=ColorPalette.TERRACOTTA, marker="s", ls="--",
				 lw=PlotProperties.LINE_WIDTH_AUX, ms=PlotProperties.MARKER_SIZE, label="单位箱成本")
		ax2.set_ylabel("单位箱成本 / 万元")
		self._style_twin_y(ax2)
		handles = ax.get_lines() + ax2.get_lines()
		ax.legend(handles=handles, labels=[line.get_label() for line in handles],
				  frameon=False, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2)
		return self._save(fig, path)

	def plot_node_risk(self, rows: list, path: str) -> list:
		"""图 9：节点风险的 θ–ρ 联合响应热力图。"""
		data = [r for r in rows if r.get("theta") is not None]
		thetas = sorted({r["theta"] for r in data})
		rhos = sorted({r["rho"] for r in data})
		base = path[:-4] if path.endswith(".png") else path
		grid = [[0.0] * len(rhos) for _ in thetas]
		for r in data:
			ti = thetas.index(r["theta"])
			rj = rhos.index(r["rho"])
			# 两类代表解的节点风险相同，取成本最优解口径绘制唯一的联合响应。
			grid[ti][rj] = r["cost_total"] * r["cost_share"]

		cmap = LinearSegmentedColormap.from_list(
			"terracotta_seq",
			["#FFF8F3", ColorPalette.WARM_SAND, ColorPalette.TERRACOTTA, "#7A3E2A"],
			N=256,
		)
		fig = self._figure(PlotProperties.FIG_WIDTH_CM_SINGLE, aspect=0.86)
		ax = fig.add_subplot(111)
		im = ax.imshow(grid, cmap=cmap, aspect="auto")
		vmin, vmax = min(map(min, grid)), max(map(max, grid))
		for ti in range(len(thetas)):
			for rj in range(len(rhos)):
				value = grid[ti][rj]
				color = "white" if value >= vmin + 0.68 * (vmax - vmin) else ColorPalette.DEFAULT_BLACK
				ax.annotate(
					f"{value:.1f}", (rj, ti), ha="center", va="center", color=color,
					fontsize=PlotProperties.FONT_SIZE_ANNOTATION - 0.2,
				)
		ax.set_xticks(range(len(rhos)))
		ax.set_xticklabels([f"${v:g}$" for v in rhos])
		ax.set_yticks(range(len(thetas)))
		ax.set_yticklabels([f"${v:g}$" for v in thetas])
		ax.set_xlabel("$\\rho$ / $\\mathrm{h}^{-1}$")
		ax.set_ylabel("$\\theta$ / $\\mathrm{h}^{-1}$")
		cb = fig.colorbar(im, ax=ax, shrink=0.92, pad=0.04)
		cb.set_label("节点风险 / 人")
		cb.ax.tick_params(direction="in", labelsize=PlotProperties.FONT_SIZE_TICK)
		self._style_axes(ax)
		out_a = f"{base}_a.png"
		self._save(fig, out_a)

		return [out_a]

	def plot_deadline_service(self, rows: list, points: list, path: str, sweep: list = None) -> list:
		"""运到时限严格度与服务类型选择。

		横轴为运到时限、纵轴为最小可行总成本：时限放宽到某个临界值之前，只能用
		快速班列；越过临界值后成本阶跃下降（改用集装箱班列）。竖虚线给出三档时限。
		"""
		fig = self._figure(PlotProperties.FIG_WIDTH_CM_SINGLE, aspect=0.88)
		ax = fig.add_subplot(111)

		valid = [item for item in (sweep or []) if item.get("cost") is not None]
		if not valid:
			self._save(fig, path)
			return [f"{path}"]
		xs = [item["deadline"] for item in valid]
		ys = [item["cost"] / 10000.0 for item in valid]
		ax.plot(
			xs,
			ys,
			color=ColorPalette.DEFAULT_BLACK,
			lw=PlotProperties.LINE_WIDTH_AUX,
			drawstyle="steps-post",
			zorder=2,
		)
		ax.scatter(
			xs,
			ys,
			s=PlotProperties.MARKER_SIZE**2 * 0.9,
			facecolor=ColorPalette.DEFAULT_WHITE,
			edgecolor=ColorPalette.DEFAULT_BLACK,
			linewidth=0.7,
			zorder=3,
		)

		# 按主导列车等级（混编方案取运距占比最大者）分段，每个等级只标一次
		runs: list = []
		for item in valid:
			key = item.get("service_name") or item.get("label", "")
			if runs and runs[-1][0] == key:
				runs[-1][1].append(item)
			else:
				runs.append([key, [item]])
		dominant = {}
		for key, items in runs:
			if key not in dominant or len(items) > len(dominant[key]):
				dominant[key] = items
		for key, items in dominant.items():
			middle = items[len(items) // 2]
			ax.annotate(
				key,
				(middle["deadline"], middle["cost"] / 10000.0),
				textcoords="offset points",
				xytext=(0, 10),
				ha="center",
				va="bottom",
				fontsize=PlotProperties.FONT_SIZE_ANNOTATION,
				zorder=6,
			)

		span = max(xs) - min(xs)
		d_max = max(max(xs), max(row["deadline"] for row in rows))
		# 右侧预留标注宽度，避免最右档（宽松）被裁切后看起来压到左侧文字
		ax.set_xlim(min(xs) - span * 0.06, d_max + max(span * 0.16, 22.0))
		width = max(ys) - min(ys)
		ax.set_ylim(min(ys) - width * 0.22, max(ys) + width * 0.30)
		top = max(ys) + width * 0.28
		rightmost_d = max(row["deadline"] for row in rows)
		for row in rows:
			ax.axvline(
				row["deadline"],
				color=ColorPalette.SLATE,
				lw=0.8,
				ls=(0, (3, 2)),
				zorder=1,
			)
			# 一律标在虚线右侧；最右档加大水平偏移，避免与中等档抢位
			x_off = 8 if abs(row["deadline"] - rightmost_d) < 1e-9 else 3
			ax.annotate(
				f"{row['label']}\n$D={row['deadline']:.1f}$",
				(row["deadline"], top),
				textcoords="offset points",
				xytext=(x_off, -2),
				ha="left",
				va="top",
				fontsize=PlotProperties.FONT_SIZE_ANNOTATION - 0.4,
				color=ColorPalette.SLATE,
				linespacing=1.1,
				zorder=6,
				clip_on=False,
			)

		# 时限过紧导致无可行解的区间：淡灰底提示
		if len(valid) < len(sweep):
			first = min(item["deadline"] for item in sweep if item.get("cost") is None)
			ax.axvspan(min(item["deadline"] for item in sweep), first,
					   color=ColorPalette.DEFAULT_GRAY, alpha=0.10, zorder=0)

		ax.set_xlabel("运到时限 $D$ / $\\mathrm{h}$")
		ax.set_ylabel("运输成本 / 万元")
		legend_items = [
			Line2D([0], [0], color=ColorPalette.DEFAULT_BLACK, lw=PlotProperties.LINE_WIDTH_AUX,
				   marker="o", markerfacecolor=ColorPalette.DEFAULT_WHITE,
				   markeredgecolor=ColorPalette.DEFAULT_BLACK, markersize=4.2,
				   label="可行解"),
			Line2D([0], [0], color=ColorPalette.SLATE, lw=0.8, ls=(0, (3, 2)),
				   label="时限严格度"),
		]
		# 图例置于主图正上方、水平单行
		ax.legend(handles=legend_items, frameon=False, loc="lower center",
				  bbox_to_anchor=(0.5, 1.0), ncol=2,
				  handlelength=1.9, handletextpad=0.5, columnspacing=1.2, borderaxespad=0.1)
		self._style_axes(ax)
		return self._save(fig, path)

	# ------------------------------------------------------------------
	# 图 10：算法性能与可扩展性
	# ------------------------------------------------------------------
	def plot_scalability(self, rows: list, path: str) -> list:
		fig = self._figure(PlotProperties.FIG_WIDTH_CM_SINGLE, aspect=0.82)
		ax = fig.add_subplot(111)
		scale = [row["num_nodes"] for row in rows]
		ax.plot(
			scale,
			[row["wall_time"] for row in rows],
			marker="o",
			color=ColorPalette.DEFAULT_BLACK,
			lw=PlotProperties.LINE_WIDTH,
			ms=PlotProperties.MARKER_SIZE,
			label="运行时间",
		)
		ax.set_xlabel("网络节点数")
		ax.set_ylabel("运行时间 / s")
		ax.set_yscale("log")
		ax.set_xticks(scale)
		ax.set_xticklabels([f"{int(value)}" for value in scale])
		ax.set_xlim(min(scale) * 0.90, max(scale) * 1.08)
		ax.grid(True, which="both", ls=":", lw=0.4, alpha=0.5)
		self._style_axes(ax)

		ax2 = ax.twinx()
		ax2.spines["top"].set_visible(False)
		ax2.plot(
			scale,
			[row["pareto_size"] for row in rows],
			marker="s",
			ls="none",
			color=ColorPalette.TERRACOTTA,
			ms=PlotProperties.MARKER_SIZE * 1.2,
			label="Pareto 解数",
		)
		ax2.set_ylabel("Pareto 解数")
		ax2.set_ylim(0.0, max(row["pareto_size"] for row in rows) * 1.35)
		ax2.tick_params(direction="in", length=PlotProperties.TICK_LENGTH, width=PlotProperties.TICK_WIDTH)
		ax2.grid(False)

		handles = ax.get_lines()[:1] + ax2.get_lines()[:1]
		ax.legend(handles=handles, frameon=False, loc="upper left", handlelength=1.9)
		return self._save(fig, path)
