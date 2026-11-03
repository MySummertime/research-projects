"""报告与表格输出中的统一精度控制。

solution.json 保留全精度数值；本模块只服务于日志与 csv 导出。
"""

from __future__ import annotations

from decimal import Decimal

RISK_DIGITS = 6
RELIABILITY_DIGITS = 4
TIME_DIGITS = 2
COST_DIGITS = 2
PERCENT_DIGITS = 2
DISTANCE_DIGITS = 1


def format_number(value, digits: int, default: str = "") -> str:
	"""按指定小数位输出，缺失值返回默认串。"""
	if value is None or value == "":
		return default
	return f"{float(value):.{digits}f}"


def parameter_digits(values, max_digits: int = 12) -> int:
	"""按参数网格中最精细的取值推断显示精度。"""
	digits = 0
	for value in values:
		exponent = Decimal(str(value)).as_tuple().exponent
		digits = max(digits, max(0, -exponent))
	return min(digits, max_digits)


def format_parameter(value, values=None) -> str:
	"""按参数自身或所在网格的精度输出。"""
	context = list(values) if values is not None else [value]
	return format_number(value, parameter_digits(context))


def format_reliability(value) -> str:
	return format_number(value, RELIABILITY_DIGITS)


def format_csv_value(field: str, value) -> str:
	"""按字段语义选择精度。"""
	if value is None or value == "":
		return ""
	name = field.lower()
	if "reliability" in name or name in {"alpha", "confidence"}:
		return format_number(value, RELIABILITY_DIGITS)
	if "share" in name or "rate" in name or "pct" in name or "gap" in name:
		return format_number(value, PERCENT_DIGITS)
	if "risk" in name:
		return format_number(value, RISK_DIGITS)
	if "cost" in name:
		return format_number(value, COST_DIGITS)
	if "distance" in name:
		return format_number(value, DISTANCE_DIGITS)
	if "time" in name or name in {"t0", "mu", "sigma"}:
		return format_number(value, TIME_DIGITS)
	if isinstance(value, float):
		return format_number(value, 4)
	return str(value)


def format_csv_row(row: dict) -> dict:
	"""对整行做精度转换。"""
	return {field: format_csv_value(field, value) for field, value in row.items()}
