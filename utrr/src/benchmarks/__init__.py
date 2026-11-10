# -*- coding: utf-8 -*-
"""外部基准算法：加权和法（WST）与 Gurobi MIP（ε-约束扫描）。

两个基准均针对同一双目标模型（成本、风险，含时间可行性约束
Tα ≤ D 与逐弧服务选择），用于与本文双向多维标号修正算法对比：
- weighted_sum：经典标量化精确基准（只覆盖前沿凸包段）；
- gurobi_mip：0-1 规划精确基准（ε-约束扫描，覆盖整条前沿）。
"""

from src.benchmarks.weighted_sum import solve_weighted_sum  # noqa: F401
