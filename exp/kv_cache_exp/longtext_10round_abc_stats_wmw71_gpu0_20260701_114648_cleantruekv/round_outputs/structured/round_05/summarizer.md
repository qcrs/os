[Round 5 Deliverable]
@round[5] @feature_scope[multi_order_cargo_selection] @depends_on[1,2,3,4] @new_systems[cargo_slots,order_selection,priority_delivery] @deliverable[incremental_spec]

新增系统：
- cargo_slots：基础容量2格，订单重量占用1或2格（由weight字段决定）
- order_selection：出发前选择核心/普通/奖励订单，受priority、weight、deadline、reward_coins、reward_rep影响
- priority_delivery：同一customer多订单时优先交付即将超时的核心订单

结算差异：
- 未携带订单：不计分
- 携带未交付：按deadline计算扣分
- 迟到订单：额外扣分且奖励减半
- 损坏订单：直接取消奖励

测试点：
1. 超载测试（订单总重量>2）
2. 优先级排序测试（不同deadline的核心订单）
3. 奖励订单携带但未交付
4. 同一customer多订单交付顺序
5. 超时订单扣分计算
6. 损坏订单处理
7. 出发前订单选择界面
8. 货舱容量动态调整（weight=2的订单）

系统整合：
- 在main()中添加订单选择逻辑
- update_turn()处理订单状态更新
- deliver_orders()实现优先级交付算法
- calculate_summary()新增订单结算逻辑
- 保留原有风暴、护盾等系统不变

该实现符合Python标准库要求，使用input()控制，包含指定函数，可通过python3 -m py_compile验证。


```json
{
  "ok": true,
  "round": 5,
  "task_id": 900