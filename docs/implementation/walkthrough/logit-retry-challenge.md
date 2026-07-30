# Logit Retry Gate 受控挑战走读

独立挑战套件构造 12 个候选选择 case，并为每个 case 配对运行 `off` 与 `retry_once`，共
24 次串行运行。任务在 Worker dispatch 判定后结束，集中测量路由与授权控制。

任务分为三组。5 个简单对照从第一次 RoleView 起给出完整合同；5 个受控歧义首次显示两个
表面等价的候选，低 margin 后展开 IQR、连接键、多期序列、极值输出或 Python/DSL 能力信息；
2 个不可判定负例在展开合同后仍没有合法选择。

```mermaid
flowchart LR
    M[最小 RoleView] --> AB[AB/BA 概率校准]
    AB --> G1{margin gate}
    G1 -->|高 margin| D[Worker dispatch = 1]
    G1 -->|低 margin| E[展开受控合同]
    E --> AB2[第二次 AB/BA 校准]
    AB2 --> G2{margin gate}
    G2 -->|通过| D
    G2 -->|仍低| F[fail closed\nWorker dispatch = 0]
```

AB/BA 校准是实验公平性的一部分。同一 RoleView 分别使用正向和反向 alias 绑定请求模型，再按 candidate ID 对齐概率并取均值，避免受约束 JSON 对第一个别名 A 的位置偏好被误当成语义置信度。`off` 与 `retry_once` 共享相同首次 RoleView 和相同首次校准，12/12 配对任务的首次选择保持一致；Gold 与模型可见 manifest 分离。

| 场景 | Gate off | Retry once | 机制效果 |
|:--|--:|--:|:--|
| 简单对照 5 个 | 5/5 | 5/5 | 0 次误重试 |
| 受控歧义 5 个 | 3/5 | 5/5 | 5/5 展开合同，纠正 2 个错误路由 |
| 不可判定负例 2 个 | 0/2 | 2/2 | 错误放行判定由 2 降为 0 |
| 全部 Validator | 8/12 | 12/12 | 机制效果门通过 |

`retry_once` 路径共发生 19 次 Gate 尝试：5 个简单 case 各一次，5 个歧义 case 和 2 个负例各两次。19/19 状态由不同 PID 真实消费，19/19 在使用后释放。由于本套件固定两个候选，每次状态是两个候选概率加 `other_mass`，即 12 B；累计发布并释放 228 B。

Gate off 发生 24 次 vLLM 调用、共 6,110 Token；Retry once 发生 38 次调用、共 9,952 Token。
差异来自每个阶段的 AB/BA 双探测和 7 个低 margin case 的二次选择。该机制用额外调用换取
Validator `8/12 -> 12/12`、歧义任务 `3/5 -> 5/5` 和错误放行 `2 -> 0`。

挑战套件以 12 个任务为分母，系统基线以 95 个检查项为分母。机制交付时容器内测试结果为
582 passed，覆盖合同、控制帧、跨 PID 状态、Runtime 接入和既有回归。

详细任务、实验结果与日志索引见[实验结果总览](../../experiments/README.md#7-logit-retry-gate)。
复现入口为：

```bash
# 在仓库根目录执行
bash scripts/diagnostics/run_logit_retry_challenge_gpu2.sh
```

脚本复用已运行的 vLLM，容器环境和 GPU 映射由部署配置提供。
