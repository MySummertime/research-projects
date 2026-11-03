"""出版级绘图：四层网络、Pareto 前沿、敏感性曲线与算法性能图。

规格按《交通运输工程学报》单栏图宽 7.0 cm、650 dpi。图内不写标题与图名（图题由
Word 排版层在图下给出），每幅图都必须带完整图例，坐标轴刻度一律朝内。
"""

from __future__ import annotations

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.patheffects as path_effects  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
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
				# 单字体族：混排（中文+mathtext）时双族回退会丢中文字形
				"font.family": [PlotProperties.FONT_FAMILY_CN],
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
		)

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
			Line2D([0], [0], color=ColorPalette.TERRACOTTA, lw=1.7, label="选中路径"),
			Line2D([0], [0], marker="s", color="none", markerfacecolor=ColorPalette.DEFAULT_BLACK,
				   markeredgecolor=ColorPalette.DEFAULT_BLACK, markersize=5, label="客户点"),
			Line2D([0], [0], marker="s", color="none", markerfacecolor=ColorPalette.WARM_SAND,
				   markeredgecolor=ColorPalette.DEFAULT_BLACK, markersize=5, label="货场"),
			Line2D([0], [0], marker="o", color="none", markerfacecolor=ColorPalette.DEFAULT_WHITE,
				   markeredgecolor=ColorPalette.DEFAULT_BLACK, markersize=4, label="铁路车站"),
		]
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
			fy = [s.cost / 1000.0 for s in sorted_full]
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
			points_y += [s.cost / 1000.0 for s in sorted_front]
			ax.plot(
				[s.risk for s in sorted_front],
				[s.cost / 1000.0 for s in sorted_front],
				color=ColorPalette.DEFAULT_BLACK,
				lw=PlotProperties.LINE_WIDTH,
				zorder=3,
			)
			ax.scatter(
				[s.risk for s in sorted_front],
				[s.cost / 1000.0 for s in sorted_front],
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
				("成本最小解", "cost_min", "s", (-6, -10), "right", "top"),
				("风险最小解", "risk_min", "^", (5, 8), "left", "bottom"),
				("折中解", "compromise", "*", (10, 9), "left", "bottom"),
			]
			for label, key, marker, offset, ha, va in marked:
				solution = schemes.get(key, {}).get("representative")
				if solution is None:
					continue
				x, y = solution.risk, solution.cost / 1000.0
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
				# 方案名称进图例，点旁只标可靠度，避免图例与注记重复
				text = f"$R={solution.reliability(instance.deadline):.3f}$"
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

		ax.set_xlabel("综合运输风险 / 人")
		ax.set_ylabel("综合运输成本 / 千元")
		ax.xaxis.set_major_locator(MultipleLocator(100.0))
		handles = [
			Line2D([0], [0], color=ColorPalette.DEFAULT_GRAY, lw=PlotProperties.LINE_WIDTH_AUX,
				   ls=(0, (4, 2)), label="完全前沿（不计时限）"),
			Line2D([0], [0], color=ColorPalette.DEFAULT_BLACK, lw=PlotProperties.LINE_WIDTH,
				   marker="o", markerfacecolor=ColorPalette.DEFAULT_WHITE,
				   markeredgecolor=ColorPalette.DEFAULT_BLACK, markersize=3.4,
				   label=f"Pareto 最优前沿（$R \\geq {alpha:.2f}$）"),
		]
		# 图例按列填充：左列为前沿、右列为三方案
		ordered = [
			handles[0],
			scheme_handles.get("cost_min"),
			handles[1],
			scheme_handles.get("risk_min"),
			scheme_handles.get("compromise"),
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
		"""图 11：各算法求解时间随网络规模的可扩展性曲线（对数纵轴）。"""
		fig = self._figure(PlotProperties.FIG_WIDTH_CM_SINGLE, aspect=0.82)
		ax = fig.add_subplot(111)
		name_to_nodes = {r["instance"]: r["num_nodes"] for r in bench_records}
		series = {
			"本文算法（BMLC）": ("o", ColorPalette.DEFAULT_BLACK, []),
			"加权和法WST": ("s", ColorPalette.TERRACOTTA, []),
			"Gurobi-MIP": ("D", ColorPalette.DEFAULT_GRAY, []),
		}
		for row in ablation_records:
			if row["variant"].startswith("完整算法"):
				series["本文算法（BMLC）"][2].append((name_to_nodes.get(row["instance"], 0), row["wall_time"]))
		for row in bench_records:
			series["加权和法WST"][2].append((row["num_nodes"], row["wst"]["wall_time"]))
			if row.get("gurobi"):
				series["Gurobi-MIP"][2].append((row["num_nodes"], row["gurobi"]["wall_time"]))
		for label, (marker, color, data) in series.items():
			if not data:
				continue
			data = sorted(d for d in data if d[0] > 0 and d[1] > 0)
			ax.plot([d[0] for d in data], [d[1] for d in data],
					marker=marker, color=color, lw=PlotProperties.LINE_WIDTH,
					ms=PlotProperties.MARKER_SIZE, label=label)
		ax.set_yscale("log")
		ax.yaxis.set_major_formatter(
			__import__("matplotlib.ticker", fromlist=["FuncFormatter"]).FuncFormatter(
				lambda v, _: f"{v:g}"
			)
		)
		ax.set_xlabel("网络节点数")
		ax.set_ylabel("求解时间 / s")
		ax.legend(frameon=False, loc="upper left", fontsize=PlotProperties.FONT_SIZE_ANNOTATION,
				  handlelength=1.6)
		self._style_axes(ax)
		return self._save(fig, path)

	# ------------------------------------------------------------------
	# 图 5b：其余 OD 对的风险-成本 Pareto 前沿（多面板）
	# ------------------------------------------------------------------
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
			markeredgecolor=ColorPalette.DEFAULT_BLACK, markersize=3.4, label="Pareto 最优前沿",
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
				ys = [s.cost / 1000.0 for s in ordered]
				ax.plot(xs, ys, color=ColorPalette.DEFAULT_BLACK,
						lw=PlotProperties.LINE_WIDTH, zorder=3)
				ax.scatter(xs, ys, s=PlotProperties.MARKER_SIZE**2 * 0.7,
						   facecolor=ColorPalette.DEFAULT_WHITE,
						   edgecolor=ColorPalette.DEFAULT_BLACK, linewidth=0.7, zorder=4)
			knee = item.get("knee")
			if knee is not None:
				ax.scatter(knee.risk, knee.cost / 1000.0, marker="*",
						   s=(PlotProperties.MARKER_SIZE * 1.5) ** 2,
						   facecolor=ColorPalette.TERRACOTTA,
						   edgecolor=ColorPalette.DEFAULT_BLACK, linewidth=0.7, zorder=5)
			ax.set_title(item["label"], fontsize=PlotProperties.FONT_SIZE_ANNOTATION)
			ax.set_xlabel("综合运输风险 / 人", fontsize=PlotProperties.FONT_SIZE_ANNOTATION)
			ax.set_ylabel("综合运输成本 / 千元", fontsize=PlotProperties.FONT_SIZE_ANNOTATION)
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
		fig = self._figure(PlotProperties.FIG_WIDTH_CM_SINGLE, aspect=0.82)
		ax = fig.add_subplot(111)
		series = [item for item in (sweep or []) if item.get("cost") is not None] or rows
		alpha = [item["alpha"] for item in series]
		cost = [item["cost"] / 1000.0 for item in series]
		risk = [item["risk"] for item in series]

		line_cost, = ax.plot(
			alpha, cost, color=ColorPalette.DEFAULT_BLACK, drawstyle="steps-post",
			lw=PlotProperties.LINE_WIDTH, label="最小成本",
		)
		ax.scatter(
			alpha, cost, s=PlotProperties.MARKER_SIZE**2 * 0.7,
			facecolor=ColorPalette.DEFAULT_WHITE, edgecolor=ColorPalette.DEFAULT_BLACK,
			linewidth=0.6, zorder=4,
		)
		ax.set_xlabel("置信水平 $\\alpha$")
		ax.set_ylabel("综合运输成本 / 千元")
		self._style_axes(ax)

		ax2 = ax.twinx()
		ax2.spines["top"].set_visible(False)
		line_risk, = ax2.plot(
			alpha, risk, marker="s", color=ColorPalette.TERRACOTTA, ls="--",
			lw=PlotProperties.LINE_WIDTH_AUX, ms=PlotProperties.MARKER_SIZE * 0.62,
			label="综合风险",
		)
		ax2.set_ylabel("综合运输风险 / 人")
		ax2.tick_params(direction="in", length=PlotProperties.TICK_LENGTH, width=PlotProperties.TICK_WIDTH)
		ax2.grid(False)

		ax.set_xlim(min(alpha) - 0.012, max(alpha) + 0.012)
		ax.xaxis.set_major_locator(MultipleLocator(0.05))
		span_cost = max(cost) - min(cost)
		span_risk = max(risk) - min(risk)
		ax.set_ylim(min(cost) - span_cost * 0.16, max(cost) + span_cost * 0.16)
		ax2.set_ylim(min(risk) - span_risk * 0.16, max(risk) + span_risk * 0.16)

		# 临界置信水平：最小成本方案的切换点，用竖虚线标出并单独进图例
		handles = [
			Line2D([0], [0], color=ColorPalette.DEFAULT_BLACK, lw=PlotProperties.LINE_WIDTH,
				   marker="o", markerfacecolor=ColorPalette.DEFAULT_WHITE,
				   markeredgecolor=ColorPalette.DEFAULT_BLACK, markersize=3.6,
				   label="最小成本"),
			Line2D([0], [0], color=ColorPalette.TERRACOTTA, lw=PlotProperties.LINE_WIDTH_AUX,
				   ls="--", marker="s", markerfacecolor=ColorPalette.TERRACOTTA,
				   markeredgecolor=ColorPalette.TERRACOTTA, markersize=3.4,
				   label="综合风险"),
		]
		if critical is not None:
			ax.axvline(
				critical,
				color=ColorPalette.SLATE,
				lw=0.9,
				ls=(0, (4, 2)),
				zorder=1,
			)
			ax.annotate(
				f"$\\alpha^* = {critical:.3f}$",
				(critical, max(cost) + span_cost * 0.10),
				textcoords="offset points",
				xytext=(3, 0),
				ha="left",
				va="bottom",
				fontsize=PlotProperties.FONT_SIZE_ANNOTATION,
				color=ColorPalette.SLATE,
				zorder=6,
			)
			handles.append(
				Line2D([0], [0], color=ColorPalette.SLATE, lw=0.9, ls=(0, (4, 2)),
					   label="临界置信水平")
			)
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
		fig = self._figure(PlotProperties.FIG_WIDTH_CM_SINGLE, aspect=0.82)
		ax = fig.add_subplot(111)
		scale = [row["sigma_h"] for row in rows]
		ax.plot(
			scale,
			[row["reliability"] for row in rows],
			marker="o",
			color=ColorPalette.DEFAULT_BLACK,
			lw=PlotProperties.LINE_WIDTH,
			ms=PlotProperties.MARKER_SIZE,
			label="本文不确定模型",
		)
		ax.plot(
			scale,
			[row["det_reliability"] for row in rows],
			marker="s",
			ls="--",
			color=ColorPalette.TERRACOTTA,
			lw=PlotProperties.LINE_WIDTH,
			ms=PlotProperties.MARKER_SIZE,
			label="确定性时间模型",
		)
		ax.axhline(
			self.config.alpha,
			color=ColorPalette.DEFAULT_GRAY,
			ls=":",
			lw=0.9,
			label=f"置信水平 $\\alpha$ = {self.config.alpha:.2f}",
		)
		ax.set_xlabel("$\\sigma$ / h")
		ax.set_ylabel("实际运到时限可靠度")
		ax.set_ylim(0.55, 1.06)
		ax.set_xlim(min(scale) - 0.15, max(scale) + 0.15)
		ax.legend(
			frameon=False,
			loc="lower center",
			bbox_to_anchor=(0.5, 1.0),
			ncol=2,
			handlelength=1.9,
			columnspacing=0.9,
			borderaxespad=0.1,
		)
		self._style_axes(ax)
		return self._save(fig, path)

	# ------------------------------------------------------------------
	# 图 8：风险构成分解
	# ------------------------------------------------------------------
	def plot_node_risk(self, rows: list, path: str) -> list:
		fig = self._figure(PlotProperties.FIG_WIDTH_CM_SINGLE, aspect=0.80)
		ax = fig.add_subplot(111)
		labels = [row["label"] for row in rows]
		arc_risk = [row["arc_risk"] for row in rows]
		node_risk = [row["node_risk_model"] for row in rows]
		omitted = [row["node_risk_omitted"] for row in rows]
		positions = list(range(len(rows)))

		ax.bar(
			positions,
			arc_risk,
			width=0.52,
			color=ColorPalette.DEFAULT_GRAY,
			edgecolor=ColorPalette.DEFAULT_BLACK,
			linewidth=0.6,
			label="弧段运输风险",
		)
		ax.bar(
			positions,
			node_risk,
			width=0.52,
			bottom=arc_risk,
			color=ColorPalette.RISK_NODE,
			edgecolor=ColorPalette.DEFAULT_BLACK,
			linewidth=0.6,
			label="计入的节点风险",
		)
		if any(value > 0 for value in omitted):
			ax.bar(
				positions,
				omitted,
				width=0.52,
				bottom=[a + b for a, b in zip(arc_risk, node_risk)],
				facecolor=ColorPalette.DEFAULT_WHITE,
				edgecolor=ColorPalette.RISK_NODE,
				linewidth=0.6,
				hatch="///",
				label="被忽略的节点风险",
			)

		top = max(a + b + c for a, b, c in zip(arc_risk, node_risk, omitted))
		ax.set_ylim(0.0, top * 1.16)
		# 柱顶标总量，柱内标节点风险占比：直接说明"忽略节点风险会低估多少"
		for position, arc, node, missing in zip(positions, arc_risk, node_risk, omitted):
			total = arc + node + missing
			ax.annotate(
				f"{total:.2f}",
				(position, total),
				textcoords="offset points",
				xytext=(0, 2),
				ha="center",
				va="bottom",
				fontsize=PlotProperties.FONT_SIZE_ANNOTATION - 0.5,
				zorder=6,
			)
			segment = node if node > 0 else missing
			if segment > 0:
				ax.annotate(
					f"{segment / total:.1%}",
					(position, arc + segment * 0.5),
					ha="center",
					va="center",
					fontsize=PlotProperties.FONT_SIZE_ANNOTATION - 0.5,
					color=ColorPalette.DEFAULT_BLACK,
					zorder=6,
				)
		ax.set_xticks(positions)
		ax.set_xticklabels(
			[lab.replace("θ,ρ", "$\\theta,\\rho$") for lab in labels], rotation=0
		)
		ax.set_ylabel("综合运输风险 / 人")
		ax.legend(
			frameon=False,
			loc="lower center",
			bbox_to_anchor=(0.5, 1.0),
			ncol=3,
			handlelength=1.5,
			columnspacing=0.9,
			handletextpad=0.45,
			borderpad=0.1,
		)
		self._style_axes(ax)
		return self._save(fig, path)

	# ------------------------------------------------------------------
	# 图 9：时限严格度与服务类型选择
	# ------------------------------------------------------------------
	def plot_deadline_service(self, rows: list, points: list, path: str, sweep: list = None) -> list:
		"""运到时限严格度与服务类型选择。

		横轴为运到时限、纵轴为最小可行总成本：时限放宽到某个临界值之前，只能用
		快速班列；越过临界值后成本阶跃下降（改用集装箱班列）。竖虚线给出三档时限。
		"""
		fig = self._figure(PlotProperties.FIG_WIDTH_CM_SINGLE, aspect=0.82)
		ax = fig.add_subplot(111)

		valid = [item for item in (sweep or []) if item.get("cost") is not None]
		if not valid:
			self._save(fig, path)
			return [f"{path}"]
		xs = [item["deadline"] for item in valid]
		ys = [item["cost"] / 1000.0 for item in valid]
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
				(middle["deadline"], middle["cost"] / 1000.0),
				textcoords="offset points",
				xytext=(0, 10),
				ha="center",
				va="bottom",
				fontsize=PlotProperties.FONT_SIZE_ANNOTATION,
				zorder=6,
			)

		span = max(xs) - min(xs)
		ax.set_xlim(min(xs) - span * 0.06, max(xs) + span * 0.05)
		width = max(ys) - min(ys)
		ax.set_ylim(min(ys) - width * 0.22, max(ys) + width * 0.30)
		top = max(ys) + width * 0.28
		middle_x = (min(xs) + max(xs)) / 2.0
		for row in rows:
			ax.axvline(
				row["deadline"],
				color=ColorPalette.SLATE,
				lw=0.8,
				ls=(0, (3, 2)),
				zorder=1,
			)
			ax.annotate(
				f"{row['label']}\nD={row['deadline']:.1f}",
				(row["deadline"], top),
				textcoords="offset points",
				xytext=(-2 if row["deadline"] > middle_x else 2, -2),
				ha="right" if row["deadline"] > middle_x else "left",
				va="top",
				fontsize=PlotProperties.FONT_SIZE_ANNOTATION - 0.4,
				color=ColorPalette.SLATE,
				linespacing=1.1,
				zorder=6,
			)

		# 时限过紧导致无可行解的区间：淡灰底提示
		if len(valid) < len(sweep):
			first = min(item["deadline"] for item in sweep if item.get("cost") is None)
			ax.axvspan(min(item["deadline"] for item in sweep), first,
					   color=ColorPalette.DEFAULT_GRAY, alpha=0.10, zorder=0)

		ax.set_xlabel("运到时限 D / h")
		ax.set_ylabel("最小可行总成本 / 千元")
		legend_items = [
			Line2D([0], [0], color=ColorPalette.DEFAULT_BLACK, lw=PlotProperties.LINE_WIDTH_AUX,
				   marker="o", markerfacecolor=ColorPalette.DEFAULT_WHITE,
				   markeredgecolor=ColorPalette.DEFAULT_BLACK, markersize=4.2,
				   label="最小可行成本"),
			Line2D([0], [0], color=ColorPalette.SLATE, lw=0.8, ls=(0, (3, 2)),
				   label="时限档位"),
		]
		ax.legend(handles=legend_items, frameon=False, loc="lower left",
				  handlelength=1.9, handletextpad=0.5, labelspacing=0.3, borderpad=0.1)
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
