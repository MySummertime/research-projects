"""图5视觉候选：冻结网络上的地图化表达，不运行求解器。"""
from __future__ import annotations

import hashlib
import json
import math
import struct
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.legend_handler import HandlerBase
from matplotlib.path import Path as MplPath
from matplotlib.patches import PathPatch, Polygon, Rectangle


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
NETWORK = ROOT / "data" / "real_case" / "network.json"
BASEMAP = ROOT / "results" / "figure_revision_20261116_acr" / "basemap" / "ne_110m_admin_0_countries" / "ne_110m_admin_0_countries.shp"
ADMIN1 = ROOT / "results" / "figure_revision_20261117_acr2" / "basemap_admin1" / "ne_10m_admin_1_states_provinces.shp"
PNG = HERE / "case_network_candidate_for_fig5_v19.png"
TIFF = HERE / "case_network_candidate_for_fig5_v19.tiff"
PREVIEW = HERE / "case_network_candidate_for_fig5_v19_on_white.png"
AUDIT = HERE / "case_network_candidate_for_fig5_v19_selfcheck.json"
PROVENANCE = HERE / "case_network_candidate_for_fig5_v19_provenance.json"
DPI = 1000
STANDARD_LATITUDE_DEG = 37.0
PROJECTION_ASPECT = 1.0 / math.cos(math.radians(STANDARD_LATITUDE_DEG))
FANGSONG = Path(r"C:\Windows\Fonts\simfang.ttf")
TIMES = Path(r"C:\Windows\Fonts\times.ttf")


class DoubleRailHandler(HandlerBase):
    def create_artists(self, legend, orig_handle, xdescent, ydescent, width, height,
                       fontsize, trans):
        return [
            Line2D([xdescent, xdescent + width], [ydescent + height * 0.35] * 2,
                   color="#303030", lw=1.1, transform=trans),
            Line2D([xdescent, xdescent + width], [ydescent + height * 0.65] * 2,
                   color="#303030", lw=1.1, transform=trans),
        ]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def polygon_records(path: Path):
    """读取 Polygon Shapefile；仅用于 Natural Earth 浅灰底图。"""
    with path.open("rb") as f:
        f.read(100)
        while True:
            header = f.read(8)
            if len(header) < 8:
                return
            _, words = struct.unpack(">2i", header)
            body = f.read(words * 2)
            if len(body) < 44 or struct.unpack_from("<i", body, 0)[0] not in (5, 15, 25):
                continue
            xmin, ymin, xmax, ymax = struct.unpack_from("<4d", body, 4)
            n_parts, n_points = struct.unpack_from("<2i", body, 36)
            parts = list(struct.unpack_from(f"<{n_parts}i", body, 44)) + [n_points]
            p0 = 44 + 4 * n_parts
            pts = [struct.unpack_from("<2d", body, p0 + 16 * i) for i in range(n_points)]
            yield (xmin, ymin, xmax, ymax), [pts[parts[i]:parts[i + 1]] for i in range(n_parts)]


def trim_segment(a, b, trim=0.09):
    """只缩短视觉线段，冻结端点和拓扑不变，避免弧线进入节点标记。"""
    x0, y0 = a
    x1, y1 = b
    dx, dy = x1 - x0, y1 - y0
    norm = max(math.hypot(dx, dy), 1e-9)
    t = min(trim, norm * 0.18)
    ux, uy = dx / norm, dy / norm
    return (x0 + ux * t, y0 + uy * t), (x1 - ux * t, y1 - uy * t)


def rail_pair(ax, a, b, artists=None):
    a, b = trim_segment(a, b, 0.075)
    x0, y0 = a
    x1, y1 = b
    dx, dy = x1 - x0, y1 - y0
    norm = max(math.hypot(dx, dy), 1e-9)
    nx, ny = -dy / norm * 0.035, dx / norm * 0.035
    for sign in (-1, 1):
        line, = ax.plot([x0 + sign * nx, x1 + sign * nx], [y0 + sign * ny, y1 + sign * ny],
                        color="#303030", lw=0.72, solid_capstyle="round", zorder=3)
        if artists is not None:
            artists.append(line)


