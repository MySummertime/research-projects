"""生成"新疆—长三角"危险货物公铁联运算例的路网文件 network.json。

数据来源与可信度（论文 4.1 的三档口径）：
	A 级（公开里程表）：兰新线兰州—乌鲁木齐南 1 892 km（逐站里程）；陇海线
	兰州—连云港东 1 759 km（商丘站距兰州 1 390、距连云港东 369）；宁西线
	西安—南京 1 075.69 km（含 72 km 汉丹联络线）；京沪线徐州—上海 649 km
	（南京—上海 303）；沪杭 190、萧甬 148；淮南线淮南—芜湖 214.7；阜淮线
	127.3；京九线商丘南—潢川 294 km（商丘南距北京西 687 / 亳州 751 / 阜阳 855
	/ 潢川 971）；皖赣线芜宣段 73.32；宣杭线 224；南疆线吐鲁番—库尔勒
	（吐库二线）334；北疆线乌鲁木齐—奎屯 241（奎屯站）；乌鲁木齐枢纽联络线
	10；商丘枢纽联络线（陇海—京九）6。宁芜线因扩能改造未完工（2022 年开工、
	计划 2027 年底完成），暂不纳入。
	B 级（按全长与站间距推算）：宁西线各站里程、京沪线中间站里程、沪杭与宣杭
	中间站里程、车站经纬度（地图服务地理编码）。
	C 级（本文设定）：货场等级、接驳公路里程、OD 需求与品类。

命名口径：线路名取《铁路线路名称表》的正式简称；节点名为线路里程表上的车站名，
货场名与所在车站一致，具体办理站（编组站、货场、港区）另由 facility 字段注明，
避免出现"货场名与车站名不符"的指代歧义。

用法：python data/real_case_xj_yrd/build_network.py
"""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(HERE, "network.json")

