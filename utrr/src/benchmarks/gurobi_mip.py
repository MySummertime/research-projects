# -*- coding: utf-8 -*-
"""Gurobi MIP 外部基准：0-1 规划 + ε-约束扫描（精确）。

与本文完全相同的双目标问题写成混合整数规划：

	min  Σ_a c_a·x_a + Σ_k q·η_k·b·z_a
	s.t. 流守恒（起点净出 1、终点净入 1、其余节点流量平衡）
	     Σ_a tα_a·x_a ≤ D        （机会约束 M{T≤D}≥α 的确定性等价）
	     Σ_a r_a·x_a ≤ ε         （ε-约束）
	     Σ_a z_a = 1, z_a ≤ x_a（首条铁路弧承担固定费率 b，式（5））
	     x_a ∈ {0,1}, z_a ∈ {0,1}

其中 tα_a 为弧 a 的等价时间贡献（转运弧为货场 μ+λ_α·σ，其余为旅行时间）；
c_a 为铁路变动费率部分 q·η_k·a·l_ij 与公路/转运弧成本；铁路弧按服务类型各
一条，混编路径自然可行。对 ε 在 [最小风险, 无风险约束最优解的风险] 内扫描
即得整条 Pareto 前沿（含非凸段）。

本模块依赖 gurobipy（需本机许可证）。由用户单独运行：

	python sensitivity/run_gurobi.py

结果写入 results/gurobi_benchmark.json，供算法对比实验（4.7）合并展示。
"""
from __future__ import annotations

import time

from src.core.network import ARC_TRANSFER, LAYER_RAIL  # noqa: F401


def _arc_records(net, config, lam: float) -> list:
    """(弧, 变动成本, 风险, Tα, 是否可作为首条铁路弧)。"""
    out_nodes = {y.out_node for y in net.yards.values()}
    records = []
    for arc in net.arcs:
        if arc.kind == ARC_TRANSFER:
            yard = net.yards[net.nodes[arc.i].yard]
            talpha = yard.mu + lam * yard.sigma
            records.append((arc, arc.cost, arc.risk, talpha, False))
        elif arc.is_rail:
            eta = config.service_type(arc.service).eta
            quantity = config.q * config.hazmat_cost_factor
            variable = eta * net.tariff.a * arc.distance * quantity
            # 所有铁路弧均可能为首条铁路弧（承担固定费率 b），由 z 约束判定
            records.append((arc, variable, arc.risk, arc.travel_time, True))
        else:
            records.append((arc, arc.cost, arc.risk, arc.travel_time, False))
    return records


