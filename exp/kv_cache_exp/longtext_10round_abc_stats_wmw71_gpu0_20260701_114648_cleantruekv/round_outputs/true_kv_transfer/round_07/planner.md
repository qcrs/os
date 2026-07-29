[JSON]
{
  "plan": "在第6轮基础上新增天气预报系统，包含weather_script数据结构和动态事件处理。实现顺风、乱流、雷暴增强三种天气效果，确保天气变化提前提示，避免突然失败。新增UI字段显示天气预报，动态生成和移除临时blocked tile。设计确定性测试用例，支持固定seed复现。新增9个测试点。",
  "sub_queries": [
    "如何设计weather_script的数据结构和每回合应用顺序？",
    "如何实现天气预报UI字段和动态blocked tile生成规则？",
    "如何确保天气变化可预测且不影响游戏失败条件？"
  ],
  "answer_tags": "@round[7] @feature_scope[weather_forecast_dynamic