# ----------------------------------------------------------------------
# 线路站表：(站点编号, 站名, 经度, 纬度, 自起点累计里程 km)
# ----------------------------------------------------------------------
LINES = {
	"兰新线": [
		("LZ", "兰州", 103.79, 36.06, 0.0),
		("YD", "永登", 103.26, 36.74, 111.0),
		("GL", "古浪", 102.89, 37.47, 244.0),
		("WWN", "武威南", 102.68, 37.90, 290.0),
		("JC", "金昌", 102.19, 38.50, 377.0),
		("SD", "山丹", 101.09, 38.79, 494.0),
		("ZY", "张掖", 100.45, 38.93, 547.0),
		("QS", "清水", 98.87, 39.42, 684.0),
		("JQ", "酒泉", 98.49, 39.73, 748.0),
		("JYG", "嘉峪关", 98.22, 39.80, 770.0),
		("YM", "玉门", 97.05, 40.29, 902.0),
		("LY", "柳园", 95.51, 41.09, 1067.0),
		("HM", "哈密", 93.51, 42.82, 1339.0),
		("SS", "鄯善", 90.21, 42.87, 1609.0),
		("TLF", "吐鲁番", 89.19, 42.95, 1749.0),
		("WLMQN", "乌鲁木齐南", 87.60, 43.75, 1892.0),
	],
	"北疆线": [
		("WLMQ", "乌鲁木齐", 87.62, 43.79, 0.0),
		("WLMQX", "乌鲁木齐西", 87.45, 43.80, 12.0),
		("CJ", "昌吉", 87.30, 44.01, 35.0),
		("HTB", "呼图壁", 86.90, 44.19, 78.0),
		("SHZ", "石河子", 86.08, 44.31, 145.0),
		("SW", "沙湾", 85.62, 44.33, 179.0),
		("KT", "奎屯", 84.90, 44.43, 241.0),
	],
	"乌鲁木齐枢纽联络线": [
		("WLMQN", "乌鲁木齐南", 87.60, 43.75, 0.0),
		("WLMQ", "乌鲁木齐", 87.62, 43.79, 10.0),
	],
	"商丘枢纽联络线": [
		("SQ", "商丘", 115.65, 34.41, 0.0),
		("SQN", "商丘南", 115.70, 34.41, 6.0),
	],
	"南疆线": [
		("TLF", "吐鲁番", 89.19, 42.95, 0.0),
		("KEL", "库尔勒", 86.15, 41.76, 334.0),
	],
	"陇海线": [
		("LZ", "兰州", 103.79, 36.06, 0.0),
		("DX", "定西", 104.62, 35.58, 118.0),
		("LX", "陇西", 104.63, 35.00, 221.0),
		("TS", "天水", 105.72, 34.58, 351.0),
		("BJ", "宝鸡", 107.14, 34.36, 503.0),
		("SFZ", "西安", 108.95, 34.27, 676.0),
		("SMX", "三门峡", 111.19, 34.78, 923.0),
		("LYY", "洛阳", 112.45, 34.62, 1063.0),
		("ZZ", "郑州", 113.65, 34.76, 1187.0),
		("KF", "开封", 114.31, 34.80, 1259.0),
		("SQ", "商丘", 115.65, 34.41, 1390.0),
		("XZ", "徐州", 117.18, 34.26, 1536.0),
		("LYG", "连云港东", 119.36, 34.73, 1759.0),
	],
	"宁西线": [
		("SFZ", "西安", 108.95, 34.27, 0.0),
		("SL", "商洛", 109.94, 33.87, 195.0),
		("SN", "商南", 110.88, 33.53, 285.0),
		("XX", "西峡", 111.47, 33.30, 335.0),
		("NY", "南阳", 112.53, 33.00, 420.0),
		("XY", "信阳", 114.09, 32.13, 600.0),
		("HC", "潢川", 115.05, 32.13, 700.0),
		("YJ", "叶集", 115.93, 31.86, 765.0),
		("LA", "六安", 116.51, 31.75, 840.0),
		("HF", "合肥", 117.20, 31.78, 920.0),
		("QJ", "全椒", 118.27, 32.09, 1000.0),
		("NJ", "南京", 118.80, 32.06, 1075.69),
	],
	"京沪线": [
		("XZ", "徐州", 117.18, 34.26, 0.0),
		("BB", "蚌埠", 117.36, 32.92, 178.0),
		("NJ", "南京", 118.80, 32.06, 346.0),
		("ZJ", "镇江", 119.45, 32.20, 410.0),
		("CZ", "常州", 119.97, 31.81, 481.0),
		("WX", "无锡", 120.30, 31.57, 520.0),
		("SZ", "苏州", 120.62, 31.30, 562.0),
		("SH", "上海", 121.45, 31.24, 649.0),
	],
	"沪杭线": [
		("SH", "上海", 121.45, 31.24, 0.0),
		("JX", "嘉兴", 120.75, 30.76, 100.0),
		("HZ", "杭州", 120.17, 30.27, 190.0),
	],
	"萧甬线": [
		("HZ", "杭州", 120.17, 30.27, 0.0),
		("SX", "绍兴", 120.58, 30.00, 43.0),
		("YY", "余姚", 121.15, 30.04, 100.0),
		("NB", "宁波", 121.55, 29.87, 148.0),
	],
	"淮南线": [
		("HN", "淮南", 117.00, 32.63, 0.0),
		("HF", "合肥", 117.20, 31.78, 90.0),
		("WH", "芜湖", 118.38, 31.33, 214.7),
	],
	"阜淮线": [
		("FY", "阜阳", 115.81, 32.89, 0.0),
		("HN", "淮南", 117.00, 32.63, 127.3),
	],
	"京九线": [
		("SQN", "商丘南", 115.70, 34.41, 0.0),
		("BZ", "亳州", 115.78, 33.87, 74.0),
		("FY", "阜阳", 115.81, 32.89, 178.0),
		("HC", "潢川", 115.05, 32.13, 294.0),
	],
	"皖赣线": [
		("WH", "芜湖", 118.38, 31.33, 0.0),
		("XC", "宣城", 118.76, 30.94, 73.32),
	],
	"宣杭线": [
		("XC", "宣城", 118.76, 30.94, 0.0),
		("CX", "长兴", 119.91, 31.00, 122.0),
		("HZ", "杭州", 120.17, 30.27, 224.0),
	],
}

