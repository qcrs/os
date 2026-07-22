# Demo UI

这是一个不依赖后端的静态前端 demo，用来展示当前仓库中的多智能体链路、`text` / `structured` 协议对比，以及 CodeAct 的执行与 repair 轨迹。

## 启动方式

建议在仓库根目录启动静态服务，这样页面可以直接读取 `task/data_anas/result/*.json`：

```bash
cd /home/qcrs/yzmxdzntxzddkxtxztcdygxjyjz
python3 -m http.server 4173
```

然后访问：

```text
http://127.0.0.1:4173/demo_ui/
```

## 说明

- 页面优先读取本地真实结果 JSON。
- 如果读取失败，会自动退回内置快照。
- 当前没有接后端 API，所有回放都是前端模拟，但指标和样例优先锚定到仓库现有结果。
- `KV Cache Slot` 已经作为预留模块放进界面结构里，后续可以直接扩展。
