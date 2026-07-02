# Docker openEuler 开发说明

适用目标：在**不影响别人容器**的前提下，把当前 `StateBus` 仓库挂载进你自己的 `openEuler 24.03-lts-sp3` 开发容器。

---

## 1. 设计原则

这套开发方式遵守下面几点：

1. 不进入别人正在运行的容器长期开发
2. 不改别人镜像标签
3. 代码保留在宿主机，只把仓库挂载进容器
4. 容器只作为开发环境，不把代码写死在容器文件系统

---

## 2. 文件位置

本仓库已新增：

1. [docker/Dockerfile](/home/qcrs/statebus/project/docker/Dockerfile)
2. [docker/entrypoint.sh](/home/qcrs/statebus/project/docker/entrypoint.sh)
3. [docker/compose.yaml](/home/qcrs/statebus/project/docker/compose.yaml)

---

## 3. 启动前准备

确保宿主机目录存在：

```bash
mkdir -p \
  "$HOME/statebus/models" \
  "$HOME/statebus/caches" \
  "$HOME/statebus/logs" \
  "$HOME/statebus/runs" \
  "$HOME/statebus/work" \
  "$HOME/statebus/work/container-home/.local"
```

当前 `v2` 开发容器默认以 root 运行，便于在单人容器里验证 CodeAct / bubblewrap 和本地 embedding 依赖。

仍然可以导出宿主机 UID/GID，镜像构建时会保留同名普通用户，方便后续需要回退到非 root 口径时使用。不要用 `UID` 这个 shell 只读变量，改用自定义变量：

```bash
export STATEBUS_UID="$(id -u)"
export STATEBUS_GID="$(id -g)"
```

---

## 4. 构建开发镜像

在仓库根目录执行：

```bash
docker compose -f docker/compose.yaml build
```

这会基于本机已有的：

```text
hub.oepkgs.net/openeuler/openeuler:24.03-lts-sp3
```

构建你自己的开发镜像：

```text
statebus-dev-openeuler:24.03-lts-sp3-core
```

如果切到重依赖 target，则镜像名会变成：

```text
statebus-dev-openeuler:24.03-lts-sp3-embed
```

默认构建的是 `core` target，只安装：

- Python 运行时
- Node.js / npm
- `protobuf/pydantic/orjson/msgpack`
- `openai/networkx/pyyaml/rich`
- `pytest`
- `langgraph`

默认**不会**在镜像构建阶段安装 `faiss-cpu`、`transformers`、`sentence-transformers`，因为这一组会继续拉取超大的 `torch` 轮子，在共享服务器和普通网络下会把首次构建拖到数小时。

如果只是先把仓库挂进 openEuler 容器里开发、看代码、跑轻量 smoke，这个默认层已经够用。

当前 `docker/Dockerfile` 已拆成两个明确 target：

- `core`
- `embed`

如果后面确实要在容器里做 embedding / FAISS 相关路径，再显式切到重依赖 target：

```bash
export STATEBUS_DOCKER_TARGET=embed
docker compose -f docker/compose.yaml build
```

如果要直接构建 GPU 版 embedding 容器，不要在容器里执行，回到**宿主机**后显式指定 CUDA torch 轮子：

```bash
export STATEBUS_DOCKER_TARGET=embed
export STATEBUS_TORCH_SPEC="torch==2.5.1+cu121"
export STATEBUS_TORCH_INDEX_URL="https://download.pytorch.org/whl/cu121"
docker compose -f docker/compose.yaml build
```

当前 `compose` 已预留 GPU 透传：

```yaml
runtime: ${STATEBUS_DOCKER_RUNTIME:-nvidia}
```

默认会走 NVIDIA runtime，再通过环境变量把 GPU 暴露进容器；如果你只想给单卡，比如 0 号卡：

```bash
export STATEBUS_NVIDIA_VISIBLE_DEVICES="0"
docker compose -f docker/compose.yaml up -d
```

如果只想先用轻量层，确保：

```bash
export STATEBUS_DOCKER_TARGET=core
docker compose -f docker/compose.yaml build
```

建议：

1. 不要反复使用 `--no-cache`
2. 构建失败后优先修 Dockerfile，再重新 `build`
3. 只有在你明确想丢掉缓存重装时，才用 `--no-cache`

当前默认会走：

```text
https://pypi.tuna.tsinghua.edu.cn/simple
```

如需替换镜像源：

```bash
export STATEBUS_PIP_INDEX_URL="https://pypi.org/simple"
docker compose -f docker/compose.yaml build
```

