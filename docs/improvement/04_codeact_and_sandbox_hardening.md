# CodeAct 完整修复

**状态**：LLM 生成 0/3 成功，全走 deterministic_policy_fallback
**目标**：LLM 生成路径成功率 ≥ 60%，repair loop 至少修复一次失败

---

## 问题一：Generation Prompt 没有告知 LLM 任何约束

### 根因

`bounded_llm_codeact_demo.py` lines 22-25 定义了 AST policy：

```python
ALLOWED_IMPORT_ROOTS = {"json", "pathlib", "statistics", "math"}
FORBIDDEN_CALLS = {"eval", "exec", "compile", "open", "input", "__import__"}
FORBIDDEN_NAME_ROOTS = {"socket", "subprocess", "requests", "urllib", "http", "os", "sys", "shutil"}
```

但生成 prompt 没有把这些信息传给 LLM。LLM 每次写出的代码都会用 `os`/`sys`/`csv`/`re`，因为这是数据处理的直觉选择。

路径 literal 检查（lines 306-309）要求代码里出现字符串 `"task.json"` 和 `"bounded_codeact_result.json"`，但 LLM 不知道输出文件叫这个名字，一般会写 `"output.json"` 或 `"result.json"`。

### 修复

找到 generation prompt 构建位置（`bounded_llm_codeact_demo.py` 中的 generation prompt 字符串），完整替换：

```python
# bounded_llm_codeact_demo.py
_GENERATION_SYSTEM_PROMPT = """\
You are a Python code generator for a sandboxed execution environment.
You will be given a task. Write a Python script that completes the task.

ALLOWED IMPORTS — only these, no others:
  json, pathlib, statistics, math, csv, re, datetime, collections, itertools, decimal

FORBIDDEN — these cause immediate rejection:
  os, sys, subprocess, requests, urllib, http, shutil, socket
  The built-in open() function (use Path(...).read_text() instead)
  eval(), exec(), compile(), input()
  Any dynamic path like Path.cwd(), Path(__file__), __file__

MANDATORY FILE NAMES — use these exact strings:
  Input:  Path("inputs/task.json").read_text()
  Output: Path("bounded_codeact_result.json").write_text(json.dumps(result))

WORKING TEMPLATE:
import json
from pathlib import Path

def main():
    task = json.loads(Path("inputs/task.json").read_text())
    # your logic here
    result = {"answer": task["value"]}
    Path("bounded_codeact_result.json").write_text(json.dumps(result))

main()

OUTPUT: Return ONLY the Python code. No markdown fences. No explanation.
"""
```

---

## 问题二：ALLOWED_IMPORT_ROOTS 太窄（只有4个）

### 根因

`ALLOWED_IMPORT_ROOTS = {"json", "pathlib", "statistics", "math"}` 禁止了 `csv` 和 `re`，但 continuous task 处理 CSV 数据必然用到这两个模块。

LLM 如果不能用 `csv`，会尝试用 `json.loads` 解析 CSV，会失败；或者手写 split 逻辑，极易出 bug。

### 修复

```python
# bounded_llm_codeact_demo.py line 22 — 直接替换
ALLOWED_IMPORT_ROOTS = {
    "json", "pathlib", "statistics", "math",
    "csv", "re", "datetime", "collections", "itertools", "decimal",
}
```

扩展后的 allowlist 覆盖了数据分析的所有合理标准库，同时仍然禁止 os/sys/subprocess/网络相关模块，安全边界不变。

---

## 问题三：Repair Prompt 信息不足

### 根因

violations list 是有的（审查 `_repair_prompt()` lines 208-241），但格式是裸字符串列表，LLM 不知道每个 violation 对应的修复动作是什么。

`missing_input_path:task.json` 这个错误信息对 LLM 来说很模糊——它应该加一行 `Path("inputs/task.json").read_text()` 还是要改某个变量名？

### 修复

替换 `_repair_prompt()` 函数：

```python
def _repair_prompt(source: str, audit: dict) -> str:
    violations = audit.get("violations", [])

    fix_hints = []
    for v in violations:
        if v.startswith("forbidden_import:"):
            mod = v.split(":", 1)[1]
            fix_hints.append(
                f'  - Remove "import {mod}" or "from {mod}". '
                f'Allowed imports: json, pathlib, statistics, math, csv, re, datetime, collections, itertools, decimal'
            )
        elif v == "missing_input_path:task.json":
            fix_hints.append(
                '  - Add: task = json.loads(Path("inputs/task.json").read_text())'
                '  (use EXACTLY the string "inputs/task.json")'
            )
        elif v == "missing_output_path:bounded_codeact_result.json":
            fix_hints.append(
                '  - Add: Path("bounded_codeact_result.json").write_text(json.dumps(result))'
                '  (use EXACTLY the string "bounded_codeact_result.json")'
            )
        elif v.startswith("forbidden_call:open"):
            fix_hints.append(
                '  - Replace open("...") with Path("...").read_text() or Path("...").write_text(...)'
            )
        else:
            fix_hints.append(f"  - Fix violation: {v}")

    hints_text = "\n".join(fix_hints)

    return f"""\
The previous code FAILED the AST policy.

=== FAILED CODE ===
{source}

=== REQUIRED FIXES ===
{hints_text}

=== REMINDER ===
Input:  Path("inputs/task.json").read_text()
Output: Path("bounded_codeact_result.json").write_text(json.dumps(result))
Allowed imports: json, pathlib, statistics, math, csv, re, datetime, collections, itertools, decimal

Return ONLY the corrected Python code, no markdown, no explanation.
"""
```

---

## 问题四：Response Parser 不支持 Markdown Codeblock

### 根因

