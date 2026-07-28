# 端到端任务走读导航

这部分不再按模块讲，而是沿任务与受控场景看对象如何流动。单任务走读对应 Studio 的“运营指标 IQR 异常分析”；连续任务走读对应“跨期收入三步任务链”；Logit 挑战走读专门解释执行前数值 Gate 的因果效果。

| 文档 | 关注点 |
|:--|:--|
| [单任务全链路](walkthrough/single-task-iqr.md) | 四 Agent、语义状态、Python/DSL、Artifact 和质量门在一次 Run 中如何衔接 |
| [三轮财务记忆链](walkthrough/continuous-financial-memory.md) | verified 结果怎样进入下一轮，兼容门如何控制复用 |
| [Logit Retry Gate 挑战](walkthrough/logit-retry-challenge.md) | 简单、歧义与不可判定 case 如何验证重试和 fail-closed |

走读中的对象名与事件来自当前实现，但省略具体 UUID、hash 和时间戳。真正 Run 的值应从 task-flow API、Telemetry 和 sidecar 读取；挑战套件结果保持独立分母，不覆盖正式业务基线。
