"""
4city B/D comparison with the latest latent-KV statistics schema.

Runs task/lantent/4city.json in structured (B) and latent_kv (D) modes, using
the same latent_kv_model_server endpoint for both modes. The output schema is
kept close to exp/latent_kv_exp/run_abd_10round_0707.py, with additional route
and cost correctness checks for the 4-city benchmark.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path


PROJECT = Path(__file__).resolve().parent.parent.parent
SRC = PROJECT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

TASK_FILE = PROJECT / "task/lantent/4city.json"
RESULT_ROOT = PROJECT / "exp/latent_kv_exp"

SERVER_PORT = os.getenv("LATENT_KV_SERVER_PORT", "8101")
UNIFIED_BASE_URL = f"http://localhost:{SERVER_PORT}/v1"
UNIFIED_API_KEY = os.getenv("CHAT_API_KEY", "token-abc")
UNIFIED_MODEL = os.getenv("CHAT_MODEL", "/data/models/Qwen3-8B")
REQUIRED_FIELDS = ["route", "total_cost", "verification"]


@dataclass
class RoundStats:
    round_id: int
    task_id: str
    title: str
    query: str
    mode: str
    wall_time_s: float = 0.0
    message_count: int = 0
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    text_chars_param: int = 0
    text_chars_result: int = 0
    latent_transfers: int = 0
    latent_steps: int = 0
    kv_bytes_added: int = 0
    kv_bytes_transfer: int = 0
    raw_route: list[str] | None = None
    raw_total_cost: int = 0
    route: list[str] | None = None
    total_cost: int = 0
    answer_source: str = ""
    final_answer: str = ""
    summary: str = ""
    route_correct: bool = False
    cost_correct: bool = False
    ok: bool = False
    error: str = ""


def load_tasks() -> tuple[dict, list[dict]]:
    if not TASK_FILE.exists():
        raise FileNotFoundError(f"Task file not found: {TASK_FILE}")
    data = json.loads(TASK_FILE.read_text(encoding="utf-8"))
    return data["shared_context"], data["tasks"]


def set_unified_env(comm_mode: str, extra: dict[str, str] | None = None) -> None:
    env = {
        "COMM_MODE": comm_mode,
        "CHAT_BASE_URL": UNIFIED_BASE_URL,
        "CHAT_API_KEY": UNIFIED_API_KEY,
        "CHAT_MODEL": UNIFIED_MODEL,
        "CHAT_DISABLE_THINKING": "1",
        "LATENT_KV_BACKEND": os.getenv("LATENT_KV_BACKEND", "real"),
        "LATENT_KV_SERVER_PORT": SERVER_PORT,
        "LATENT_KV_SERVER_HOST": "localhost",
        "LATENT_KV_DOCKER_CONTAINER": os.getenv("LATENT_KV_DOCKER_CONTAINER", "SynapseX-wmw71"),
    }
    if extra:
        env.update(extra)
    os.environ.update(env)


def collect(stats: RoundStats, metrics_obj) -> RoundStats:
    d = metrics_obj.summary_dict()
    stats.message_count = d.get("message_count", 0)
    stats.llm_calls = d.get("llm_calls", 0)
    stats.input_tokens = d.get("input_tokens", 0)
    stats.output_tokens = d.get("output_tokens", 0)
    stats.text_chars_param = d.get("param_chars", 0)
    stats.text_chars_result = d.get("result_chars", 0)
    stats.latent_transfers = d.get("embedding_transfers", 0)
    stats.latent_steps = d.get("latent_steps_total", 0)
    stats.kv_bytes_added = d.get("latent_kv_bytes_added", 0)
    stats.kv_bytes_transfer = d.get("latent_kv_bytes_transferred", 0)
    return stats


def compact_json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def build_prompt(task: dict, shared_context: dict, history: dict[int, dict]) -> str:
    parts: list[str] = []
    parts.append("# 四城市巡检路线任务")
    parts.append(f"## 背景\n{shared_context['description']}")

    cities = shared_context["cities"]
    distance_matrix = shared_context["distance_matrix"]
    parts.append("\n## 距离矩阵")
    parts.append("    " + " ".join(f"{city:>3}" for city in cities))
    for c1 in cities:
        parts.append(f"{c1:>3} " + " ".join(f"{distance_matrix[c1][c2]:>3}" for c2 in cities))

    parts.append("\n## 规则")
    for rule in shared_context["default_rules"]:
        parts.append(f"- {rule}")

    inherits = task.get("inherits", [])
    if "round_01_context" in inherits and history.get(1):
        parts.append("\n## 第1轮结果")
        parts.append(f"路线: {' -> '.join(history[1]['route'])}")
        parts.append(f"成本: {history[1]['cost']}")

    parts.append(f"\n## 第{task['round']}轮任务: {task['title']}")
    parts.append(task["prompt"])
    if task.get("hint"):
        parts.append(f"\n提示: {task['hint']}")

    parts.extend([
        "",
        "请给出最优路线、总成本和简短验证。",
        "",
        "## Final Answer Contract",
        "Return only JSON with exactly these fields:",
        compact_json({
            "route": ["A", "..."],
            "total_cost": "<integer>",
            "verification": "<short string>",
        }),
        "Use an array of city labels for route and an integer for total_cost.",
    ])
    return "\n".join(parts)


def find_json_objects(text: str) -> list[dict]:
    if not text:
        return []
    decoder = json.JSONDecoder()
    objects: list[dict] = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            objects.append(obj)
    return objects


def normalize_route(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if re.fullmatch(r"[A-D]", str(item).strip())]
    if isinstance(value, str):
        return re.findall(r"[A-D]", value)
    return []


def normalize_cost(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    match = re.search(r"\d+", str(value))
    return int(match.group(0)) if match else 0


def parse_answer(result: dict) -> tuple[list[str], int]:
    candidates: list[dict] = []
    extracted = result.get("extracted_answers")
    if isinstance(extracted, dict):
        candidates.append(extracted)

    final_answer = str(result.get("final_answer", ""))
    summary = str(result.get("summary", ""))
    candidates.extend(find_json_objects(final_answer))
    candidates.extend(find_json_objects(summary))

    for candidate in candidates:
        route = normalize_route(candidate.get("route", ""))
        cost = normalize_cost(candidate.get("total_cost", candidate.get("cost", 0)))
        if route and cost:
            return route, cost

    text_parts = [final_answer]
    if not summary.startswith("Summary of research on:"):
        text_parts.append(summary)
    text = "\n".join(part for part in text_parts if part)

    route: list[str] = []
    route_patterns = [
        r"(?:路线|路径|route)\s*[:：=]\s*((?:[A-D]\s*(?:->|→|-|,|，|\s)\s*)+[A-D])",
        r"([A-D]\s*(?:->|→|-)\s*[A-D](?:\s*(?:->|→|-)\s*[A-D]){1,4})",
    ]
    for pattern in route_patterns:
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        if matches:
            route = re.findall(r"[A-D]", matches[-1].group(1))
            break

    cost = 0
    cost_patterns = [
        r"(?:总成本|成本|total_cost|cost)\s*[:：=]\s*(\d+)",
        r"(?:总成本|成本)[^\d]{0,8}(\d+)",
    ]
    for pattern in cost_patterns:
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        if matches:
            cost = int(matches[-1].group(1))
            break

    return route, cost


def check_correctness(route: list[str], cost: int, reference: dict) -> tuple[bool, bool]:
    ref_route = reference.get("route", [])
    ref_cost = reference.get("total_cost", 0)
    route_correct = route == ref_route
    if not route_correct and reference.get("reverse_route_also_valid", False):
        route_correct = route == list(reversed(ref_route))
    return route_correct, cost == ref_cost


def fill_answer_stats(stats: RoundStats, result: dict, reference: dict) -> None:
    raw_route, raw_cost = parse_answer(result)
    stats.raw_route = raw_route
    stats.raw_total_cost = raw_cost

    stats.route_correct, stats.cost_correct = check_correctness(raw_route, raw_cost, reference)
    stats.ok = stats.route_correct and stats.cost_correct

    if raw_route and raw_cost:
        stats.route = raw_route
        stats.total_cost = raw_cost
        stats.answer_source = "model_parse"
        return

    stats.route = list(reference.get("route", []))
    stats.total_cost = normalize_cost(reference.get("total_cost", 0))
    stats.answer_source = "reference_fallback_for_reporting"


def clear_server_handles() -> int:
    """Best-effort cleanup of server-side KV handles after a completed round."""
    base = f"http://localhost:{SERVER_PORT}"
    try:
        with urllib.request.urlopen(f"{base}/handles", timeout=10) as response:
            data = json.load(response)
    except Exception:
        return -1

    count = 0
    for handle in data.get("handles", []):
        handle_id = handle.get("handle_id")
        if not handle_id:
            continue
        request = urllib.request.Request(f"{base}/handle/{handle_id}", method="DELETE")
        try:
            with urllib.request.urlopen(request, timeout=10):
                count += 1
        except Exception:
            pass
    return count


def run_mode_b(task: dict, shared_context: dict, history: dict[int, dict], round_id: int) -> RoundStats:
    stats = RoundStats(
        round_id=round_id,
        task_id=task["task_id"],
        title=task["title"],
        query=task["prompt"],
        mode="B_structured",
    )
    set_unified_env("structured", {"ENABLE_CONTEXT_PACKETS": "1"})
    t0 = time.perf_counter()
    try:
        import importlib
        import config as cfg_mod

        importlib.reload(cfg_mod)
        from graph import build_graph
        from metrics import metrics

        metrics.reset()
        prompt = build_prompt(task, shared_context, history)
        graph, _ = build_graph(mode="structured")
        result = graph.invoke({"query": prompt, "task_group": task["task_id"], "mode": "structured"})

        stats.summary = str(result.get("summary", ""))[:500]
        stats.final_answer = str(result.get("final_answer", "")) or stats.summary
        fill_answer_stats(stats, result, task.get("reference_answer", {}))
        collect(stats, metrics)
    except Exception as exc:
        stats.error = str(exc)[:500]
    stats.wall_time_s = round(time.perf_counter() - t0, 3)
    return stats


def run_mode_d(task: dict, shared_context: dict, history: dict[int, dict], round_id: int) -> RoundStats:
    stats = RoundStats(
        round_id=round_id,
        task_id=task["task_id"],
        title=task["title"],
        query=task["prompt"],
        mode="D_latent_kv",
    )
    set_unified_env(
        "latent_kv",
        {
            "ANALYST_LATENT_STEPS": os.getenv("ANALYST_LATENT_STEPS", "64"),
            "EXECUTOR_LATENT_STEPS": os.getenv("EXECUTOR_LATENT_STEPS", "32"),
            "POST_EXEC_LATENT_STEPS": os.getenv("POST_EXEC_LATENT_STEPS", "16"),
            "SUMMARIZER_LATENT_STEPS": os.getenv("SUMMARIZER_LATENT_STEPS", "0"),
        },
    )
    t0 = time.perf_counter()
    try:
        import importlib
        import config as cfg_mod

        importlib.reload(cfg_mod)
        from graph import build_latent_kv_graph
        from metrics import metrics

        metrics.reset()
        prompt = build_prompt(task, shared_context, history)
        graph, _ = build_latent_kv_graph()
        result = graph.invoke({"query": prompt, "task_group": task["task_id"], "mode": "latent_kv"})

        stats.summary = str(result.get("summary", ""))[:500]
        stats.final_answer = str(result.get("final_answer", "")) or stats.summary
        fill_answer_stats(stats, result, task.get("reference_answer", {}))
        collect(stats, metrics)
    except Exception as exc:
        stats.error = str(exc)[:500]
    stats.wall_time_s = round(time.perf_counter() - t0, 3)
    return stats


def avg(rows: list[dict], key: str) -> float:
    return sum(float(row.get(key, 0) or 0) for row in rows) / len(rows) if rows else 0.0


def pct_delta(new: float, base: float) -> str:
    if not base:
        return "n/a"
    return f"{(new - base) * 100 / base:+.1f}%"


def generate_report(results: list[dict], output_dir: Path, rounds: int) -> Path:
    by_mode: dict[str, list[dict]] = {}
    for row in results:
        by_mode.setdefault(row["mode"], []).append(row)

    b_rows = by_mode.get("B_structured", [])
    d_rows = by_mode.get("D_latent_kv", [])
    all_wall = [float(row.get("wall_time_s", 0) or 0) for row in results]

    lines = [
        "# 4city B/D 最新统计口径实验报告",
        "",
        f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"任务文件: {TASK_FILE.relative_to(PROJECT)}",
        f"运行轮数: {rounds}",
        f"推理引擎: latent_kv_model_server (port {SERVER_PORT}, HuggingFace Transformers, Qwen3-8B, GPU2)",
        (
            "D 配置: "
            f"analyst={os.getenv('ANALYST_LATENT_STEPS', '64')}, "
            f"executor={os.getenv('EXECUTOR_LATENT_STEPS', '32')}, "
            f"post_exec={os.getenv('POST_EXEC_LATENT_STEPS', '16')}, "
            f"summarizer={os.getenv('SUMMARIZER_LATENT_STEPS', '0')}"
        ),
        "",
        "## 汇总统计",
        "",
        "| 模式 | 轮数 | 平均耗时(s) | Agent消息次数 | 文本Token(in) | 文本字符 | LLM调用 | 非文本传递 | Latent步数 | KV传输(KB) | 路线正确率 | 成本正确率 | 完全正确率 |",
        "|------|------|------------|-------------|------------|---------|---------|----------|-----------|-----------|-----------|-----------|-----------|",
    ]

    for mode in ["B_structured", "D_latent_kv"]:
        rows = by_mode.get(mode, [])
        if not rows:
            continue
        n = len(rows)
        route_ok = sum(1 for row in rows if row.get("route_correct"))
        cost_ok = sum(1 for row in rows if row.get("cost_correct"))
        ok = sum(1 for row in rows if row.get("ok"))
        lines.append(
            f"| {mode} | {n} | {avg(rows, 'wall_time_s'):.1f} | "
            f"{avg(rows, 'message_count'):.0f} | {avg(rows, 'input_tokens'):.0f} | "
            f"{(avg(rows, 'text_chars_param') + avg(rows, 'text_chars_result')):.0f} | "
            f"{avg(rows, 'llm_calls'):.0f} | {avg(rows, 'latent_transfers'):.0f} | "
            f"{avg(rows, 'latent_steps'):.0f} | {avg(rows, 'kv_bytes_transfer') / 1024:.0f} | "
            f"{route_ok}/{n} ({route_ok * 100 / n:.0f}%) | "
            f"{cost_ok}/{n} ({cost_ok * 100 / n:.0f}%) | "
            f"{ok}/{n} ({ok * 100 / n:.0f}%) |"
        )

    if b_rows and d_rows:
        lines += [
            "",
            "## B vs D 通信开销对比",
            "",
            "| 指标 | B/structured | D/latent_kv | D 相对 B |",
            "|------|--------------|-------------|----------|",
            (
                f"| 平均文本 token_in | {avg(b_rows, 'input_tokens'):.0f} | "
                f"{avg(d_rows, 'input_tokens'):.0f} | "
                f"{pct_delta(avg(d_rows, 'input_tokens'), avg(b_rows, 'input_tokens'))} |"
            ),
            (
                f"| 平均文本字符 | {(avg(b_rows, 'text_chars_param') + avg(b_rows, 'text_chars_result')):.0f} | "
                f"{(avg(d_rows, 'text_chars_param') + avg(d_rows, 'text_chars_result')):.0f} | "
                f"{pct_delta(avg(d_rows, 'text_chars_param') + avg(d_rows, 'text_chars_result'), avg(b_rows, 'text_chars_param') + avg(b_rows, 'text_chars_result'))} |"
            ),
            f"| Latent steps/轮 | {avg(b_rows, 'latent_steps'):.0f} | {avg(d_rows, 'latent_steps'):.0f} | n/a |",
            f"| KV 传输/轮 | {avg(b_rows, 'kv_bytes_transfer') / 1024:.0f} KB | {avg(d_rows, 'kv_bytes_transfer') / 1024:.0f} KB | n/a |",
        ]

    lines += [
        "",
        "## 耗时分析",
        "",
        "| 模式 | 平均耗时 | 最快 | 最慢 | 标准差 |",
        "|------|--------|------|------|-------|",
    ]
    for mode in ["B_structured", "D_latent_kv"]:
        rows = by_mode.get(mode, [])
        if not rows:
            continue
        times = [float(row.get("wall_time_s", 0) or 0) for row in rows]
        sd = statistics.pstdev(times) if len(times) > 1 else 0.0
        lines.append(f"| {mode} | {sum(times) / len(times):.1f}s | {min(times):.1f}s | {max(times):.1f}s | {sd:.1f}s |")

    lines += [
        "",
        "## 指标说明",
        "",
        "- Agent消息次数: `message_count` (`metrics.message_log` 条目数)",
        "- 文本Token(in): LLM 输入 token 总数",
        "- 文本字符: Agent 间传递的 `param_chars + result_chars`",
        "- 非文本传递: `embedding_transfers` / KV handle 相关消息计数",
        "- Latent步数: `latent_steps_total`",
        "- KV传输(KB): `latent_kv_bytes_transferred / 1024`",
        "- 路线/成本正确率只基于模型输出可解析结果；若模型输出不可解析，`route`/`total_cost` 字段会用 reference fallback 补全，并以 `answer_source` 标记。",
    ]
    if all_wall:
        lines.append(f"- 全部轮次 wall time 总计: {sum(all_wall):.1f}s")

    lines += ["", "## 每轮详情", ""]
    for row in results:
        icon = "OK" if row.get("ok") else "FAIL"
        route = " -> ".join(row.get("route") or []) if row.get("route") else "未提取"
        lines.append(f"### {icon} {row['mode']} 轮{row['round_id']} - {row['title']}")
        lines.append(f"- 任务ID: {row['task_id']}")
        lines.append(f"- 耗时: {row['wall_time_s']}s | Agent消息: {row['message_count']}次 | LLM调用: {row['llm_calls']}次")
        lines.append(
            f"- 文本token: {row['input_tokens']} in / {row['output_tokens']} out"
            f" | 字符: {row['text_chars_param'] + row['text_chars_result']}"
        )
        lines.append(
            f"- 非文本传递: {row['latent_transfers']}次 | latent步: {row['latent_steps']}"
            f" | KV传输: {row['kv_bytes_transfer'] // 1024}KB"
        )
        lines.append(f"- 路线: {route}")
        lines.append(f"- 成本: {row['total_cost']}")
        if row.get("answer_source"):
            raw_route = " -> ".join(row.get("raw_route") or []) if row.get("raw_route") else "未提取"
            lines.append(
                f"- 答案来源: {row['answer_source']} | 原始解析路线: {raw_route} | "
                f"原始解析成本: {row.get('raw_total_cost', 0)}"
            )
        lines.append(f"- 正确性: 路线{'yes' if row.get('route_correct') else 'no'} | 成本{'yes' if row.get('cost_correct') else 'no'}")
        if row.get("error"):
            lines.append(f"- 错误: {row['error'][:180]}")
        summary = (row.get("summary") or row.get("final_answer") or "")[:160].replace("\n", " ")
        if summary:
            lines.append(f"- 结果摘要: {summary}")
        lines.append("")

    report_path = output_dir / "4city_BD_latest_stats_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def write_manifest(output_dir: Path, args: argparse.Namespace) -> None:
    manifest = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "task_file": str(TASK_FILE),
        "output_dir": str(output_dir),
        "modes": args.modes,
        "rounds": args.rounds,
        "server_base_url": UNIFIED_BASE_URL,
        "model": UNIFIED_MODEL,
        "latent_steps": {
            "analyst": os.getenv("ANALYST_LATENT_STEPS", "64"),
            "executor": os.getenv("EXECUTOR_LATENT_STEPS", "32"),
            "post_exec": os.getenv("POST_EXEC_LATENT_STEPS", "16"),
            "summarizer": os.getenv("SUMMARIZER_LATENT_STEPS", "0"),
        },
        "stats_schema": "latest_0707_plus_4city_accuracy",
    }
    (output_dir / "RUN_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run 4city B/D modes with latest statistics")
    parser.add_argument("--modes", nargs="+", default=["B", "D"], help="Modes to run: B D")
    parser.add_argument("--rounds", type=int, default=10, help="Number of rounds to run")
    parser.add_argument("--output-dir", default="", help="Explicit output directory")
    args = parser.parse_args()

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir) if args.output_dir else RESULT_ROOT / f"4city_bd_latest_stats_gpu2_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    shared_context, tasks = load_tasks()
    tasks = tasks[: args.rounds]

    fn_map = {"B": run_mode_b, "D": run_mode_d}
    all_results: list[dict] = []

    print(f"\n{'=' * 72}")
    print(f"  4city B/D latest-stats experiment  modes={args.modes}  rounds={len(tasks)}")
    print(f"  task_file: {TASK_FILE}")
    print(f"  server: {UNIFIED_BASE_URL}")
    print(f"  output: {output_dir}")
    print(f"{'=' * 72}\n")

    write_manifest(output_dir, args)

    for mode in args.modes:
        if mode not in fn_map:
            print(f"skip unknown mode: {mode}")
            continue
        print(f"\n{'-' * 72}")
        print(f"  Mode {mode}, rounds={len(tasks)}")
        print(f"{'-' * 72}")

        history: dict[int, dict] = {}
        for i, task in enumerate(tasks, 1):
            print(f"  [{i:02d}/{len(tasks):02d}] {task['title'][:60]}")
            stats = fn_map[mode](task, shared_context, history, i)
            row = asdict(stats)
            all_results.append(row)

            if stats.answer_source == "model_parse" and stats.route and stats.total_cost:
                history[i] = {"route": stats.route, "cost": stats.total_cost}
            cleaned_handles = clear_server_handles()

            icon = "OK" if stats.ok else "FAIL"
            print(
                f"    {icon} {stats.wall_time_s:.1f}s | msgs={stats.message_count} | "
                f"tok_in={stats.input_tokens} | latent={stats.latent_steps} | "
                f"kv={stats.kv_bytes_transfer // 1024}KB | "
                f"route={'yes' if stats.route_correct else 'no'} cost={'yes' if stats.cost_correct else 'no'}"
            )
            if cleaned_handles > 0:
                print(f"    cleaned_handles={cleaned_handles}")
            if stats.error:
                print(f"    error: {stats.error[:160]}")

            round_path = output_dir / f"round_{mode}_{i:02d}_{task['task_id']}.json"
            round_path.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")

        mode_rows = [row for row in all_results if row["mode"].startswith(f"{mode}_")]
        mode_path = output_dir / f"mode_{mode}_all_rounds.json"
        mode_path.write_text(json.dumps(mode_rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  mode summary: {mode_path}")

    all_path = output_dir / "all_results.json"
    all_path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path = generate_report(all_results, output_dir, len(tasks))

    print(f"\n{'=' * 72}")
    print(f"  completed: {output_dir}")
    print(f"  all_results: {all_path}")
    print(f"  report: {report_path}")
    print(f"{'=' * 72}\n")


if __name__ == "__main__":
    main()
