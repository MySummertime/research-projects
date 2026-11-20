# UTRR - Uncertain Transfer time Road-Rail intermodal routing
# 单一入口：main.py（4.2 主实验）
#
# 论文：不确定转运时间与运到时限下危险货物公铁联运路径优化
#
# 用法：
#   python main.py                       # 主实验（四类方案 + 表 2/2b/3 + 图 5 + 附图 S1）
#   python main.py --mode verify         # 算法精确性校验（双向/剪枝交叉验证）
#   python main.py --mode generate       # 仅构造并导出算例
#   python main.py --mode all            # 主实验 + 全部敏感性实验
#
# 结果写入 results/<实验名>_<时间戳>/，内含 config.json、utrr.log、instance/、
# 表N_*.csv（与同名 .md 三线表）、figN_*.png/.tiff 与 *.json。

from __future__ import annotations

import argparse
import json
import os
import sys

from config import DATA_SOURCE_REAL, DATA_SOURCE_SYNTHETIC, RESULTS_ROOT, UTRRConfig
from src.core.uncertainty import equivalent_time
from src.solvers.baselines import SCHEME_LABELS, knee_point, solve_all_schemes
from src.solvers.label_correcting import ParetoLabelSolver
from src.utils.experiment import finish_run, make_run_dir, start_run
from src.utils.paper_tables import write_table
from src.utils.plotting import Visualizer
from src.utils.reporting import (
	format_instance_report,
	format_pareto_report,
	format_scheme_report,
	path_text,
	route_station_text,
	route_text,
)

EXPERIMENT_NAMES = ("alpha", "sigma", "node_risk", "deadline_service", "scalability")


# ----------------------------------------------------------------------
# 命令行
# ----------------------------------------------------------------------
def parse_args(argv=None):
	defaults = UTRRConfig()
	parser = argparse.ArgumentParser(
		description="UTRR：不确定转运时间与运到时限下危险货物公铁联运路径优化",
		formatter_class=argparse.RawDescriptionHelpFormatter,
		epilog="""
示例：
  python main.py                                  # 主实验
  python main.py --alpha 0.95 --real-case-od 3     # 换置信水平与 OD
  python main.py --mode verify                     # 精确性校验
  python main.py --mode all                        # 主实验 + 5 个敏感性实验
		""",
	)
	parser.add_argument(
		"--mode",
		choices=["main", "verify", "generate", "all"],
		default="main",
		help="执行模式（默认 main）",
	)
	parser.add_argument("--alpha", type=float, default=defaults.alpha, help="置信水平 α")
	parser.add_argument(
		"--confidence-mode",
		choices=["normal"],
		default=defaults.confidence_mode,
		help="λ_α 口径：正态不确定变量分位数（唯一口径）",
	)
	parser.add_argument("--deadline", type=float, default=None, help="直接指定运到时限 D（h）")
	parser.add_argument(
		"--data-source",
		choices=[DATA_SOURCE_REAL, DATA_SOURCE_SYNTHETIC],
		default=defaults.data_source,
		help="算例来源：真实路网 JSON 或合成算例",
	)
	parser.add_argument("--real-case", default=defaults.real_case_path, help="真实路网 JSON 路径")
	parser.add_argument("--real-case-od", type=int, default=defaults.real_case_od, help="选用第几条 OD")
	parser.add_argument("--output", default=RESULTS_ROOT, help="结果根目录")
	parser.add_argument(
		"--no-bidirectional", action="store_true", help="关闭双向汇合，仅作前向标号搜索"
	)
	parser.add_argument("--no-pruning", action="store_true", help="关闭机会可行性与下界剪枝")
	parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
	return parser.parse_args(argv)


def build_config(args) -> UTRRConfig:
	config = UTRRConfig()
	config.alpha = args.alpha
	config.confidence_mode = args.confidence_mode
	if args.deadline is not None:
		config.deadline_hours = args.deadline
	config.data_source = args.data_source
	config.real_case_path = args.real_case
	config.real_case_od = args.real_case_od
	if args.no_bidirectional:
		config.bidirectional = False
	if args.no_pruning:
		config.enable_pruning = False
	return config


