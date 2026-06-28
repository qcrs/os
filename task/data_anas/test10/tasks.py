"""Objective 10-round chained task suite for SynapseX multi-agent experiments.

The canonical data and answer key live next to this file:
  - data.json
  - answer_key.json
  - tasks.json

The TASKS shape intentionally follows the existing run_12rounds.py style:
each item has id/query/task_group/desc. Extra metadata is retained for custom
runners that can inject data.json and score against answer_key.json.
"""

from __future__ import annotations

from pathlib import Path


TASK_DIR = Path(__file__).resolve().parent
DATA_PATH = TASK_DIR / "data.json"
ANSWER_KEY_PATH = TASK_DIR / "answer_key.json"

TASKS = [
    {
        "id": "R01",
        "desc": "需求库存汇总",
        "task_group": "test10_objective",
        "depends_on": [],
        "query": "使用 task/test10/data.json 的固定数据，汇总每个 SKU 的总需求、总库存、库存缺口，并给出按规则确定的店铺优先级顺序。只输出 JSON，字段为 priority_order、sku_totals、total_demand_units、total_inventory_units、total_gap_units。",
    },
    {
        "id": "R02",
        "desc": "优先级库存分配",
        "task_group": "test10_objective",
        "depends_on": ["R01"],
        "query": "基于 R01 的优先级顺序和 data.json 的 fulfillment_rule，对每个 SKU 独立按优先级分配库存，计算每个店铺每个 SKU 的 fulfilled 与 unmet。只输出 JSON，字段为 fulfilled、unmet、store_fill_units、sku_unmet_totals。",
    },
    {
        "id": "R03",
        "desc": "最近仓货源分配",
        "task_group": "test10_objective",
        "depends_on": ["R01", "R02"],
        "query": "基于 R02 的 fulfilled 矩阵，按 data.json 的 source_rule 为每个店铺和 SKU 选择货源仓。输出每条 warehouse->store 的 SKU 数量，并给出两个仓库最终剩余库存。只输出 JSON，字段为 source_allocations、warehouse_remaining_inventory。",
    },
    {
        "id": "R04",
        "desc": "线路载荷与毛利",
        "task_group": "test10_objective",
        "depends_on": ["R03"],
        "query": "基于 R03 的 source_allocations 和产品重量/体积/单位毛利，汇总每条 warehouse->store 线路的 units、weight_kg、volume_m3、gross_margin_cny，并计算全局合计。只输出 JSON，字段为 lane_metrics、totals。",
    },
    {
        "id": "R05",
        "desc": "装车与容量校验",
        "task_group": "test10_objective",
        "depends_on": ["R04"],
        "query": "将 R04 的线路装入 data.json 中的计划车辆：V1 承运 North->S1 与 North->S2，V2 承运 South->S4 与 South->S1，V3 承运 South->S3。检查每辆车的重量和体积是否超过容量，并汇总每辆车承运的线路。只输出 JSON，字段为 vehicle_loads、all_capacity_pass。",
    },
    {
        "id": "R06",
        "desc": "基准路线时刻表",
        "task_group": "test10_objective",
        "depends_on": ["R05"],
        "query": "基于计划路线、50 km/h 车速、08:30 发车、每个服务店铺 15 分钟作业，计算每辆车路线里程、各店到达时间、返回时间，并按每个店铺 deadline 判断基准方案是否准时。S1 有两条货源，按该店最后一批到达时间判断。只输出 JSON，字段为 route_metrics、store_arrival_latest、on_time_by_store、all_on_time。",
    },
    {
        "id": "R07",
        "desc": "道路中断影响评估",
        "task_group": "test10_objective",
        "depends_on": ["R04", "R06"],
        "query": "评估 D1 道路中断且不采取缓解时的影响：V2 改走 South->S3->S4->S1->South，S3 仅路过不服务，仍 08:30 发车。计算 V2 新里程、S4/S1 到达时间、各店延误分钟、罚金，以及包含罚金的无缓解总成本。只输出 JSON，字段为 disrupted_v2、late_minutes_by_store、late_penalty_cny、no_mitigation_total_cost_cny。",
    },
    {
        "id": "R08",
        "desc": "缓解方案选择",
        "task_group": "test10_objective",
        "depends_on": ["R04", "R06", "R07"],
        "query": "比较 data.json 的三个缓解选项 A_overtime_early_dispatch、B_charter_microvan、C_no_mitigation。对每个方案计算总路线成本、额外成本、罚金、总成本、是否满足所有 SLA，并选择总成本最低且满足 SLA 的方案。只输出 JSON，字段为 option_costs、selected_option、selected_total_cost_cny、selected_route_distance_km、selected_all_on_time。",
    },
    {
        "id": "R09",
        "desc": "财务 KPI 汇总",
        "task_group": "test10_objective",
        "depends_on": ["R02", "R04", "R08"],
        "query": "基于已选择的 R08 最优方案，汇总财务和履约 KPI：需求总件数、履约件数、缺货件数、件数履约率、缺失毛利、已履约毛利、物流总成本、净贡献、准时店铺数和准时率。只输出 JSON，字段为 kpi。",
    },
    {
        "id": "R10",
        "desc": "最终审计包",
        "task_group": "test10_objective",
        "depends_on": ["R01", "R02", "R03", "R04", "R05", "R06", "R07", "R08", "R09"],
        "query": "生成最终审计 JSON，必须复用 R01-R09 的结果，不重新假设数据。包含 scenario_id、priority_order、sku_gap_totals、capacity_pass、baseline_all_on_time、selected_option、selected_total_cost_cny、fulfilled_units、gross_margin_cny、net_contribution_cny、selected_route_distance_km。checksum 公式：fulfilled_units*1000 + selected_route_distance_km*10 + gross_margin_cny + round(net_contribution_cny*10)。只输出 JSON。",
    },
]

