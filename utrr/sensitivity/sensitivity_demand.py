# -*- coding: utf-8 -*-
"""4.7 运量敏感性分析：运量分档运价对成本、风险与服务选择的影响。

自变量为运量 q（40 ft 箱），取值覆盖运价分档边界 10、20、40 箱两侧（demand_grid）。
每档重解机会约束 Pareto 前沿，提取成本最小、折中、风险最小三类代表解，记录成本
分解（固定费、铁路运费、公路费、转运费）、风险、M、服务类型与前沿解数。

用法：
    python sensitivity/sensitivity_demand.py
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sensitivity.runner import front_extremes
from src.core.instance_builder import build_instance
from src.solvers.baselines import knee_point
from src.solvers.label_correcting import ParetoLabelSolver
from src.utils.paper_tables import write_table
from src.utils.plotting import Visualizer
from src.utils.reporting import path_text


def _tier_label(config, q: float) -> str:
    lower = 0.0
    for upper, _fixed, _variable in config.rail_volume_tiers:
        if q <= upper:
            return f"{lower:g}-{upper:g}箱"
        lower = upper
    return f">{lower:g}箱"


def _cost_split(solution, inst, config) -> dict:
    """成本分解：固定费、铁路运费（浮动）、公路费、转运费。"""
    costs = solution.cost_breakdown(inst.network, config)
    rail_var = 0.0
    for arc in solution.arcs:
        if arc.is_rail:
            eta = config.service_type(arc.service).eta
            rail_var += eta * inst.network.config.q * config.hazmat_cost_factor * inst.network.tariff.a * arc.distance
    return {
        "fixed": costs["rail_cost"] - rail_var,
        "rail_var": rail_var,
        "road": costs["road_cost"],
        "yard": costs["yard_cost"],
    }


def _rep(solution, inst, config) -> dict:
    return {
        "cost": solution.cost,
        "risk": solution.risk,
        "reliability": solution.reliability(inst.deadline),
        "service": solution.service_label(config),
    }


def run(config, output_dir: str, logger, instance=None) -> dict:
    rows = []
    records = []
    for q in config.demand_grid:
        cfg2 = config.with_overrides(demand_override=q)
        inst = build_instance(cfg2)
        payload = ParetoLabelSolver(cfg2, inst, logger).solve_pareto()
        front = payload["solutions"]
        extremes = front_extremes(front)
        cost_opt = extremes["cost_optimal"]
        risk_opt = extremes["risk_optimal"]
        mid = knee_point(front)
        split = _cost_split(cost_opt, inst, cfg2)
        tier = _tier_label(cfg2, q)
        rail_km = sum(a.distance for a in cost_opt.arcs if a.is_rail)
        logger.info(
            f"q={q:g}箱（{tier}）：成本最小解 {cost_opt.service_label(cfg2)}，"
            f"成本 ¥{cost_opt.cost:,.0f}，风险 {cost_opt.risk:.1f}，M {cost_opt.reliability(inst.deadline):.3f}，"
            f"前沿 {len(front)} 解，费用分解 固定{split['fixed']:,.0f}/铁路{split['rail_var']:,.0f}/"
            f"公路{split['road']:,.0f}/转运{split['yard']:,.0f}"
        )
        rows.append([
            f"{q:g}", tier, f"{cost_opt.cost:.2f}", f"{cost_opt.risk:.6f}",
            f"{cost_opt.reliability(inst.deadline):.4f}", cost_opt.service_label(cfg2),
            str(len(front)),
        ])
        records.append({
            "q": q,
            "tier": tier,
            "cost_min": _rep(cost_opt, inst, cfg2),
            "compromise": _rep(mid, inst, cfg2),
            "risk_min": _rep(risk_opt, inst, cfg2),
            "split": split,
            "rail_km": rail_km,
            "front_size": len(front),
            "path": path_text(cost_opt, inst),
        })

    write_table(
        os.path.join(output_dir, "表10_运量敏感性.csv"),
        ["q/箱", "费率档", "成本最小解成本/元", "风险", "M", "服务类型", "前沿解数"],
        rows,
        title="表 10  运量敏感性",
    )
    visualizer = Visualizer(config)
    visualizer.plot_demand(records, os.path.join(output_dir, "fig11_demand.png"))
    with open(os.path.join(output_dir, "demand.json"), "w", encoding="utf-8") as handle:
        json.dump(records, handle, indent=2, ensure_ascii=False)
    return {"rows": rows, "records": records}


if __name__ == "__main__":
    from sensitivity._cli import run_as_script

    run_as_script("demand", run, "运量敏感性（运量分档运价）")
