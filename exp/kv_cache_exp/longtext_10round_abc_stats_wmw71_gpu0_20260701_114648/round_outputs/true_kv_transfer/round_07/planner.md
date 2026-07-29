[JSON]
{
  "plan": "在第6轮补给站和道具系统基础上，新增天气预报系统。weather_script定义每回合天气类型，提前3回合提示。动态事件包括顺风（wind_lane推动+1）、乱流（air变blocked）、雷暴增强（storm范围扩大）。实现weather_script数据结构，每回合应用顺序为：先处理动态blocked生成，再处理天气效果。UI新增天气预报字段，动态blocked tile在若干回合后消失。测试点包括天气提示、事件生成、tile变化、风暴范围扩大、道具使用与天气互动。",
  "sub_queries": [
    "如何设计weather_script的数据结构并确保可预测性？",
    "动态blocked tile的生成和消失规则如何实现？