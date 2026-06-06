# 当前开发环境与迁移约束说明

更新时间：2026-06-06 17:42:57 CST

适用范围：本仓库从 design-first 转向实现阶段时的环境约束、开发边界与迁移策略说明。

---

## 1. 结论先说

本项目采用两阶段环境策略：

1. **主开发放当前 Linux 宿主机**
   - 使用用户自己的 conda 环境
   - 使用用户自己的目录隔离代码、缓存、模型、日志和中间状态
   - 先完成 `Phase 0` 到 `Phase 4`
   - 主线能力包括：`runtime`、`protocol`、`statepool`、`memory`、`eval`

2. **openEuler VM 只做后验验证**
   - 验证依赖能不能装
   - 验证代码能不能跑
   - 验证 10 轮 benchmark 能不能复现
   - 最后再决定是否补容器/沙箱终态

这不是“退而求其次”，而是当前多人服务器权限条件下最稳的工程路线。

---

## 2. 当前宿主机事实

### 2.1 已确认环境

- 宿主机系统：`Ubuntu 20.04.6 LTS`
- 当前用户：`qcrs`
- Python `multiprocessing.shared_memory`：可正常创建和释放
- `unshare`：存在
- `journalctl`：可执行，但用户视图受限

### 2.2 已确认受限项

- 全局 Docker daemon 已安装并运行，但当前用户**无权访问** `/var/run/docker.sock`
- 当前用户不在可访问 Docker daemon 的权限组内
- `nsjail` 当前未安装
- `podman` / `apptainer` / `udocker` 当前未预装

### 2.3 对项目的直接影响

这意味着：

- 可以在宿主机上直接做用户态开发和测试
- 不能把系统级 Docker 当作当前主开发基础设施
- 不能把 `nsjail` 当成当前现成能力
- 不能默认拥有系统级观测、容器和沙箱权限

---

## 3. 当前宿主机上能做什么

以下能力可以作为当前主线开发目标：

- `Planner` / `Retriever` / `Executor` / `Summarizer` 四角色逻辑
- `text` / `protocol` 双模式
- Protobuf 协议、能力注册、schema 校验
- Unix Domain Socket
- 文件级 `mmap`
- Python `shared_memory`
- SQLite
- FAISS
- 本地 embedding
- 共享记忆命中与复用剪枝
- 10 轮连续任务稳定性测试
- benchmark 指标采集与报表生成

换句话说，**赛题主链路的大部分功能都可以先在当前宿主机完成**。

---

## 4. 当前宿主机上做不了或不适合做什么

### 4.1 当前做不了

- 依赖全局 Docker daemon 的开发流程
- 基于当前环境的容器编排验证
- 以 `nsjail` 为前提的最终 CodeAct 隔离验证
- 需要更高系统权限的 `perf` / `bpftrace` / eBPF 观测

### 4.2 当前不适合做

- 直接读取和分析整机真实系统服务日志作为主 benchmark
- 把多人服务器系统对象当作默认实验对象
- 把 GPU 容器链路作为当前主线
- 把 openEuler 部署成功与否当作当前阶段的阻塞条件

### 4.3 当前测不了或不该承诺能测

- openEuler 最终依赖安装成功率
- openEuler 上的最终部署脚本可靠性
- 容器终态方案
- `nsjail` 最终权限模型
- 完整系统级服务诊断权限

这些项目应放到 **后验验证阶段**，不是当前主开发阶段。

---

## 5. 当前阶段的强约束

### 5.1 环境隔离

必须使用用户自己的目录和环境，不污染共享空间。

建议目录：

```text
$HOME/statebus/
  models/
  caches/
  work/
  logs/
  runs/
```

建议 Python 环境：

- 使用用户自己的 conda 新环境
- 不往系统 Python 装包
- 不使用全局 HF 缓存目录

### 5.2 状态池实现策略

第一版 `StatePool` 不以容器或高权限共享内存为前提。

推荐顺序：

1. `MMAP_FILE`
2. Python `shared_memory`
3. 后续再扩展 `MEMFD/POSIX_SHM`

第一版不要求：

- `memfd + SCM_RIGHTS`
- `nsjail` 只读 FD 注入
- privileged 容器共享状态

### 5.3 数据来源策略

为了保证可复现：

- 优先使用仓库内任务样本
- 优先使用导出的日志样本、文档样本、CSV 样本
- 不默认依赖当前宿主机真实系统状态

### 5.4 模型策略

当前阶段采用：

- `Planner` / `Summarizer`：API LLM
- `Retriever` / `MemoryProxy`：本地 embedding
- `Executor`：脚本/工具优先，CodeAct 兜底

不把“本地部署大语言模型”作为当前主开发前置条件。

---

## 6. 分阶段建议

### 6.1 当前宿主机完成的阶段

应在当前宿主机完成：

- `Phase 0`：环境与仓库初始化
- `Phase 1`：最小多 Agent 文本模式跑通
- `Phase 2`：结构化控制面与能力注册
- `Phase 3`：`StateRef` 数据面
- `Phase 4`：共享记忆与复用

### 6.2 openEuler VM 完成的阶段

应在 openEuler VM 中补做：

- 依赖安装验证
- 代码运行验证
- 10 轮 benchmark 复现验证
- `Phase 5`：CodeAct + 沙箱终态验证
- `Phase 6`：交付环境与实验复核

### 6.3 为什么不把 openEuler VM 当主开发环境

原因很明确：

- GPU 使用会更麻烦
- IPC / `mmap` / 文件系统多一层
- 会把大量时间花在 guest 环境维护上
- 当前主线最缺的是可运行闭环，不是 guest OS 完整性

因此，VM 适合作为**交付前验证环境**，不适合作为**当前主开发环境**。

---

## 7. 对后续实现者的默认要求

后续任何实现、脚本、目录设计、测试计划，都应默认遵守以下规则：

1. 不把系统级 Docker 当作当前必要前提。
2. 不把 `nsjail` 当作当前现成能力。
3. 不以 openEuler VM 作为当前主开发环境。
4. 第一版 `StatePool` 优先走 `mmap` / `shared_memory`。
5. 第一版 benchmark 以仓库内样本任务为主，不依赖宿主机真实系统对象。
6. 任何当前无法验证的终态能力，都必须明确标注为“后验验证项”，不能写成“已覆盖”。

---

## 8. 最终收束

当前阶段的正确工程策略只有一句话：

> 在当前 Linux 宿主机上，用用户态隔离环境先把 StateBus 主链路做通；把 openEuler VM 留给兼容性、复现性和最终交付验证。

这条路线能最大化开发效率，同时最小化多人服务器上的环境污染和权限依赖。
