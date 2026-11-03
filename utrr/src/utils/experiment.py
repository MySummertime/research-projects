"""实验运行的统一脚手架：结果目录、配置快照、算例快照与日志。

目录约定（每次运行独立生成，互不覆盖）：
	results/<实验名>_<时间戳>/
		config.json          本次运行的模型与绘图参数快照
		utrr.log             完整日志
		instance/            算例快照（instance.json + nodes/arcs/yards.csv）
		表N_*.csv / *.md     论文表格（CSV + Markdown 三线表）
		figN_*.png / .tiff   论文插图
		*.json               机器可读的完整结果
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

from config import RESULTS_ROOT, UTRRConfig
from src.core.instance_builder import build_instance
from src.core.instance_generator import CaseInstance, save_instance
from src.utils.logging import Logger
from src.utils.reporting import format_instance_report


def make_run_dir(name: str, root: str | None = None) -> str:
	"""创建 results/<实验名>_<时间戳> 目录。"""
	root = root or RESULTS_ROOT
	stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
	path = os.path.join(root, f"{name}_{stamp}")
	os.makedirs(path, exist_ok=True)
	return path


@dataclass
class RunContext:
	"""一次实验运行的上下文。"""

	name: str
	config: UTRRConfig
	output_dir: str
	logger: Logger
	instance: CaseInstance


def start_run(
	name: str,
	config: UTRRConfig,
	log_level: str = "INFO",
	root: str | None = None,
	snapshot: bool = True,
	with_instance: bool = True,
) -> RunContext:
	"""创建结果目录、写配置快照、构造算例并打开日志。"""
	output_dir = make_run_dir(name, root)
	config.save_to_json(os.path.join(output_dir, "config.json"))
	logger = Logger(level=log_level, log_file=os.path.join(output_dir, "utrr.log"))
	logger.info("UTRR - 不确定转运时间与运到时限下危险货物公铁联运路径优化")
	logger.info(
		f"实验：{name} | 数据来源：{config.data_source} | "
		f"α={config.alpha:.2f}（{config.confidence_mode}）| "
		f"双向汇合={config.bidirectional} | 剪枝={config.enable_pruning}"
	)
	instance = build_instance(config) if with_instance else None
	if instance is not None and config.data_source == "real":
		logger.info(f"路网数据：{config.real_case_path}")
	if instance is not None:
		for warning in instance.metadata.get("warnings", []):
			logger.warning(warning)
		if snapshot:
			save_instance(instance, os.path.join(output_dir, "instance"))
		logger.info(format_instance_report(instance))
	logger.info(f"结果目录：{output_dir}")
	return RunContext(name=name, config=config, output_dir=output_dir, logger=logger, instance=instance)


def finish_run(context: RunContext) -> None:
	context.logger.info(f"\n完成。结果目录：{context.output_dir}")
	context.logger.close()
