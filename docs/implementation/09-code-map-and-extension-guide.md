# 代码地图与扩展导航

这一组文档从对象或机制反查代码、测试和审计出口。模型侧功能横跨合同、Runtime、
vLLM integration、benchmark 与脚本，完整接入同时覆盖这些模块。

| 文档 | 核心问题 |
|:--|:--|
| [核心代码地图](extensions/code-map.md) | 某个对象或事件应从哪个文件开始追 |
| [常见扩展流程](extensions/extension-recipes.md) | 新任务族、capability、DSL op、状态载体、Studio recipe 如何接入 |
| [测试与审阅清单](extensions/testing-and-review.md) | 修改不同模块后运行哪些测试、人工检查哪些不变量 |
| [模型侧状态路径](runtime/model-state-paths.md) | Logit、Prefix 与 KV 的实现入口、开关和证据怎样对应 |

```mermaid
flowchart LR
    C[合同或配置] --> R[Runtime 接线]
    R --> I[集成或存储]
    I --> A[审计与异常路径]
    A --> T[确定性测试]
    T --> E[串行专项实验]
```

新增正式状态类型接入批准、执行、验证、Telemetry 和异常结算链。新增 engine-local 优化
同时记录普通路径、启用条件、真实命中证明、fallback 和资源释放；注册为正式 `StateRef`
时再接入 RefKind、Registry 和 Protobuf。