def solve_gurobi_sweep(instance, config, num_eps: int = 30, verbose: bool = False) -> dict:
    """ε-约束扫描求整条前沿；返回与 WST 相同结构的统计。"""
    import gurobipy as gp
    from gurobipy import GRB

    net = instance.network
    lam = config.lambda_alpha()
    deadline = instance.deadline
    records = _arc_records(net, config, lam)

    started = time.perf_counter()
    model = gp.Model("utrr_mip")
    model.Params.OutputFlag = 1 if verbose else 0
    x, z = {}, {}
    for arc, cost, risk, talpha, first_ok in records:
        x[id(arc)] = model.addVar(vtype=GRB.BINARY, name=f"x_{id(arc)}")
        if first_ok:
            z[id(arc)] = model.addVar(vtype=GRB.BINARY, name=f"z_{id(arc)}")
    model.update()
    for node in net.nodes:
        expr = gp.LinExpr()
        for arc, *_ in records:
            if arc.j == node:
                expr += x[id(arc)]
            if arc.i == node:
                expr -= x[id(arc)]
        rhs = -1.0 if node == net.origin else (1.0 if node == net.destination else 0.0)
        model.addConstr(expr == rhs, name=f"flow_{node}")
    model.addConstr(
        gp.quicksum(talpha * x[id(arc)] for arc, _, _, talpha, _ in records) <= deadline,
        name="deadline",
    )
    model.addConstr(gp.quicksum(z.values()) == 1, name="one_first_rail")
    # 首条铁路弧 = 尾点不经铁路弧即可自起点到达的铁路弧（静态可达性刻画，
    # 与式（5）中 covered=0 的首段口径严格一致，无需顺序变量）
    reach_no_rail = {net.origin}
    frontier = [net.origin]
    while frontier:
        node = frontier.pop()
        for arc in net.out_arcs.get(node, []):
            if not arc.is_rail and arc.j not in reach_no_rail:
                reach_no_rail.add(arc.j)
                frontier.append(arc.j)
    for arc, *_ in records:
        if arc.is_rail:
            model.addConstr(z[id(arc)] <= x[id(arc)], name=f"zle_{id(arc)}")
            if arc.i not in reach_no_rail:
                model.addConstr(z[id(arc)] == 0, name=f"znotfirst_{id(arc)}")
    # 服务连续性：未经货场转运不得中途改乘其它等级列车（与式（5）口径一致）。
    # 用节点-服务选择变量 y(u,k)：铁路弧的两端须同为该弧的服务；站点拆分
    # 接驳弧（铁路节点间的公路弧）保持服务不变；货场转运后可自由重选服务
    rail_nodes_set = {a.i for a, *_ in records if a.is_rail} | {
        a.j for a, *_ in records if a.is_rail
    }
    y = {}
    for node in rail_nodes_set:
        for spec in config.service_types:
            y[(node, spec.code)] = model.addVar(vtype=GRB.BINARY, name=f"y_{node}_{spec.code}")
    model.update()
    for node in rail_nodes_set:
        model.addConstr(
            gp.quicksum(y[(node, spec.code)] for spec in config.service_types) <= 1,
            name=f"ysum_{node}",
        )
    for arc, *_ in records:
        if arc.is_rail:
            model.addConstr(x[id(arc)] <= y[(arc.i, arc.service)], name=f"ya_{id(arc)}_i")
            model.addConstr(x[id(arc)] <= y[(arc.j, arc.service)], name=f"ya_{id(arc)}_j")
    for arc, *_ in records:
        if arc.is_rail or arc.kind == ARC_TRANSFER:
            continue
        if arc.i in rail_nodes_set and arc.j in rail_nodes_set:
            for spec in config.service_types:
                k = spec.code
                model.addConstr(x[id(arc)] <= 1 - (y[(arc.i, k)] - y[(arc.j, k)]),
                                name=f"yswap_{id(arc)}_{k}_a")
                model.addConstr(x[id(arc)] <= 1 - (y[(arc.j, k)] - y[(arc.i, k)]),
                                name=f"yswap_{id(arc)}_{k}_b")
    risk_constr = model.addConstr(
        gp.quicksum(risk * x[id(arc)] for arc, _, risk, _, _ in records) <= gp.GRB.INFINITY,
        name="risk_budget",
    )

    def _cost_expr():
        expr = gp.quicksum(cost * x[id(arc)] for arc, cost, _, _, _ in records)
        quantity = config.q * config.hazmat_cost_factor
        for arc, cost, _, _, first_ok in records:
            if first_ok:
                eta = config.service_type(arc.service).eta
                expr += net.tariff.b1 * quantity * eta * z[id(arc)]
        return expr

    model.setObjective(_cost_expr(), GRB.MINIMIZE)

    def _solve_with_eps(eps: float | None):
        risk_constr.Rhs = gp.GRB.INFINITY if eps is None else eps
        model.optimize()
        if model.Status != GRB.OPTIMAL:
            return None
        chosen = [arc for arc, *_ in records if x[id(arc)].X > 0.5]
        risk = sum(a.risk for a in chosen)
        talpha = sum(t for a, _, _, t, _ in records if x[id(a)].X > 0.5)
        cost = sum(c for a, c, _, _, _ in records if x[id(a)].X > 0.5)
        quantity = config.q * config.hazmat_cost_factor
        cost += sum(
            net.tariff.b1 * quantity * config.service_type(a.service).eta
            for a, _, _, _, first_ok in records if first_ok and z[id(a)].X > 0.5
        )
        return {"cost": cost, "risk": risk, "equivalent_time": talpha}

    num_solves = 0
    points: dict = {}

    def _keep(point):
        if point is None:
            return
        key = (round(point["cost"], 4), round(point["risk"], 6))
        points[key] = point

    point_cost = _solve_with_eps(None)
    num_solves += 1
    _keep(point_cost)
    model.setObjective(
        gp.quicksum(risk * x[id(arc)] for arc, _, risk, _, _ in records), GRB.MINIMIZE
    )
    point_risk = _solve_with_eps(None)
    num_solves += 1
    _keep(point_risk)
    model.setObjective(_cost_expr(), GRB.MINIMIZE)
    if point_cost is not None and point_risk is not None:
        lo, hi = point_risk["risk"], point_cost["risk"]
        if hi > lo:
            step = (hi - lo) / max(1, num_eps - 1)
            for i in range(num_eps):
                _keep(_solve_with_eps(lo + step * i))
                num_solves += 1
    wall_time = time.perf_counter() - started
    ordered = sorted(points.values(), key=lambda p: p["risk"])
    return {
        "algorithm": "gurobi_mip",
        "points": ordered,
        "num_points": len(ordered),
        "num_solves": num_solves,
        "wall_time": wall_time,
    }