# ----------------------------------------------------------------------
# 模式：main（4.2 主实验）
# ----------------------------------------------------------------------
def run_main(config: UTRRConfig, instance, output_dir: str, logger) -> dict:
	logger.info("\n" + "=" * 78)
	logger.info("4.2 基准算例求解与四类方案对比")
	logger.info("=" * 78)
	schemes = solve_all_schemes(config, instance, logger, include_deterministic=False)
	logger.info("\n" + format_pareto_report(schemes["proposed"], instance, config))
	logger.info("\n" + format_scheme_report(schemes, instance, config))

	pareto = schemes["proposed"]["solutions"]
	# 完全前沿（不计运到时限）：用于图 5 对照，说明机会约束截掉了哪一段前沿
	full = ParetoLabelSolver(config, instance, logger).solve_pareto(use_deadline=False)["solutions"]
	logger.info(f"完全前沿 {len(full)} 条；α = {config.alpha:.2f} 下可行前沿 {len(pareto)} 条")
	payload = {
		"experiment": "main",
		"instance": instance.name,
		"data_source": config.data_source,
		"alpha": config.alpha,
		"confidence_mode": config.confidence_mode,
		"deadline_hours": instance.deadline,
		"lambda_alpha": config.lambda_alpha(),
		"pareto_size": len(pareto),
		"full_front_size": len(full),
		"full_front": [s.to_dict(instance.network, config, instance.deadline) for s in full],
		"pareto": [s.to_dict(instance.network, config, instance.deadline) for s in pareto],
		"schemes": {
			key: {
				"label_cn": SCHEME_LABELS[key][0],
				"label_en": SCHEME_LABELS[key][1],
				"representative": (
					None if value["representative"] is None
					else value["representative"].to_dict(instance.network, config, instance.deadline)
				),
				"num_solutions": len(value.get("solutions", [])),
			}
			for key, value in schemes.items()
		},
	}
	with open(os.path.join(output_dir, "main.json"), "w", encoding="utf-8") as handle:
		json.dump(payload, handle, indent=2, ensure_ascii=False)

	write_scheme_table(full, pareto, instance, config, os.path.join(output_dir, "表3_六类方案对比.csv"))
	write_dissection_table(schemes, instance, config, os.path.join(output_dir, "表3b_代表路径解剖.csv"))
	write_pareto_table(pareto, instance, config, os.path.join(output_dir, "附表_帕累托解集.csv"))
	write_pareto_table(full, instance, config, os.path.join(output_dir, "附表_完全前沿.csv"))

	visualizer = Visualizer(config)
	tri = {
		"cost_min": {"representative": min(pareto, key=lambda s: (s.cost, s.risk))},
		"risk_min": {"representative": min(pareto, key=lambda s: (s.risk, s.cost))},
		"compromise": {"representative": knee_point(pareto)},
	}
	representative = tri["compromise"]["representative"]
	visualizer.plot_network(instance, os.path.join(output_dir, "figS1_real_network.png"), solution=representative)
	visualizer.plot_pareto(
		pareto,
		instance,
		os.path.join(output_dir, "fig5_pareto.png"),
		schemes=tri,
		full_front=full,
	)
	if representative is not None:
		logger.info(f"折中解路径：{path_text(representative, instance)}")

	# 多 OD 汇总：同一路网下 6 个 OD 对的求解结果
	run_multi_od(config, output_dir, logger)
	return payload


