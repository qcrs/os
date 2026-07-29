[System]
You are a senior Python game engineer in a multi-Agent pipeline.
Follow the assigned role. Keep outputs concise, specific, and machine-readable.
The task source is the 10-round Skyforge Courier longtext benchmark.

[Mode]
text

[Agent Role]
researcher_2

[Long source design document: task/longtext/skyforge_rules.md]
# Skyforge Courier 长规则设计文档

## 1. 游戏概念

《Skyforge Courier》是一款单人 2D 俯视角轻量小游戏。玩家扮演云端工坊的快递员，在漂浮岛屿之间运送能量包。游戏目标不是击败敌人，而是在有限时间内规划路线、管理体力、躲避风暴、完成订单并逐步升级飞行装备。整个设计强调短局、清晰反馈、可扩展系统和低实现成本。

游戏画面采用网格地图。每个关卡由 12x12