# ----------------------------------------------------------------------
# 线路里程基准：(起讫站, 全长 km, 可信度, 口径说明)
# 用于 verify() 的逐线自洽校验，并随 network.json 输出备查
# ----------------------------------------------------------------------
LINE_META = {
	"兰新线": ("兰州—乌鲁木齐南", 1892.0, "A", "逐站里程累计"),
	"北疆线": ("乌鲁木齐—奎屯", 241.0, "A", "奎屯站距乌鲁木齐 241 km"),
	"乌鲁木齐枢纽联络线": ("乌鲁木齐南—乌鲁木齐", 10.0, "B", "枢纽联络线，按站间距计"),
	"商丘枢纽联络线": ("商丘—商丘南", 6.0, "A", "陇海-京九联络线 6 km"),
	"南疆线": ("吐鲁番—库尔勒", 334.0, "A", "吐库二线运营里程，较既有线缩短 123 km"),
	"陇海线": ("兰州—连云港东", 1759.0, "A", "商丘距兰州 1 390、距连云港东 369"),
	"宁西线": ("西安—南京", 1075.69, "A", "含 72 km 汉丹联络线"),
	"京沪线": ("徐州—上海", 649.0, "A", "南京—上海 303"),
	"沪杭线": ("上海—杭州", 190.0, "A", ""),
	"萧甬线": ("杭州—宁波", 148.0, "A", ""),
	"淮南线": ("淮南—芜湖", 214.7, "A", ""),
	"阜淮线": ("阜阳—淮南", 127.3, "A", ""),
	"京九线": ("商丘南—潢川", 294.0, "A", "商丘南距北京西 687／亳州 751／阜阳 855／潢川 971"),
	"皖赣线": ("芜湖—宣城", 73.32, "A", "芜宣段扩能改造里程 73.321 km"),
	"宣杭线": ("宣城—杭州", 224.0, "A", ""),
}

# ----------------------------------------------------------------------
# 候选货场：tier A = 危险货物专办站（S1），B = 普通货场可换装（S2）
# 字段：编号、货场名、所在铁路节点、等级、具体办理设施
# 货场与所在车站同址；名称取现实中实际办理危险货物的货场或编组站
# ----------------------------------------------------------------------
YARDS = [
	("Y1", "乌鲁木齐西", "WLMQX", "A", "乌鲁木齐西货场"),
	("Y2", "石河子", "SHZ", "B", "石河子货场"),
	("Y3", "奎屯", "KT", "A", "奎屯货场"),
	("Y4", "库尔勒", "KEL", "A", "库尔勒货场"),
	("Y5", "哈密", "HM", "A", "哈密货场"),
	("Y6", "吐鲁番", "TLF", "B", "吐鲁番货场"),
	("Y7", "嘉峪关", "JYG", "B", "嘉峪关货场"),
	("Y8", "兰州北", "LZ", "A", "兰州北编组站"),
	("Y9", "西安", "SFZ", "A", "新丰镇编组站"),
	("Y10", "郑州北", "ZZ", "B", "郑州北编组站"),
	("Y11", "商丘", "SQ", "B", "商丘货场"),
	("Y12", "阜阳", "FY", "B", "阜阳北编组站"),
	("Y13", "合肥东", "HF", "A", "合肥东编组站"),
	("Y14", "芜湖", "WH", "A", "芜湖东编组站"),
	("Y15", "南京东", "NJ", "A", "南京东编组站"),
	("Y16", "上海桃浦", "SH", "A", "桃浦货场"),
	("Y17", "杭州北", "HZ", "A", "杭州北货场"),
	("Y18", "宁波北", "NB", "A", "宁波北货场"),
]