def run_multi_od(config: UTRRConfig, output_dir: str, logger) -> dict:
	"""遍历算例中的全部 OD 对，输出多 OD 汇总表（表 3）。

	每个 OD 对承担一项论证任务（见 data/real_case/build_network.py），
	此处只做同一算法口径下的横向比较，用于说明模型在不同品类、不同需求、
	不同通道结构下的适用性。
	"""
	from src.core.instance_builder import build_instance
	from src.core.real_case import list_od_pairs

	if config.data_source != DATA_SOURCE_REAL:
		return {}
	od_list = list_od_pairs(config.real_case_path)
	if len(od_list) <= 1:
		return {}
	logger.info("\n" + "=" * 78)
	logger.info("多 OD 横向比较")
	logger.info("=" * 78)
	header = [
		"OD", "品类", "需求/箱", "时间/h",
		"无时限成本最小/元", "其M",
		"折中解成本/元", "折中解风险", "折中解M", "折中解服务类型", "前沿解数",
	]
	rows = []
	records = []
	path_rows = []
	multi_fronts = []
	for item in od_list:
		cfg = config.with_overrides(real_case_od=item["index"], deadline_hours=config.deadline_hours)
		inst = build_instance(cfg)
		schemes = solve_all_schemes(cfg, inst, include_deterministic=False)
		front = schemes["proposed"]["solutions"]
		cost_min = schemes["cost_min"]["representative"]
		prop = knee_point(front)
		rows.append(
			[
				item["id"],
				cfg.hazmat_name,
				f"{cfg.q:.0f}",
				f"{equivalent_time(prop.t0, prop.mu, prop.sigma, cfg.lambda_alpha()):.2f}" if prop else "",
				f"{cost_min.cost:.2f}" if cost_min else "",
				f"{cost_min.reliability(inst.deadline):.4f}" if cost_min else "",
				f"{prop.cost:.2f}" if prop else "",
				f"{prop.risk:.6f}" if prop else "",
				f"{prop.reliability(inst.deadline):.4f}" if prop else "",
				prop.service_label(cfg) if prop else "",
				len(front),
			]
		)
		records.append(
			{
				"od": item["id"],
				"hazmat": cfg.hazmat_name,
				"demand_boxes": cfg.q,
				"deadline": inst.deadline,
				"pareto_size": len(front),
				"path": route_station_text(prop, inst) if prop else "",
				"transfers": sum(1 for a in prop.arcs if a.is_transfer) if prop else 0,
				"front": [s.to_dict(inst.network, cfg, inst.deadline) for s in front],
				"schemes": {
					key: (
						None
						if value["representative"] is None
						else {
							"cost": value["representative"].cost,
							"risk": value["representative"].risk,
							"reliability": value["representative"].reliability(inst.deadline),
							"service": value["representative"].service_label(cfg),
							"equivalent_time": value["representative"].equivalent_time(),
							"yards": value["representative"].yards_used(inst.network),
						}
					)
					for key, value in schemes.items()
				},
			}
		)
		multi_fronts.append({"label": item["id"], "front": front, "knee": prop})
		path_rows.append(
			[
				item["id"],
				"/".join(prop.yards_used(inst.network)) if prop else "",
				str(sum(1 for a in prop.arcs if a.is_transfer)) if prop else "",
				route_station_text(prop, inst) if prop else "",
			]
		)
		logger.info(
			f"{item['id']}（{cfg.hazmat_name}，{cfg.q:.0f}箱，D={inst.deadline:.2f} h）："
			f"前沿 {len(front)} 条；折中解 ¥{prop.cost:,.0f}、R={prop.reliability(inst.deadline):.4f}"
			if prop is not None
			else f"{item['id']}：无可行解"
		)
	write_table(os.path.join(output_dir, "表4_多OD汇总.csv"), header, rows, title="表 4  多 OD 对求解结果汇总")
	write_table(
		os.path.join(output_dir, "表5_各OD路径与转运.csv"),
		["OD", "启用货场", "转运次数", "完整路径（折中解）"],
		path_rows,
		title="表 5  各OD对的路径与转运方案",
	)
	# 图 6：6 个 OD 对的可行 Pareto 前沿（含 OD1）
	if multi_fronts:
		Visualizer(config).plot_multi_od_fronts(
			multi_fronts, os.path.join(output_dir, "fig6_multi_od_pareto.png")
		)
	with open(os.path.join(output_dir, "multi_od.json"), "w", encoding="utf-8") as handle:
		json.dump(records, handle, indent=2, ensure_ascii=False)
	return {"records": records}