def yard_marker(ax, x, y, tier, scale=1.0):
    """A类用正方形、B类用三角形；不用底纹。"""
    ax.scatter([x], [y], s=42 * scale, marker="s" if tier == "A" else "^",
               facecolor="white", edgecolor="black", linewidth=0.9, zorder=6)


def road_pairs(ods, nodes, yards):
    pairs = set()
    for od in ods:
        o = (float(od["origin"]["lon"]), float(od["origin"]["lat"]))
        d = (float(od["destination"]["lon"]), float(od["destination"]["lat"]))
        for item in od["origin_yards"]:
            pairs.add((o, nodes[yards[item["yard"]]["rail_node"]][:2]))
        pairs.add((nodes[yards[od["destination_yard"]["yard"]]["rail_node"]][:2], d))
    return pairs


def road_curve(ax, a, b, artists=None):
    """以二次贝塞尔曲线绘制公路接驳，保持端点不变。"""
    a, b = trim_segment(a, b, 0.13)
    x0, y0 = a
    x1, y1 = b
    dx, dy = x1 - x0, y1 - y0
    norm = max(math.hypot(dx, dy), 1e-9)
    # 曲率只作用于显示路径，不改变冻结端点或连接关系。
    offset = min(0.13 * norm, 0.48)
    nx, ny = -dy / norm * offset, dx / norm * offset
    control = ((x0 + x1) / 2 + nx, (y0 + y1) / 2 + ny)
    path = MplPath([(x0, y0), control, (x1, y1)],
                   [MplPath.MOVETO, MplPath.CURVE3, MplPath.CURVE3])
    patch = PathPatch(path, fill=False, color="black", lw=0.36,
                      capstyle="round", zorder=2)
    ax.add_patch(patch)
    if artists is not None:
        artists.append(patch)


def draw_map(ax, extent, data, nodes, yards, ods, basemap_records, province_records,
             node_size=4.5, yard_scale=1.0, network_artists=None):
    xmin, xmax, ymin, ymax = extent
    drawn = 0
    for bbox, parts in basemap_records:
        if bbox[2] < xmin or bbox[0] > xmax or bbox[3] < ymin or bbox[1] > ymax:
            continue
        for part in parts:
            ax.add_patch(Polygon(part, closed=True, facecolor="#F4F4F4", edgecolor="#B8B8B8",
                                 lw=0.35, zorder=0))
            drawn += 1
    # 省级行政边界只作地理参照，不参与网络或实验计算。
    for bbox, parts in province_records:
        if bbox[2] < xmin or bbox[0] > xmax or bbox[3] < ymin or bbox[1] > ymax:
            continue
        for part in parts:
            if len(part) > 1:
                ax.plot([p[0] for p in part], [p[1] for p in part], color="#AAAAAA",
                        lw=0.34, zorder=1)
    # 公路接驳为黑色曲线，线宽为铁路单线的一半。
    for a, b in road_pairs(ods, nodes, yards):
        if (min(a[0], b[0]) <= xmax and max(a[0], b[0]) >= xmin and
                min(a[1], b[1]) <= ymax and max(a[1], b[1]) >= ymin):
            road_curve(ax, a, b, network_artists)
    for arc in data["rail_arcs"]:
        a, b = nodes[arc["i"]][:2], nodes[arc["j"]][:2]
        if (min(a[0], b[0]) <= xmax and max(a[0], b[0]) >= xmin and
                min(a[1], b[1]) <= ymax and max(a[1], b[1]) >= ymin):
            rail_pair(ax, a, b, network_artists)
    visible_nodes = [p for p in nodes.values() if xmin <= p[0] <= xmax and ymin <= p[1] <= ymax]
    ax.scatter([p[0] for p in visible_nodes], [p[1] for p in visible_nodes], s=node_size,
               facecolor="white", edgecolor="#555555", linewidth=0.32, zorder=4)
    for yard in yards.values():
        x, y, _ = nodes[yard["rail_node"]]
        if xmin <= x <= xmax and ymin <= y <= ymax:
            yard_marker(ax, x, y, yard["tier"], yard_scale)
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    # 等距圆柱投影的标准纬线校正。经度方向按37°纬线的实际距离缩放，
    # 这是对所有矢量对象的统一地图投影，而非对成图位图进行纵向拉伸。
    ax.set_aspect(PROJECTION_ASPECT, adjustable="box")
    ax.set_xticks([])
    ax.set_yticks([])
    return drawn