# ----------------------------------------------------------------------
# OD 对：每条承担一项论证任务
# ----------------------------------------------------------------------
OD_PAIRS = [
	{
		"id": "OD1",
		"task": "干线三通道主对比：兰新—陇海—宁西/京沪/京九三条径路同时可行",
		"hazmat": 8,
		"demand_boxes": 24.0,
		"origin": {"name": "乌鲁木齐经济技术开发区", "lon": 87.58, "lat": 43.86},
		"destination": {"name": "上海化学工业区", "lon": 121.35, "lat": 30.85},
		"origin_yards": [{"yard": "Y1", "km": 28.0}, {"yard": "Y2", "km": 150.0}, {"yard": "Y3", "km": 262.0}],
		"destination_yard": {"yard": "Y16", "km": 55.0},
		"transit_yards": ["Y8", "Y9", "Y10", "Y11", "Y15", "Y14"],
		"deadline_h": None,
	},
	{
		"id": "OD2",
		"task": "到达端分流：上海与杭州的通道分工（沪杭 vs 宣杭）",
		"hazmat": 3,
		"demand_boxes": 12.0,
		"origin": {"name": "乌鲁木齐经济技术开发区", "lon": 87.58, "lat": 43.86},
		"destination": {"name": "杭州临江工业园区", "lon": 120.60, "lat": 30.20},
		"origin_yards": [{"yard": "Y1", "km": 28.0}, {"yard": "Y2", "km": 150.0}, {"yard": "Y3", "km": 262.0}],
		"destination_yard": {"yard": "Y17", "km": 35.0},
		"transit_yards": ["Y8", "Y9", "Y11", "Y12", "Y14", "Y13"],
		"deadline_h": None,
	},
	{
		"id": "OD3",
		"task": "非乌鲁木齐始发：北疆西向集运距离差异（奎屯 vs 石河子）",
		"hazmat": 6,
		"demand_boxes": 16.0,
		"origin": {"name": "独山子石化园区", "lon": 84.85, "lat": 44.32},
		"destination": {"name": "南京江北新材料产业园", "lon": 118.65, "lat": 32.20},
		"origin_yards": [{"yard": "Y3", "km": 45.0}, {"yard": "Y2", "km": 190.0}, {"yard": "Y1", "km": 265.0}],
		"destination_yard": {"yard": "Y15", "km": 25.0},
		"transit_yards": ["Y8", "Y9", "Y10", "Y11", "Y14"],
		"deadline_h": None,
	},
	{
		"id": "OD4",
		"task": "宁西线与阜淮线形成\"短里程 vs 少转运\"权衡",
		"hazmat": 8,
		"demand_boxes": 10.0,
		"origin": {"name": "独山子石化园区", "lon": 84.85, "lat": 44.32},
		"destination": {"name": "合肥循环经济示范园", "lon": 117.40, "lat": 31.72},
		"origin_yards": [{"yard": "Y3", "km": 45.0}, {"yard": "Y2", "km": 190.0}, {"yard": "Y1", "km": 265.0}],
		"destination_yard": {"yard": "Y13", "km": 20.0},
		"transit_yards": ["Y8", "Y9", "Y11", "Y12", "Y14"],
		"deadline_h": None,
	},
	{
		"id": "OD5",
		"task": "支线强制转运：南疆线至吐鲁番方能上兰新干线",
		"hazmat": 8,
		"demand_boxes": 8.0,
		"origin": {"name": "库尔勒石化产业园", "lon": 86.10, "lat": 41.70},
		"destination": {"name": "上海化学工业区", "lon": 121.35, "lat": 30.85},
		"origin_yards": [{"yard": "Y4", "km": 25.0}, {"yard": "Y6", "km": 350.0}, {"yard": "Y5", "km": 720.0}],
		"destination_yard": {"yard": "Y16", "km": 55.0},
		"transit_yards": ["Y6", "Y8", "Y9", "Y11", "Y15"],
		"deadline_h": None,
	},
	{
		"id": "OD6",
		"task": "东疆短程集运 + 末端萧甬线延伸再转运",
		"hazmat": 3,
		"demand_boxes": 6.0,
		"origin": {"name": "哈密伊吾煤化工基地", "lon": 94.70, "lat": 43.30},
		"destination": {"name": "宁波港区", "lon": 121.87, "lat": 29.90},
		"origin_yards": [{"yard": "Y5", "km": 65.0}, {"yard": "Y7", "km": 560.0}, {"yard": "Y6", "km": 620.0}],
		"destination_yard": {"yard": "Y18", "km": 15.0},
		"transit_yards": ["Y7", "Y8", "Y9", "Y11", "Y12", "Y14"],
		"deadline_h": None,
	},
]