def write_scheme_table(full_front: list, chance_front: list, instance, config, path: str) -> None:
	"""表 3：无时限与机会约束下的成本最小、折中和风险最小方案。"""
	entries = []
	for prefix, front in (("无时限", full_front), ("机会约束", chance_front)):
		entries.extend([
			(f"{prefix}成本最小", min(front, key=lambda s: (s.cost, s.risk))),
			(f"{prefix}折中", knee_point(front)),
			(f"{prefix}风险最小", min(front, key=lambda s: (s.risk, s.cost))),
		])
	header = [
		"方案", "服务类型", "成本/元", "总风险", "时间/h", "M",
		"货场", "转运次数", "径路构成",
	]
	rows = []
	for label, solution in entries:
		rows.append(
			[
				label,
				solution.service_label(config),
				f"{solution.cost:.2f}",
				f"{solution.risk:.6f}",
				f"{equivalent_time(solution.t0, solution.mu, solution.sigma, config.lambda_alpha()):.2f}",
				f"{solution.reliability(instance.deadline):.4f}",
				"/".join(solution.yards_used(instance.network)),
				sum(1 for a in solution.arcs if a.is_transfer),
				route_text(solution, instance, config),
			]
		)
	write_table(path, header, rows, title="表 3  无时限与机会约束下六类方案对比")


def write_dissection_table(schemes: dict, instance, config, path: str) -> None:
	"""表 2b：代表性路径的成本与风险构成。"""
	rows = []
	for key, payload in schemes.items():
		solution = payload.get("representative")
		if solution is None:
			continue
		costs = solution.cost_breakdown(instance.network, config)
		risks = solution.risk_breakdown()
		rows.append(
			[
				SCHEME_LABELS[key][0],
				f"{costs['road_cost']:.2f}",
				f"{costs['rail_cost']:.2f}",
				f"{costs['yard_cost']:.2f}",
				f"{risks['arc_risk']:.6f}",
				f"{risks['node_risk']:.6f}",
				"/".join(solution.yards_used(instance.network)),
				sum(1 for a in solution.arcs if a.is_transfer),
				f"{solution.dist:.1f}",
			]
		)
	write_table(
		path,
		["方案", "公路成本/元", "铁路成本/元", "货场成本/元", "弧段风险", "节点风险",
		 "途经货场", "转运次数", "铁路运距/km"],
		rows,
		title="表 3b  代表性路径的成本与风险构成",
	)


def write_pareto_table(pareto: list, instance, config, path: str) -> None:
	"""附表：风险-成本 Pareto 最优路径集。"""
	header = [
		"序号", "服务类型", "总成本/元", "总风险", "弧段风险", "节点风险",
		"铁路运距/km", "T0/h", "μ/h", "σ/h", "时间/h", "M", "货场", "径路构成",
	]
	rows = []
	for index, solution in enumerate(pareto, start=1):
		risks = solution.risk_breakdown()
		rows.append(
			[
				index,
				solution.service_label(config),
				f"{solution.cost:.2f}",
				f"{solution.risk:.6f}",
				f"{risks['arc_risk']:.6f}",
				f"{risks['node_risk']:.6f}",
				f"{solution.dist:.1f}",
				f"{solution.t0:.2f}",
				f"{solution.mu:.2f}",
				f"{solution.sigma:.2f}",
				f"{solution.equivalent_time():.2f}",
				f"{solution.reliability(instance.deadline):.4f}",
				"/".join(solution.yards_used(instance.network)),
				route_text(solution, instance, config),
			]
		)
	write_table(path, header, rows, title="附表  风险-成本 Pareto 最优路径集")