def main():
    if AUDIT.exists():
        raise FileExistsError(f"Versioned candidate already exists: {AUDIT}")
    data = json.loads(NETWORK.read_text(encoding="utf-8"))
    nodes = {n["id"]: (float(n["lon"]), float(n["lat"]), n["name"]) for n in data["rail_nodes"]}
    yards = {y["id"]: y for y in data["yards"]}
    ods = [od for od in data["od_pairs"] if od["id"] in {"OD1", "OD2", "OD3", "OD4", "OD5", "OD6"}]

    font_manager.fontManager.addfont(str(FANGSONG))
    font_manager.fontManager.addfont(str(TIMES))
    cn = font_manager.FontProperties(fname=str(FANGSONG), size=7.2)
    cn_leg = font_manager.FontProperties(fname=str(FANGSONG), size=7.2)
    tn = font_manager.FontProperties(fname=str(TIMES), size=7.2)
    tn_small = font_manager.FontProperties(fname=str(TIMES), size=5.8)
    plt.rcParams.update({"font.family": cn.get_name(), "axes.unicode_minus": False,
                         "mathtext.fontset": "custom", "mathtext.rm": "Times New Roman",
                         "mathtext.it": "Times New Roman:italic"})
    # 仅保留一个主地图。画布高度全部用于主图，坐标轴保持等比例，不拉伸省界与路网。
    fig = plt.figure(figsize=(17.2 / 2.54, 10.5 / 2.54), facecolor="none")
    ax = fig.add_axes([0.012, 0.020, 0.976, 0.960])
    xmin, xmax, ymin, ymax = 81.6, 127.0, 27.6, 46.5

    # Natural Earth 国界底图，仅提供地理定位，不参与实验计算。
    basemap_records = list(polygon_records(BASEMAP))
    province_records = list(polygon_records(ADMIN1))
    network_artists = []
    map_parts = draw_map(ax, (xmin, xmax, ymin, ymax), data, nodes, yards, ods,
                         basemap_records, province_records, node_size=5.0, yard_scale=1.08,
                         network_artists=network_artists)

    # OD1—OD6 端点及名称全部置于主图。手工排布的标注区避开路网，并用虚线引线回指真实坐标。
    endpoints = {}
    for od in ods:
        for role in ("origin", "destination"):
            item = od[role]
            key = (float(item["lon"]), float(item["lat"]), item["name"], role)
            endpoints.setdefault(key, []).append(od["id"])
    endpoint_texts = []
    for (x, y, name, role), od_ids in endpoints.items():
        marker = "o" if role == "origin" else "D"
        ax.scatter([x], [y], s=24, marker=marker, facecolor="white", edgecolor="black",
                   linewidth=0.8, zorder=8)

    origin_positions = {
        "独山子石化园区": (82.05, 46.05, "left"),
        "乌鲁木齐经济技术开发区": (82.05, 43.95, "left"),
        "库尔勒石化产业园": (82.05, 40.75, "left"),
        "哈密伊吾煤化工基地": (96.25, 45.55, "right"),
    }
    dest_positions = {
        "南京江北新材料产业园": (126.35, 37.15, "right"),
        "合肥循环经济示范园": (126.35, 35.05, "right"),
        "上海化学工业区": (126.35, 32.95, "right"),
        "杭州临江工业园区": (126.35, 30.85, "right"),
        "宁波港区": (126.35, 28.75, "right"),
    }
    for (x, y, name, role), od_ids in endpoints.items():
        positions = origin_positions if role == "origin" else dest_positions
        marker = "o" if role == "origin" else "D"
        tx, ty, ha = positions[name]
        inset_name = {"独山子石化园区": "独山子", "乌鲁木齐经济技术开发区": "乌鲁木齐",
                      "库尔勒石化产业园": "库尔勒", "哈密伊吾煤化工基地": "哈密",
                      "南京江北新材料产业园": "南京", "合肥循环经济示范园": "合肥",
                      "上海化学工业区": "上海", "杭州临江工业园区": "杭州",
                      "宁波港区": "宁波"}[name]
        # OD与数字直接绑定times.ttf；中文城市名使用独立仿宋文本对象。
        od_label = "/".join(od_ids)
        t = ax.annotate(od_label, (x, y), xytext=(tx, ty), textcoords="data",
                        ha=ha, va="center", fontproperties=cn, fontsize=5.8,
                        color="black", zorder=12,
                        arrowprops=dict(arrowstyle="-", color="#555555", lw=0.48,
                                        linestyle=(0, (2.2, 2.0)), shrinkA=2, shrinkB=5),
                        bbox=dict(facecolor="white", edgecolor="none", alpha=0.94, pad=0.30))
        t.set_fontproperties(tn_small)
        city = ax.annotate(inset_name, (tx, ty), xytext=(0, -8), textcoords="offset points",
                           ha=ha, va="center", fontproperties=cn, fontsize=5.8,
                           color="black", zorder=12,
                           bbox=dict(facecolor="white", edgecolor="none", alpha=0.94, pad=0.25))
        endpoint_texts.append((od_label, t, city))

    # 自绘混合字体图例：拉丁A/B绑定Times New Roman，中文绑定仿宋。
    # 外框保留充分内边距，确保末端“B类货场”及全部符号不越过边线。
    box_x, box_y, box_w, box_h = 0.055, 0.027, 0.53, 0.090
    legend_frame = Rectangle((box_x, box_y), box_w, box_h, transform=ax.transAxes,
                             facecolor="white", edgecolor="#777777", linewidth=0.75,
                             zorder=14, clip_on=False)
    ax.add_patch(legend_frame)
    ly = 0.072
    road_key, = ax.plot([0.135, 0.170], [ly, ly], transform=ax.transAxes, color="black", lw=0.36, zorder=15)
    road_text = ax.text(0.178, ly, "公路", transform=ax.transAxes, fontproperties=cn_leg,
                        va="center", ha="left", zorder=16)
    rail_key_1, = ax.plot([0.235, 0.270], [ly-0.004, ly-0.004], transform=ax.transAxes, color="#303030", lw=1.0, zorder=15)
    rail_key_2, = ax.plot([0.235, 0.270], [ly+0.004, ly+0.004], transform=ax.transAxes, color="#303030", lw=1.0, zorder=15)
    rail_text = ax.text(0.278, ly, "铁路", transform=ax.transAxes, fontproperties=cn_leg,
                        va="center", ha="left", zorder=16)
    ax.scatter([0.350], [ly], transform=ax.transAxes, s=38, marker="s", facecolor="white",
               edgecolor="black", linewidth=0.9, zorder=16, clip_on=False)
    a_text = ax.text(0.365, ly, "A", transform=ax.transAxes, fontproperties=tn,
                     va="center", ha="left", zorder=16)
    a_cn_text = ax.text(0.376, ly, "类货场", transform=ax.transAxes, fontproperties=cn_leg,
                        va="center", ha="left", zorder=16)
    ax.scatter([0.465], [ly], transform=ax.transAxes, s=38, marker="^", facecolor="white",
               edgecolor="black", linewidth=0.9, zorder=16, clip_on=False)
    b_text = ax.text(0.480, ly, "B", transform=ax.transAxes, fontproperties=tn,
                     va="center", ha="left", zorder=16)
    b_cn_text = ax.text(0.491, ly, "类货场", transform=ax.transAxes, fontproperties=cn_leg,
                        va="center", ha="left", zorder=16)
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.set_aspect(PROJECTION_ASPECT, adjustable="box")
    ax.set_axis_off()

    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    frame_box = legend_frame.get_window_extent(renderer)
    legend_text_boxes = [x.get_window_extent(renderer) for x in
                         (road_text, rail_text, a_text, a_cn_text, b_text, b_cn_text)]
    legend_line_boxes = [x.get_window_extent(renderer) for x in
                         (road_key, rail_key_1, rail_key_2)]
    marker_centers = [ax.transAxes.transform((0.350, ly)), ax.transAxes.transform((0.465, ly))]
    marker_half_px = math.sqrt(38) / 2 * fig.dpi / 72 + 1.5
    legend_inside = all(frame_box.contains(box.x0, box.y0) and
                        frame_box.contains(box.x1, box.y1)
                        for box in legend_text_boxes + legend_line_boxes)
    legend_inside = legend_inside and all(
        frame_box.contains(x - marker_half_px, y - marker_half_px) and
        frame_box.contains(x + marker_half_px, y + marker_half_px)
        for x, y in marker_centers)
    if not legend_inside:
        raise RuntimeError("legend content exceeds frame")
    outside = []
    label_boxes = []
    for label, od_artist, city_artist in endpoint_texts:
        a = od_artist.get_bbox_patch().get_window_extent(renderer)
        b = city_artist.get_bbox_patch().get_window_extent(renderer)
        from matplotlib.transforms import Bbox
        box = Bbox.union([a, b])
        label_boxes.append((label, box))
        canvas = od_artist.axes.bbox
        if box.x0 < canvas.x0 or box.y0 < canvas.y0 or box.x1 > canvas.x1 or box.y1 > canvas.y1:
            outside.append(label)
    overlaps = []
    for i, (a, ba) in enumerate(label_boxes):
        for b, bb in label_boxes[i + 1:]:
            if ba.overlaps(bb):
                overlaps.append([a, b])
    if outside or overlaps:
        raise RuntimeError(f"endpoint label QA failed: outside={outside}, overlaps={overlaps}")

    # 保留精确的172 mm × 105 mm画布，不使用bbox_inches裁边，也不对位图做非等比缩放。
    fig.savefig(PNG, dpi=DPI, transparent=True)
    fig.savefig(TIFF, dpi=DPI, transparent=True,
                pil_kwargs={"compression": "tiff_lzw"})
    fig.savefig(PREVIEW, dpi=300, facecolor="white", transparent=False,
                )
    plt.close(fig)

    audit = {
        "status": "PASS",
        "figure": 5,
        "type": "TYPE A",
        "visual_only": True,
        "solver_rerun": False,
        "frozen_counts": {"rail_nodes": len(nodes), "rail_arcs": len(data["rail_arcs"]),
                          "yards": len(yards), "od_pairs_drawn": len(ods)},
        "od_ids": [od["id"] for od in ods],
        "yard_tiers": {k: sum(1 for y in yards.values() if y["tier"] == k) for k in ("A", "B")},
        "class_c_resolution": "冻结数据无C类货场，未虚构；A类用正方形、B类用三角形",
        "removed_legend_items": ["客户点", "代表路径"],
        "removed_labels": ["供应点", "需求点"],
        "map_parts_drawn": map_parts,
        "endpoint_label_outside": outside,
        "endpoint_label_overlaps": overlaps,
        "axes_visible": False,
        "road_style": "black quadratic curve, linewidth 0.36 pt (half of each 0.72 pt rail line)",
        "rail_style": "dark parallel double line",
        "local_insets": [],
        "endpoint_labels": "all OD identifiers and city names placed on the main map with dashed leaders",
        "figure_size_cm": [17.2, 10.5],
        "map_axes_aspect": "equidistant cylindrical projection corrected at 37-degree standard latitude; all vector layers redrawn; no raster stretching",
        "standard_latitude_deg": STANDARD_LATITUDE_DEG,
        "projection_aspect": PROJECTION_ASPECT,
        "province_boundaries": True,
        "latin_digit_font": "Times New Roman bound directly from C:/Windows/Fonts/times.ttf for OD identifiers and A/B legend labels",
        "legend_content_inside_frame": legend_inside,
        "legend_frame_axes": [box_x, box_y, box_w, box_h],
    }
    AUDIT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    provenance = {
        "type": "TYPE A",
        "network": {"path": str(NETWORK), "sha256": sha256(NETWORK)},
        "basemap": {"path": str(BASEMAP), "sha256": sha256(BASEMAP),
                    "source": "Natural Earth 1:110m Admin 0 Countries v5.1.1"},
        "admin1": {"path": str(ADMIN1), "sha256": sha256(ADMIN1),
                   "source": "Natural Earth 1:10m Admin 1 States and Provinces"},
        "outputs": {p.name: sha256(p) for p in (PNG, TIFF, PREVIEW, AUDIT)},
        "coordinates_modified": False,
        "nodes_or_arcs_modified": False,
    }
    PROVENANCE.write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