# ----------------------------------------------------------------------
# 生成与校验
# ----------------------------------------------------------------------
def build() -> dict:
	nodes: dict = {}
	arcs: list = []
	for line, stations in LINES.items():
		for sid, name, lon, lat, km in stations:
			previous = nodes.get(sid)
			if previous is None:
				nodes[sid] = {"id": sid, "name": name, "lon": lon, "lat": lat}
			elif previous["name"] != name:
				raise ValueError(f"站点编号 {sid} 被复用于不同站名：{previous['name']} / {name}")
		for left, right in zip(stations, stations[1:]):
			length = round(right[4] - left[4], 3)
			if length <= 0:
				raise ValueError(f"{line} 里程非单调：{left[0]}→{right[0]} = {length}")
			for a, b in ((left, right), (right, left)):
				arcs.append(
					{
						"i": a[0],
						"j": b[0],
						"km": length,
						"line": line,
					}
				)

	yard_ids = {item[0] for item in YARDS}
	if len(yard_ids) != len(YARDS):
		raise ValueError("货场编号重复")
	yards = [
		{
			"id": yid,
			"name": name,
			"rail_node": rail,
			"station": nodes[rail]["name"],
			"facility": facility,
			"tier": tier,
			"qualified": True,
		}
		for yid, name, rail, tier, facility in YARDS
	]
	for yard in yards:
		if yard["rail_node"] not in nodes:
			raise KeyError(f"货场 {yard['id']} 挂接的铁路节点不存在：{yard['rail_node']}")
	if len({(y["rail_node"]) for y in yards}) != len(yards):
		raise ValueError("两个货场挂接到同一铁路节点，会造成转运弧重复")

	for od in OD_PAIRS:
		for item in od["origin_yards"] + [od["destination_yard"]]:
			if item["yard"] not in yard_ids:
				raise KeyError(f"{od['id']} 引用了不存在的货场：{item['yard']}")
		for yid in od["transit_yards"]:
			if yid not in yard_ids:
				raise KeyError(f"{od['id']} 的中转货场不存在：{yid}")
		# 同一货场可以既是发送端候选、又是干线中途转运点（如 OD5 的吐鲁番：
		# 既可由库尔勒公路集运至此，也是南疆线接入兰新干线的换装点）。
		if od["destination_yard"]["yard"] in od["transit_yards"]:
			raise ValueError(f"{od['id']} 的到达货场不应再作为中途转运点")

	payload = {
		"name": "新疆至长三角危险货物公铁联运路网",
		"version": "xj-yrd-v2",
		"coordinate_system": "lonlat",
		"notes": (
			"里程为公开线路里程（A 级）与按站间距推算（B 级）混合；"
			"货场等级、接驳公路里程、OD 需求与品类亦为本文设定。"
			"货场与所在车站同址，名称取现实中实际办理危险货物的货场或编组站。"
		),
		"line_meta": {
			name: {"section": section, "km": km, "grade": grade, "note": note}
			for name, (section, km, grade, note) in LINE_META.items()
		},
		"rail_nodes": list(nodes.values()),
		"rail_arcs": arcs,
		"yards": yards,
		"od_pairs": OD_PAIRS,
	}
	return payload


def verify(payload: dict) -> None:
	"""里程自洽性校验：逐线累加长度与公开全长比对。"""
	lines: dict = {}
	seen: set = set()
	for arc in payload["rail_arcs"]:
		key = (arc["line"], arc["i"], arc["j"])
		if key in seen:  # 反向弧与正向弧成对出现，里程只计一次
			continue
		seen.add(key)
		seen.add((arc["line"], arc["j"], arc["i"]))
		lines[arc["line"]] = lines.get(arc["line"], 0.0) + arc["km"]
	print(f"铁路节点 {len(payload['rail_nodes'])}，铁路弧 {len(payload['rail_arcs'])}，货场 {len(payload['yards'])}")
	bad = []
	for line, total in lines.items():
		meta = LINE_META.get(line)
		if meta is None:
			bad.append(f"{line} 未登记里程基准")
			continue
		if abs(total - meta[1]) > 1e-6:
			bad.append(f"{line} 合计 {total:.2f} ≠ 基准 {meta[1]:.2f}")
		print(f"  {line:<10} {meta[0]:<22} 合计 {total:>9.2f} km  基准 {meta[1]:>9.2f}")
	for line in LINE_META:
		if line not in lines:
			bad.append(f"{line} 未生成任何弧")
	if bad:
		raise ValueError("里程自洽校验失败：\n  " + "\n  ".join(bad))

	# 径路里程（乌鲁木齐南 → 上海 / 杭州 / 宁波），按弧上真实里程计算
	import heapq

	def shortest(src, dst):
		adj = {}
		for a in payload["rail_arcs"]:
			adj.setdefault(a["i"], []).append((a["j"], a["km"]))
		dist = {src: 0.0}
		pq = [(0.0, src)]
		while pq:
			d, u = heapq.heappop(pq)
			if d != dist.get(u):
				continue
			if u == dst:
				return d
			for v, w in adj.get(u, []):
				nd = d + w
				if nd < dist.get(v, float("inf")):
					dist[v] = nd
					heapq.heappush(pq, (nd, v))
		return None

	print("径路里程核对（自乌鲁木齐南，真实最短路）：")
	for dst, label in (("SH", "上海"), ("HZ", "杭州"), ("NB", "宁波")):
		d = shortest("WLMQN", dst)
		print(f"  → {label:<4} {d:>8.2f} km" if d is not None else f"  → {label}: 不可达")


def main() -> None:
	payload = build()
	verify(payload)
	with open(OUTPUT, "w", encoding="utf-8") as handle:
		json.dump(payload, handle, indent=2, ensure_ascii=False)
	print(f"\n已写入 {OUTPUT}")


if __name__ == "__main__":
	main()