默认 CPU `torch` 源是：

```text
https://download.pytorch.org/whl/cpu
```

如需替换版本或源：

```bash
export STATEBUS_TORCH_SPEC="torch==2.5.1"
export STATEBUS_TORCH_INDEX_URL="https://download.pytorch.org/whl/cpu"
docker compose -f docker/compose.yaml build
```

---

## 5. 启动开发容器

```bash
docker compose -f docker/compose.yaml up -d
```

默认容器已经以 root 运行。如果你看到旧命令里叠加了 root profile，也可以继续使用；它现在只是显式确认 root 运行口径：

```bash
docker compose -f docker/compose.yaml -f docker/compose.root.yaml up -d --force-recreate
```

如果要验证 CodeAct 的 `bubblewrap` 沙箱后端，必须叠加 bwrap profile。这个 profile 会同时切到 root，并授予 bwrap 需要的 namespace / mount / network 能力：

```bash
docker compose -f docker/compose.yaml -f docker/compose.bwrap.yaml up -d --force-recreate
```

注意：

1. 默认 compose 和 `compose.root.yaml` 都只保证 root 身份，不保证 bwrap 可用。
2. `compose.bwrap.yaml` 是 CodeAct sandbox 专项验证 profile，可用于证明 bwrap backend 在 openEuler 容器高权限配置下跑通。
3. 不要把该结果表述成默认低权限容器也支持 bwrap；默认低权限路径仍应视为 `auto/resource` fallback。

进入容器：

```bash
docker exec -it statebus-dev-qcrs bash
```

进入容器后，建议先激活容器内的 `StateBus` 环境约定：

```bash
source /usr/local/bin/activate_statebus_container.sh
```

如果你刚切过 CPU 镜像到 GPU 镜像，建议在宿主机先完整重建并重启容器：

```bash
docker compose -f docker/compose.yaml down
docker compose -f docker/compose.yaml up -d --build
```

---

## 6. VS Code 开发方式

推荐：

1. 在宿主机打开 VS Code
2. 使用 `Dev Containers` 或 `Attach to Running Container`
3. 附着到 `statebus-dev-qcrs`

因为代码目录是挂载的，所以：

1. 在容器里改代码
2. 在宿主机改代码

都会落回同一个仓库。

---

## 7. 当前挂载内容

代码仓库：

1. `/home/qcrs/statebus/project -> /workspace/statebus/project`

状态目录：

1. `$HOME/statebus/models -> /statebus/models`
2. `$HOME/statebus/caches -> /statebus/caches`
3. `$HOME/statebus/logs -> /statebus/logs`
4. `$HOME/statebus/runs -> /statebus/runs`
5. `$HOME/statebus/work -> /statebus/work`
6. `$HOME/statebus/work/container-home/.local -> /root/.local`
7. `$HOME/statebus/work/container-home/.local -> /home/qcrs/.local`

---

## 8. 为什么这样最稳

这样做的好处：

1. 不碰别人容器
2. 不污染别人挂载目录
3. 容器删了，代码和结果都还在宿主机
4. 后续切换到正式 openEuler benchmark 容器也容易
5. 容器内用 `pip --user` 安装的 embedding 栈也能随宿主机目录一起保留

---

## 9. 不建议做的事

1. 不要 `docker exec` 进 `SynapseX-wang` 或 `SynapseX-wmw` 长期开发
2. 不要在别人的运行中容器里安装依赖
3. 不要把代码只留在容器内部
4. 不要执行 `docker system prune`
5. 不要删除不属于你的镜像或容器

---

## 10. 最小验证

容器启动后，先在容器里执行：

```bash
source /usr/local/bin/activate_statebus_container.sh
cd /workspace/statebus/project
python3 --version
python3 -c "import numpy, pydantic, orjson, msgpack; import google.protobuf"
python3 -c "import langgraph; print('langgraph ok')"
```

如果上面通过，再做更稳妥的分层验证，不要一上来就跑全量 `pytest -q`：

```bash
source /usr/local/bin/activate_statebus_container.sh
python3 -m runtime.smoke
python3 -m pytest -q tests/test_state_channels_and_graph.py::test_langgraph_adapter_runs_existing_statebus_graph_path
```

如果后面需要 embedding 栈，优先直接重建 `embed` target。

如果你更在意安装速度，而不是把大依赖烘进镜像，推荐长期使用这条更高效的开发路径：

