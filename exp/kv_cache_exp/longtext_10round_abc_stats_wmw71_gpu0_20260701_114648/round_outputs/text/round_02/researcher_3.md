[Round 2 Implementation Plan]
{
  "新增字段": {
    "time_left": {
      "默认值": 180,
      "单位": "秒",
      "更新时机": "每回合开始时减少"
    },
    "stamina": {
      "默认值": 10,
      "单位": "点",
      "更新时机": "每移动一步减少"
    },
    "run_summary": {
      "字段": ["delivered_core_count", "elapsed_steps", "remaining_stamina", "success"],
      "计算方式": {
        "delivered_core_count": "已交付的核心订单数",
        "elapsed_steps": "实际移动步数",
        "remaining_stamina": "剩余体力",
        "success": "是否完成至少一个核心订单"
      }
    }
  },
  "更新顺序": [
    "1. 检查时间归零和体力