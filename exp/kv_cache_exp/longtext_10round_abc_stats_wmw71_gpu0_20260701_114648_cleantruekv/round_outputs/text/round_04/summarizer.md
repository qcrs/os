[System]
You are a senior Python game engineer in a multi-Agent pipeline.
Follow the assigned role. Keep outputs concise, specific, and machine-readable.
The task source is the 10-round Skyforge Courier longtext benchmark.

[Mode]
text

[Agent Role]
engineer

[Long source design document: task/longtext/skyforge_rules.md]
# Skyforge Courier 长规则设计文档

## 1. 游戏概念

《Skyforge Courier》是一款单人 2D 俯视角轻量小游戏。玩家扮演云端工坊的快递员，在漂浮岛屿之间运送能量包。游戏目标不是击败敌人，而是在有限时间内规划路线、管理体力、躲避风暴、完成订单并逐步升级飞行装备。整个设计强调短局、清晰反馈、可扩展系统和低实现成本。

游戏画面采用网格地图。每个关卡由 12x12 到 20x20 的 tile 组成。tile 可以是空中航道、浮岛、云墙、风道、雷暴、补给站、客户点、工坊起点、传送门或临时障碍。玩家每次移动一格，也可以通过技能移动多格。所有系统都应该优先支持键盘方向键和 WASD，同时保留触屏方向键的扩展可能。

游戏的一局称为一次配送日。配送日开始时，玩家从工坊起点出发，收到若干订单。每个订单包含目标客户点、包裹类型、截止时间、奖励和风险。玩家必须在倒计时归零前把至少一个核心订单送达，否则配送日失败。如果送达更多订单，则获得更多金币、声望和升级材料。

## 2. 核心循环

基础循环如下：

1. 读取当天地图和订单。
2. 玩家观察订单位置、