1. 宿主机只构建 `core` 容器
2. GPU 运行时通过 `runtime: nvidia` 透传
3. 在容器里执行 `statebus-setup-container-embed-stack.sh`
4. 依赖通过 `pip --user` 安装到挂载出来的 `/root/.local`

这样即使你执行 `docker compose down` 再 `up`，只要保留宿主机的：

```text
$HOME/statebus/work/container-home/.local
```

就不需要重新下载整套 embedding 依赖。

如果你希望在容器里直接启动新的 Codex 会话，推荐也走同样的“安装一次、持久化复用”路径：

```bash
source /usr/local/bin/activate_statebus_container.sh
bash /usr/local/bin/statebus-setup-container-codex-cli.sh
codex --help
```

容器里的 Codex 状态默认会持久化到：

```text
/statebus/work/codex-home
```

这样即使你 `docker compose down` 再 `up`，容器内的 Codex 登录态、配置和会话状态也会跟着宿主机挂载目录一起保留。

如果要确认 GPU torch 和容器 GPU 透传都生效，在容器里执行：

```bash
source /usr/local/bin/activate_statebus_container.sh
python3 -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.device_count())"
```

理想输出应类似：

```text
2.5.1+cu121 True 1
```

如果这里仍然是：

```text
2.5.1+cpu False 0
```

说明你还在旧的 CPU 镜像里，或者宿主机 Docker 没有把 GPU 透传进来。

如果你只是临时在已经启动的 `core` 容器里补装依赖做一次验证，再执行：

```bash
source /usr/local/bin/activate_statebus_container.sh
bash scripts/setup_container_embed_stack.sh
```

这个脚本默认走 `pip --user`，在当前 root 容器下会把包装到 `/root/.local`。如果你明确想写系统 site-packages，可以设置：

```bash
export STATEBUS_CONTAINER_PIP_INSTALL_SCOPE=system
bash scripts/setup_container_embed_stack.sh
```

更稳妥的长期方式仍然是退出容器后，直接重建 `embed` target。

如果你只是要确认仓库挂载和运行时导入没问题，也可先做：

```bash
source /usr/local/bin/activate_statebus_container.sh
python3 -c "import runtime, protocol, statepool, memory"
```

## 10.1 `v2` benchmark 容器内验证

当前容器激活脚本只保证 `python3`，不要在容器里用 `python`。  
同时要把每条命令作为**单独一整行**执行，不要把换行后的半截参数单独粘贴给 shell。

建议按下面顺序执行：

```bash
source /usr/local/bin/activate_statebus_container.sh
cd /workspace/statebus/project
python3 -m pytest -q tests/v2/test_preflight_and_live_runner.py tests/v2/test_fixed_answer_and_external_baseline.py tests/v2/test_minimal_benchmark.py
python3 -m pytest -q tests/v2/test_smoke.py
python3 -m v2.benchmark.live_runner --suite formal --benchmark-tier formal --role-path-mode deterministic --embedding-mode deterministic
python3 -m v2.benchmark.live_runner --suite compare --benchmark-tier dev --role-path-mode deterministic --embedding-mode deterministic --statebus-mode cold-start
```

预期口径：

1. formal 命令应输出 `suite_id=statebus-v2-benchmark-formal` 对应的 JSON，并带 `metadata.benchmark_tier=formal`
2. dev compare 命令当前应输出 `comparison_valid=false`
3. dev compare 当前失效原因应为 `invalid_reason=fairness_gate_failed`，这表示辅助 external lane 仍不具备 formal comparator 资格，而不是命令失败

如果你想一次性跑容器内 helper，也可以执行：

```bash
source /usr/local/bin/activate_statebus_container.sh
cd /workspace/statebus/project
bash scripts/run_v2_live_container_suite.sh
```

这个 helper 当前默认只跑：

1. `preflight`
2. formal financial suite
3. dev fixed-answer `cold-start` statebus
4. dev fixed-answer `cold-start` compare

默认**不会**自动跑 synthetic replay。只有在你显式设置：

```bash
export STATEBUS_V2_ENABLE_SYNTHETIC_REPLAY=1
```

之后，helper 才会追加 replay-ready synthetic probe；这条路径仍只能当开发诊断，不能当 formal replay evidence。

## 11. 明确不要做的安装路径

不要在 Docker 容器里运行：

```bash
bash scripts/setup_host_dev_env.sh
```

这个脚本是给宿主机 conda 环境准备的，会走 host-only 安装逻辑，不是当前 openEuler 开发容器的正确路径。
