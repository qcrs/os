# 代码地图与扩展导航

这一组文档供准备改代码的人使用。代码地图按职责列入口；扩展流程说明新增任务、capability、状态或 Studio recipe 时要同步哪些合同；测试地图给出最小回归范围。

| 文档 | 核心问题 |
|:--|:--|
| [核心代码地图](extensions/code-map.md) | 某个对象或事件应从哪个文件开始追 |
| [常见扩展流程](extensions/extension-recipes.md) | 新任务族、capability、DSL op、状态载体、Studio recipe 如何接入 |
| [测试与审阅清单](extensions/testing-and-review.md) | 修改不同边界后至少运行哪些测试、人工检查哪些不变量 |

扩展时优先复用现有合同与 Runtime 边界。增加一个新类并不自动构成能力；它必须进入批准、执行、验证、Telemetry 和失败结算链。

