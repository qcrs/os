# StateBus Host 环境配置

日期：`2026-06-11`

## 目标

这份文档只说明一件事：如何在一台新的 Linux host 上，把当前 StateBus 仓库需要的本地运行环境配起来。

它不包含真实 API key，也不包含本机已有的模型文件、conda 环境目录、`runs/` 结果产物。

---

## 一、默认目录约定

当前仓库默认使用下面这组目录：

```text
$HOME/statebus/
├── conda-envs/
├── models/
├── caches/
├── logs/
├── runs/
└── work/
```

其中：

- 代码仓库本身：单独 clone 到任意位置，例如 `~/workspace/statebus`
- Python 环境：默认在 `$HOME/statebus/conda-envs/statebus_host`
- 模型目录：默认在 `$HOME/statebus/models`
- benchmark / 日志 / 状态池产物：默认都放在 `$HOME/statebus` 下

如果你不想用这个默认布局，可以覆盖这些环境变量：

- `STATEBUS_HOME`
- `STATEBUS_ENV_PREFIX`
- `STATEBUS_MODELS_DIR`
- `STATEBUS_RUNS_DIR`
- `STATEBUS_WORKDIR`
- `STATEBUS_EMBED_MODEL_PATH`

---

## 二、推荐安装顺序

### 2.1 准备 conda

要求：

- 已安装 Miniconda 或兼容 conda 发行版
- `conda` 已经在 `PATH` 中，或者设置了 `CONDA_EXE`

当前脚本会优先按下面顺序寻找 conda：

1. `CONDA_EXE`
2. `PATH` 里的 `conda`
3. `/opt/miniconda/bin/conda`

### 2.2 创建环境并安装依赖

在仓库根目录执行：

```bash
bash scripts/setup_host_dev_env.sh
```

这个脚本会：

- 创建 `$HOME/statebus/...` 目录结构
- 创建 conda 环境
- 安装 `torch`
- 安装 `requirements-host.txt` 中的 Python 依赖

其中：

- `torch` 使用单独 CUDA 源安装
- 其余依赖走 `requirements-host.txt`

### 2.3 激活环境

```bash
source deploy/activate_statebus_host.sh
```

激活后会自动导出：

- `STATEBUS_HOME`
- `STATEBUS_ENV_PREFIX`
- `STATEBUS_MODELS_DIR`
- `STATEBUS_RUNS_DIR`
- `STATEBUS_WORKDIR`
- `STATEBUS_STATEPOOL_DIR`
- `STATEBUS_LLM_CONFIG_FILE`
- `STATEBUS_EMBED_DEVICE`

---

## 三、模型与 LLM 配置

### 3.1 Embedding 模型

默认 embedding 模型路径是：

```text
$HOME/statebus/models/Qwen3-Embedding-0.6B
```

如果模型不放在这里，可以显式设置：

```bash
export STATEBUS_EMBED_MODEL_PATH="/your/path/Qwen3-Embedding-0.6B"
```

### 3.2 API 配置

推荐先复制模板：

```bash
cp deploy/statebus_llm.yaml.example deploy/statebus_llm.yaml.local
cp deploy/statebus_llm.env.example deploy/statebus_llm.env.local
```

然后只在本地 `.local` 文件里填写：

- `STATEBUS_LLM_API_KEY`

不要把下面两个文件提交到远端：

- `deploy/statebus_llm.env.local`
- `deploy/statebus_llm.yaml.local`

---

## 四、GPU / CPU 说明

默认 `STATEBUS_EMBED_DEVICE=auto`。

当前逻辑是：

- 如果检测到 CUDA 可用，embedding 默认走 `cuda:0`
- 否则回退到 `cpu`

如果你想显式指定：

```bash
export STATEBUS_EMBED_DEVICE=cuda:0
```

或者：

```bash
export STATEBUS_EMBED_DEVICE=cpu
```

---

## 五、验证命令

环境拉起后，建议至少跑下面两条：

```bash
python -m pytest -q
python -m runtime.smoke
```

如果只想先看环境是否激活成功，也可以先执行：

```bash
source deploy/activate_statebus_host.sh
python --version
```

---

## 六、当前建议提交到远端的环境相关文件

建议保留在仓库中：

- `scripts/setup_host_dev_env.sh`
- `deploy/activate_statebus_host.sh`
- `requirements-host.txt`
- `deploy/statebus_llm.env.example`
- `deploy/statebus_llm.yaml.example`
- 本文档

不建议提交：

- `deploy/statebus_llm.env.local`
- `deploy/statebus_llm.yaml.local`
- 本地 conda 环境目录
- 本地模型目录
- `runs/`、`logs/`、`work/` 产物
