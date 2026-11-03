"""敏感性实验脚本的统一命令行入口。

每个 sensitivity_*.py 只需：

	from sensitivity._cli import launch
	from .sensitivity_alpha import run   # 或直接与本文件同名的 run 定义

	if __name__ == "__main__":
		launch("alpha", run)
"""

from __future__ import annotations

import argparse
import sys

from config import DATA_SOURCE_REAL, DATA_SOURCE_SYNTHETIC, UTRRConfig
from src.utils.experiment import finish_run, start_run


def build_parser(name: str, description: str = "") -> argparse.ArgumentParser:
	defaults = UTRRConfig()
	parser = argparse.ArgumentParser(
		description=description or f"UTRR 敏感性实验：{name}",
		formatter_class=argparse.RawDescriptionHelpFormatter,
		epilog=f"""
示例：
  python sensitivity/sensitivity_{name}.py
  python sensitivity/sensitivity_{name}.py --alpha 0.95
  python sensitivity/sensitivity_{name}.py --data-source synthetic
		""",
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
	parser.add_argument("--output", default=None, help="结果根目录（默认 utrr/results）")
	parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
	return parser


def apply_args(config: UTRRConfig, args) -> UTRRConfig:
	config.alpha = args.alpha
	config.confidence_mode = args.confidence_mode
	if args.deadline is not None:
		config.deadline_hours = args.deadline
	config.data_source = args.data_source
	config.real_case_path = args.real_case
	config.real_case_od = args.real_case_od
	return config


def launch(name: str, runner, description: str = "", argv=None, with_instance: bool = True) -> int:
	"""解析参数、建立结果目录并运行实验。"""
	args = build_parser(name, description).parse_args(argv)
	config = apply_args(UTRRConfig(), args)
	context = start_run(
		name, config, log_level=args.log_level, root=args.output, with_instance=with_instance
	)
	try:
		runner(context.config, context.output_dir, context.logger, instance=context.instance)
	except Exception:
		context.logger.error("实验异常终止")
		raise
	finally:
		finish_run(context)
	return 0


def run_as_script(name: str, runner, description: str = "", with_instance: bool = True) -> None:
	"""脚本入口包装（自动处理 sys.exit）。"""
	sys.exit(launch(name, runner, description, with_instance=with_instance))
