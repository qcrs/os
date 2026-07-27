from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys


@dataclass(frozen=True)
class Recipe:
    recipe_id: str
    name: str
    mode: str
    description: str
    duration: str
    dataset_ids: tuple[str, ...]
    task_ids: tuple[str, ...]
    accent: str

    def public_payload(self) -> dict[str, object]:
        return {
            "recipe_id": self.recipe_id,
            "name": self.name,
            "mode": self.mode,
            "description": self.description,
            "duration": self.duration,
            "dataset_ids": list(self.dataset_ids),
            "task_ids": list(self.task_ids),
            "accent": self.accent,
        }


RECIPES: tuple[Recipe, ...] = (
    Recipe(
        recipe_id="quick-operating-codeact",
        name="运营指标 IQR 异常分析",
        mode="quick",
        description="用四角色 adaptive CodeAct 链路执行一个正式 IQR 异常检测任务。",
        duration="约 1-3 分钟",
        dataset_ids=("operating-metrics",),
        task_ids=("formal-anomaly-001",),
        accent="codeact",
    ),
    Recipe(
        recipe_id="financial-three-step",
        name="跨期收入三步任务链",
        mode="scenario",
        description="执行三轮相互依赖的财务任务，展示状态、验证产物与记忆复用。",
        duration="约 3-8 分钟",
        dataset_ids=("financial-reports",),
        task_ids=("formal-financial-001", "formal-financial-002", "formal-financial-003"),
        accent="memory",
    ),
    Recipe(
        recipe_id="formal-causal-matrix",
        name="完整效率对照矩阵",
        mode="experiment",
        description="运行两个任务族、五轮任务的 L0-L3 正式同任务对照。",
        duration="长任务",
        dataset_ids=("operating-metrics", "financial-reports"),
        task_ids=(),
        accent="comparison",
    ),
    Recipe(
        recipe_id="semantic-state-holdout",
        name="语义状态留出集",
        mode="experiment",
        description="运行四个留出用例，验证跨进程数值状态的真实消费。",
        duration="约 8-15 分钟",
        dataset_ids=("semantic-holdout",),
        task_ids=("semantic-holdout-s1", "semantic-holdout-s2", "semantic-holdout-s3", "semantic-holdout-s4"),
        accent="state",
    ),
    Recipe(
        recipe_id="memory-truth-suite",
        name="记忆真实性测试",
        mode="experiment",
        description="运行六用例记忆漏斗、负向兼容门与重新计算测试。",
        duration="约 8-15 分钟",
        dataset_ids=("financial-reports",),
        task_ids=(),
        accent="memory",
    ),
    Recipe(
        recipe_id="continuous-long-horizon",
        name="双任务族连续运行",
        mode="experiment",
        description="使用完整 StateBus 链路执行两个相互关联的十轮任务族。",
        duration="长任务",
        dataset_ids=("operating-metrics", "financial-reports"),
        task_ids=(),
        accent="continuity",
    ),
    Recipe(
        recipe_id="capability-coverage",
        name="25 任务能力覆盖",
        mode="experiment",
        description="以受限 Python 或 DSL 路径执行五类全部正式任务。",
        duration="超长任务",
        dataset_ids=("formal-capability",),
        task_ids=(),
        accent="codeact",
    ),
)


RECIPE_BY_ID = {recipe.recipe_id: recipe for recipe in RECIPES}


def _common_live_command(run_dir: Path, run_id: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "v2.benchmark.live_runner",
        "--benchmark-tier",
        "formal",
        "--role-path-mode",
        "local_vllm",
        "--embedding-mode",
        "local",
        "--state-pool-mode",
        "shared_memory",
        "--transport",
        "subprocess",
        "--workspace-root",
        str(run_dir / "workspaces"),
        "--runtime-root",
        str(run_dir / "runtime"),
        "--socket-path",
        str(run_dir / "control.sock"),
        "--suite-id",
        f"studio-{run_id}",
    ]


def build_command(recipe_id: str, run_dir: Path, run_id: str) -> list[str]:
    if recipe_id not in RECIPE_BY_ID:
        raise KeyError(recipe_id)
    common = _common_live_command(run_dir, run_id)
    if recipe_id == "quick-operating-codeact":
        embedding_model = os.getenv(
            "STATEBUS_EMBED_MODEL_PATH",
            str(Path.home() / "statebus" / "models" / "Qwen3-Embedding-0.6B"),
        )
        return [
            sys.executable,
            "-m",
            "v2.benchmark.adaptive_formal_mainline",
            "--output-root",
            str(run_dir / "adaptive"),
            "--embedding-model-path",
            embedding_model,
            "--embedding-device",
            os.getenv("STATEBUS_EMBED_DEVICE", "auto"),
            "--case-id",
            "formal-anomaly-001",
            "--lane",
            "adaptive",
            "--exit-gate",
            "all-correct",
        ]
    if recipe_id == "financial-three-step":
        return [
            *common,
            "--suite",
            "continuous",
            "--family",
            "formal_financial_reports",
            "--max-cases",
            "3",
            "--layer",
            "L3",
            "--executor-mode",
            "deterministic_codeact",
        ]
    if recipe_id == "formal-causal-matrix":
        return [
            *common,
            "--suite",
            "continuous",
            "--round-view",
            "causal_core",
            "--executor-mode",
            "deterministic_codeact",
        ]
    if recipe_id == "semantic-state-holdout":
        return [*common, "--suite", "semantic-holdout"]
    if recipe_id == "memory-truth-suite":
        return [*common, "--suite", "adaptive-memory"]
    if recipe_id == "continuous-long-horizon":
        return [
            *common,
            "--suite",
            "continuous",
            "--round-view",
            "long_horizon",
            "--layer",
            "L3",
            "--executor-mode",
            "deterministic_codeact",
        ]
    if recipe_id == "capability-coverage":
        embedding_model = os.getenv(
            "STATEBUS_EMBED_MODEL_PATH",
            str(Path.home() / "statebus" / "models" / "Qwen3-Embedding-0.6B"),
        )
        return [
            sys.executable,
            "-m",
            "v2.benchmark.adaptive_formal_mainline",
            "--output-root",
            str(run_dir / "adaptive"),
            "--embedding-model-path",
            embedding_model,
            "--embedding-device",
            os.getenv("STATEBUS_EMBED_DEVICE", "auto"),
            "--max-cases",
            "25",
            "--lane",
            "adaptive",
            "--exit-gate",
            "all-correct",
        ]
    raise KeyError(recipe_id)
