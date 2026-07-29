[JSON]
{
  "analysis": "在第6轮补给站和道具系统基础上，新增天气预报系统。weather_script定义每回合天气类型，提前3回合提示，确保可预测性。动态事件包括顺风（wind_lane推动+1）、乱流（air变blocked）、雷暴增强（storm范围扩大）。实现weather_script数据结构，每回合应用顺序为：先生成临时blocked，再处理天气效果。UI新增天气预报字段，动态blocked tile在若干回合后消失。测试点包括天气提示、事件生成、tile变化、风暴范围扩大、道具使用与天气互动。",
  "round_summary": "新增天气预报系统，实现weather_script数据结构，支持顺风、乱流、雷暴增强等动态事件。天气效果提前3回合提示，动态blocked tile生成和消失规则确保可测试性。UI新增天气预报字段，天气系统与现有风暴、风道逻辑兼容，支持固定seed复现。",
  "carried_state": [
    "PlayerState需扩展添加weather_forecast字段记录未来3回合天气",
    "LevelState需包含weather_script数组定义每回合天气类型",
    "resolve_tile_effect函数需处理动态blocked tile的生成和