# ----------------------------------------------------------------------
# 模式：verify —— 精确性交叉验证
# ----------------------------------------------------------------------
def run_verify(config: UTRRConfig, instance, output_dir: str, logger) -> dict:
	"""三组设置交叉验证：双向+剪枝 / 仅前向+剪枝 / 仅前向无剪枝。

	若三者 Pareto 前沿一致，说明双向汇合与剪枝策略不丢失最优解。
	"""
	settings = {
		"bidirectional_pruned": config.with_overrides(bidirectional=True, enable_pruning=True),
		"forward_pruned": config.with_overrides(bidirectional=False, enable_pruning=True),
		"forward_full": config.with_overrides(
			bidirectional=False, enable_pruning=False, enable_dominance=False
		),
	}
	results = {}
	for label, cfg in settings.items():
		logger.info(f"\n>>> 校验设置：{label}")
		solver = ParetoLabelSolver(cfg, instance, logger)
		payload = solver.solve_pareto()
		front = payload["solutions"]
		results[label] = {
			"pareto_size": len(front),
			"min_cost": min((s.cost for s in front), default=None),
			"min_risk": min((s.risk for s in front), default=None),
			"signatures": [s.signature() for s in front],
			"labels_generated": sum(row["labels_generated"] for row in payload["stats"]),
			"wall_time": payload["wall_time"],
		}
		logger.info(
			f"  Pareto 解数 {results[label]['pareto_size']}，"
			f"生成标号 {results[label]['labels_generated']}，耗时 {payload['wall_time']:.3f}s"
		)

	reference = results["forward_full"]["signatures"]
	consistent = True
	for label, payload in results.items():
		if label == "forward_full":
			continue
		missing = set(reference) - set(payload["signatures"])
		if missing:
			consistent = False
			logger.warning(f"  {label} 相对全标号搜索遗漏 {len(missing)} 条前沿路径")
	logger.info("")
	logger.info("精确性校验结论：" + ("一致（双向汇合与剪枝未丢失 Pareto 最优解）" if consistent else "不一致，需检查剪枝条件"))

	payload = {key: {k: v for k, v in value.items() if k != "signatures"} for key, value in results.items()}
	payload["consistent"] = consistent
	payload["baseline_pareto_size"] = len(reference)
	with open(os.path.join(output_dir, "verify.json"), "w", encoding="utf-8") as handle:
		json.dump(payload, handle, indent=2, ensure_ascii=False)
	return payload


# ----------------------------------------------------------------------
# 模式：generate
# ----------------------------------------------------------------------
def run_generate(config: UTRRConfig, instance, output_dir: str, logger) -> dict:
	from config import PROJECT_ROOT
	from src.core.instance_generator import save_instance

	# 同时写入本次结果目录与 data/case/，后者可作后续实验的固定算例快照
	path = save_instance(instance, os.path.join(output_dir, "instance"))
	snapshot = save_instance(instance, os.path.join(PROJECT_ROOT, "data", "case"))
	logger.info(f"算例已导出：{path}")
	logger.info(f"算例快照：{snapshot}")
	payload = instance.summary()
	with open(os.path.join(output_dir, "instance_summary.json"), "w", encoding="utf-8") as handle:
		json.dump(payload, handle, indent=2, ensure_ascii=False)
	return payload


# ----------------------------------------------------------------------
# 模式：all —— 主实验 + 全部敏感性实验（平铺命名：每实验一个 results/<实验名>_<时间戳>）
# ----------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------
def main(argv=None) -> int:
	args = parse_args(argv)
	config = build_config(args)

	if args.mode == "all":
		from sensitivity.runner import EXPERIMENTS, run_named_experiment

		for name in ["main", *EXPERIMENTS]:
			context = start_run(name, config, log_level=args.log_level, root=args.output)
			try:
				if name == "main":
					run_main(context.config, context.instance, context.output_dir, context.logger)
				else:
					run_named_experiment(name, context.config, context.output_dir, context.logger)
			finally:
				finish_run(context)
		return 0

	context = start_run(args.mode, config, log_level=args.log_level, root=args.output)
	try:
		if args.mode == "main":
			run_main(context.config, context.instance, context.output_dir, context.logger)
		elif args.mode == "verify":
			run_verify(context.config, context.instance, context.output_dir, context.logger)
		elif args.mode == "generate":
			run_generate(context.config, context.instance, context.output_dir, context.logger)
	finally:
		finish_run(context)
	return 0


if __name__ == "__main__":
	sys.exit(main())
