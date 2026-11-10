"""不确定变量运算与机会约束等价形式（论文式（9）—（13））。

采用刘宝碇不确定性理论：
- 正态不确定变量 N(e, σ) 的不确定分布为
	Φ(x) = 1 / (1 + exp(π(e − x) / (√3·σ)))，即逻辑斯蒂形式；
- 其 α 分位数为 Φ⁻¹(α) = e + (√3/π)·σ·ln(α/(1−α))；
- 相互独立正态不确定变量之和仍为正态不确定变量，且波动参数线性相加
	（与概率论方差相加不同），故 Σσ_i·y_i 直接累加。

据此，机会约束 M{T̃ ≤ D} ≥ α 与确定性线性约束
	T0 + Σμ_i·y_i + (√3/π)ln(α/(1−α))·Σσ_i·y_i ≤ D
严格等价：路径的时间 T_α ≤ D 当且仅当其不确定测度达到 α。
"""

from __future__ import annotations

import math

from config import UTRRConfig

SQRT3_OVER_PI = math.sqrt(3.0) / math.pi


def normal_uncertain_distribution(x: float, e: float, sigma: float) -> float:
	"""正态不确定变量 N(e, σ) 的不确定分布 Φ(x)（逻辑斯蒂形式）。"""
	if sigma <= 1e-12:
		return 1.0 if x >= e else 0.0
	z = math.pi * (e - x) / (math.sqrt(3.0) * sigma)
	if z > 700.0:
		return 0.0
	if z < -700.0:
		return 1.0
	return 1.0 / (1.0 + math.exp(z))


def reliability_price(alpha: float, mode: str) -> float:
	"""返回可靠度分位系数 λ_α。

	正态不确定变量 N(e, σ) 的 α 分位数为 e + (√3/π)·σ·ln(α/(1−α))，
	故 λ_α = (√3/π)·ln(α/(1−α))，随 α 提高而严格增大。
	mode 参数保留用于兼容旧调用，不再切换口径。
	"""
	if not 0.0 < alpha < 1.0:
		raise ValueError(f"置信水平必须位于 (0, 1)，当前为 {alpha}")
	return SQRT3_OVER_PI * math.log(alpha / (1.0 - alpha))


def equivalent_time(t0: float, mu: float, sigma: float, lam: float) -> float:
	"""机会约束时间 T_α = T0 + μ + λ_α·σ。"""
	return t0 + mu + lam * sigma


def achieved_reliability(t0: float, mu: float, sigma: float, deadline: float, lam: float) -> float:
	"""返回路径实际达到的运到时限可靠度 M{T̃ ≤ D}。

	按正态不确定变量的不确定分布计算；σ = 0 时退化为确定性判断。该口径与等价
	时间严格一致：可靠度 ≥ α 当且仅当 T0 + μ + λ_α·σ ≤ D。
	"""
	return normal_uncertain_distribution(deadline, t0 + mu, sigma)


def lambda_alpha(config: UTRRConfig, alpha: float | None = None) -> float:
	"""按配置口径返回 λ_α。"""
	return reliability_price(float(config.alpha if alpha is None else alpha), config.confidence_mode)