LLM 默认习惯用 ` ```python ... ``` ` 包裹代码块。如果 parser 是直接把 response 当成代码，markdown fence 会导致语法错误，触发 AST parse failure（甚至在 audit 之前就失败）。

### 修复

在 AST audit 之前加一步 parser 处理：

```python
import re as _re

def _extract_code(response_text: str) -> str:
    text = response_text.strip()
    # 格式1: ```python ... ```
    m = _re.search(r'```python\s*\n(.*?)```', text, _re.DOTALL)
    if m:
        return m.group(1).strip()
    # 格式2: ``` ... ```
    m = _re.search(r'```\s*\n(.*?)```', text, _re.DOTALL)
    if m:
        return m.group(1).strip()
    # 格式3: JSON {"code": "..."}
    try:
        import json as _json
        obj = _json.loads(text)
        if isinstance(obj, dict) and "code" in obj:
            return str(obj["code"]).strip()
    except Exception:
        pass
    # 格式4: 直接是代码
    return text
```

在 `bounded_llm_codeact_demo.py` 的 LLM 响应处理位置（generation loop 内），先调用 `_extract_code(response)` 再传给 `audit_generated_source()`。

---

## 问题五：CodeAct 在主 Pipeline 中与 Deterministic 路径的分裂

### 根因

formal pipeline 中 `codeact_sandbox_bwrap_count=8`，`codeact_sandbox_fallback_count=0`，这些成功全部来自 `codeact_data_tasks.py` 的 deterministic path。

`v2/runtime/codeact.py` 的脚本生成（lines 699-702）：

```python
if task_family in {"continuous_csv_table_analysis", "continuous_long_doc_table_analysis"}:
    output_payload = build_candidate_output_payload(request, workspace_root)
```

即：对已知 task family 直接调用 deterministic 函数，根本没有走 LLM 生成路径。

**结论**：formal pipeline 的 CodeAct 是 deterministic 执行，不是 LLM CodeAct。这在赛题语境下是弱点：赛题鼓励的是 LLM 生成代码在沙箱中运行。

### 修复

给 `CodeActRequest` 加一个 `force_llm_generation: bool = False` 标志，在 demo 和部分 formal task 中启用：

```python
# v2/runtime/codeact.py：修改脚本生成逻辑
if not request.force_llm_generation and task_family in DETERMINISTIC_TASK_FAMILIES:
    # 走 deterministic 路径（保持现有行为）
    output_payload = build_candidate_output_payload(request, workspace_root)
else:
    # 走 LLM 生成路径（新行为）
    generated_source = _generate_source_with_llm(request, workspace_root)
    output_payload = _execute_generated_source(generated_source, workspace_root)
```

在答辩演示时，用 `force_llm_generation=True` 运行，展示真正的 LLM → AST check → bwrap 链路。

---

## 问题六：CodeAct 执行结果没有进入 StateRef 体系

### 根因

`CodeActExecutionRecord` 只保存 output 文件路径，没有注册为 `ExecutionArtifactRef`。Summarizer 直接读文件，绕过了 StateRef 数据面。

### 修复

在 CodeAct 执行成功后，把 output artifact 注册到 StatePool：

```python
# v2/runtime/codeact.py：post-execution，在返回 record 之前
import hashlib, pathlib

def _register_output_as_artifact(
    execution_record: CodeActExecutionRecord,
    state_pool,  # StatePool instance
) -> str:
    output_path = pathlib.Path(execution_record.output_artifact_path)
    artifact_bytes = output_path.read_bytes()
    artifact_hash = hashlib.sha256(artifact_bytes).hexdigest()
    ref_id = f"codeact_artifact_{artifact_hash[:16]}"
    state_pool.put(ref_id, artifact_bytes, content_type="application/json")
    return ref_id
```

Summarizer 通过 `ref_id` 从 StatePool 取数据，而不是直接读文件路径。这样 CodeAct 输出完全进入数据面，可以在 telemetry 中统计。

---

## 验收清单

```bash
# 1. 修复后的 LLM 生成成功率测试（5次，期望 ≥3次成功）
SUCCESS=0
for i in $(seq 1 5); do
  result=$(python scripts/v2_diagnostics/bounded_llm_codeact_demo.py \
    --role-path-mode api --sandbox-backend bwrap --max-repair-attempts 3 \
    --output-root /statebus/runs/codeact-v2/run-$i 2>&1)
  echo "$result" | grep -q "generation_fallback_used.*False" && SUCCESS=$((SUCCESS+1))
  echo "Run $i: $(echo "$result" | grep -E 'ok=|fallback_used' | head -2 | tr '\n' ' ')"
done
echo "LLM generation success: $SUCCESS/5 (target: ≥3)"

# 2. Formal pipeline 回归（不应破坏现有指标）
python -m v2.benchmark.live_runner \
  --suite formal --benchmark-tier formal \
  --role-path-mode api --embedding-mode local \
  2>&1 | grep -E "quality_floor_pass|codeact_sandbox"
# 期望：quality_floor_pass_count=8, codeact_sandbox_bwrap_count=8

# 3. 单次完整演示路径（force LLM generation）
python scripts/v2_diagnostics/bounded_llm_codeact_demo.py \
  --role-path-mode api --sandbox-backend bwrap \
  --force-llm-generation \
  --output-root /statebus/runs/codeact-demo-llm \
  2>&1 | tail -20
# 期望：ok=True, generation_fallback_used=False
```

**预期指标变化**：
- `generation_fallback_used=False` 比例：0% → ≥60%
- formal pipeline：不变（quality_floor_pass=8/8 保持）
- 答辩中可展示真正的 LLM → AST check → bwrap 链路
