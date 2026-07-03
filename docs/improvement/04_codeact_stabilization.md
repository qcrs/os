# P1-2：CodeAct API 生成稳定化

**优先级**：P1
**目标**：让 API 生成的 Python 代码至少一次通过 AST policy，不再依赖 deterministic fallback

---

## 一、当前失败根因分析

从最新 bundle `generation_attempts.json` 的三次失败来看，失败模式通常有以下几种：

### 1.1 LLM 输出格式问题（最常见）

LLM 经常在 code 外面包裹 markdown codeblock：

```
```python
import os
def main():
    ...
```
```

当前 parser 需要从这种格式中提取纯 Python 代码。如果 parser 没有处理这个情况，会把 markdown 符号当成代码的一部分，导致语法错误。

**另一种常见格式问题**：LLM 输出 JSON 包裹代码：

```json
{"code": "import os\ndef main():\n    ..."}
```

如果 prompt 要求 JSON 输出但 parser 期望纯代码，就会失败。

### 1.2 AST policy 违规（prompt 没有说清楚限制）

当前 AST policy 有一个 allowlist（允许的 import 列表），但 prompt 可能没有把这个 allowlist 明确告诉 LLM。LLM 倾向于使用 `os`、`sys`、`subprocess` 等常用库，这些很可能在 policy 的 blocklist 中。

**关键点**：如果 prompt 中不明确列出"你只能 import 以下库"，LLM 几乎必然会违反 AST policy。

### 1.3 repair prompt 不够有针对性

当前 repair loop 可能只是把错误信息附加到 repair prompt，但 LLM 需要看到：
1. 原始代码的哪一行违反了哪条规则
2. 正确的替代写法是什么

如果只给"AST policy failed"这样的错误信息，LLM 无法有效修复。

---

## 二、修复方案

### 方案 A：改进生成 prompt（最高优先级）

当前生成 prompt 的核心问题：**没有明确说明 AST policy allowlist**。

**改进原则**：

1. 在 prompt 开头明确列出"你只能使用以下 Python 标准库"
2. 明确列出"你禁止使用以下操作"
3. 给出一个符合 policy 的代码示例（few-shot）
4. 明确要求输出纯 Python 代码，不要 markdown codeblock

**推荐的 prompt 结构**：

```
You are a Python code generator for a bounded execution environment.

STRICT CONSTRAINTS (AST policy enforcement):
- You MAY ONLY import from this allowlist: json, math, statistics, pathlib, datetime, collections, itertools, functools
- You MUST NOT use: os, sys, subprocess, socket, urllib, requests, or any file system operations outside the workspace
- You MUST NOT execute shell commands
- You MUST NOT import anything not in the allowlist above

OUTPUT FORMAT:
- Return ONLY pure Python code
- Do NOT wrap in markdown codeblocks (no ```python)
- Do NOT include explanations or comments outside the code

TASK:
{task_description}

INPUTS available at /sandbox/workspace/inputs/:
{input_file_list}

OUTPUT: Write result to /sandbox/workspace/outputs/result.json

EXAMPLE (follow this pattern exactly):
import json
from pathlib import Path

def main():
    inputs = json.loads(Path('/sandbox/workspace/inputs/data.json').read_text())
    result = {"answer": inputs["value"] * 2}
    Path('/sandbox/workspace/outputs/result.json').write_text(json.dumps(result))

main()
```

**关键改动**：
- allowlist 明确列在 prompt 中（而不是让 LLM 猜）
- 给出一个符合 policy 的 few-shot 示例
- 明确要求"纯 Python，不要 markdown"

### 方案 B：改进 response parser（中优先级）

在 `v2/runtime/codeact.py` 的 response 解析中，加入多格式支持：

```python
def extract_python_code(response_text: str) -> str | None:
    """
    从 LLM 响应中提取纯 Python 代码，支持多种格式：
    1. 纯代码（直接返回）
    2. ```python ... ``` 包裹（提取代码块内容）
    3. ```\n...\n``` 包裹（无语言标注的 codeblock）
    4. JSON {"code": "..."} 格式（提取 code 字段）
    """
    import re

    text = response_text.strip()

    # 格式4：JSON 包裹
    try:
        import json
        obj = json.loads(text)
        if isinstance(obj, dict) and "code" in obj:
            return str(obj["code"]).strip()
    except (json.JSONDecodeError, ValueError):
        pass

    # 格式2/3：markdown codeblock
    codeblock_pattern = re.compile(r'```(?:python)?\n(.*?)```', re.DOTALL)
    match = codeblock_pattern.search(text)
    if match:
        return match.group(1).strip()

    # 格式1：纯代码（如果包含 import 或 def，认为是代码）
    if "import " in text or "def " in text or text.startswith("#"):
        return text

    return None
```

### 方案 C：改进 repair prompt（中优先级）

repair prompt 需要包含具体的 AST error 信息。

**当前 repair prompt 可能的样子**：
```
The code failed AST policy check. Please fix it.
```

**改进后的 repair prompt**：
```
The previous code FAILED the AST policy check.

FAILED code:
```python
import subprocess  # ← THIS IS FORBIDDEN
result = subprocess.run(['ls'], capture_output=True)
```

SPECIFIC ERROR:
- Line 1: `import subprocess` - subprocess is NOT in the allowed import list
- Allowed imports: json, math, statistics, pathlib, datetime, collections, itertools, functools

Fix the code to accomplish the same task WITHOUT using subprocess.
Alternative: Use pathlib.Path to read files, json to parse data.

Return ONLY the fixed pure Python code (no markdown, no explanations).
```

**关键改动**：
- 明确指出哪一行违反了哪条规则
- 给出允许的替代方案
- 重申输出格式要求

### 方案 D：schema enforcement（可选，中优先级）

让 LLM 输出结构化 JSON，其中包含代码字段：

**prompt 改为要求 JSON 输出**：
```
Return your response as JSON in this exact format:
{
  "reasoning": "brief explanation of your approach",
  "code": "your python code here (as a string, escape newlines as \\n)"
}
```

然后 parser 专门解析这个 JSON 格式，提取 `code` 字段。

优点：格式固定，parser 不需要启发式猜测
缺点：code 中的换行和引号需要正确转义，LLM 可能仍然会出错

---

## 三、AST policy 的改进建议

### 3.1 当前 policy 可能过于严格

如果当前 policy 的 allowlist 只有极少数库，LLM 几乎无法生成有用的代码。
建议将 allowlist 扩展到以下"安全标准库子集"：

```python
SAFE_STDLIB_ALLOWLIST = {
    # 数据处理
    "json", "csv", "re", "math", "statistics", "decimal", "fractions",
    # 数据结构
    "collections", "itertools", "functools", "operator", "copy",
    # 文件（只读 + 限定路径写入）
    "pathlib",  # 注意：需要在沙箱内限制可写路径
    # 时间
    "datetime", "time", "calendar",
    # 字符串
    "string", "textwrap", "unicodedata",
    # 类型
    "typing", "dataclasses", "enum",
    # 随机（用于测试）
    "random",
}

# 显式禁止列表（即使在 stdlib 中也不允许）
BLOCKED_MODULES = {
    "os", "sys", "subprocess", "socket", "urllib", "http",
    "ftplib", "smtplib", "poplib", "imaplib", "telnetlib",
    "multiprocessing", "threading", "ctypes", "cffi",
    "importlib", "__import__", "eval", "exec",
    "pickle", "marshal", "shelve",
}
```

### 3.2 AST policy 的错误信息应该可读

当前 AST policy 失败时，应该输出结构化的错误信息（而不只是 True/False）：

```python
@dataclass
class ASTViolation:
    line_number: int
    column: int
    violation_type: str  # "forbidden_import" | "forbidden_call" | "forbidden_attribute"
    violation_detail: str  # e.g., "import subprocess"
    suggestion: str  # e.g., "Use pathlib.Path instead"

@dataclass
class ASTPolicyResult:
    passed: bool
    violations: list[ASTViolation]

    def to_repair_hint(self) -> str:
        """生成可直接用于 repair prompt 的文本"""
        if self.passed:
            return ""
        lines = ["The following violations were found:"]
        for v in self.violations:
            lines.append(f"  Line {v.line_number}: {v.violation_detail} → {v.suggestion}")
        return "\n".join(lines)
```

---

## 四、验证方法

### 4.1 测试 prompt 改进效果

修改后，在容器中运行 API 模式并记录成功率：

```bash
docker exec statebus-dev-qcrs bash -lc '
  source /usr/local/bin/activate_statebus_container.sh
  cd /workspace/statebus/project
  OUTPUT=/statebus/runs/v2-diagnostics/codeact-api-improved-$(date +%Y%m%d_%H%M%S)

  # 运行5次，统计成功率
  for i in 1 2 3 4 5; do
    python3 scripts/v2_diagnostics/bounded_llm_codeact_demo.py \
      --role-path-mode api \
      --sandbox-backend bwrap \
      --max-repair-attempts 3 \
      --output-root "$OUTPUT/attempt-$i" \
      2>&1 | tail -5
    echo "---"
  done
'
```

### 4.2 验收标准

| 指标 | 当前 | 目标 |
|---|---|---|
| API 生成代码一次通过 AST policy 的比率 | 0/3（0%） | ≥1/3（33%） |
| repair loop 修复成功率 | 未知（3次全失败） | ≥1/3 次 repair 成功 |
| deterministic fallback 使用率 | 100% | ≤50% |
| `generation_fallback_used` | true（总是） | ≤50% 的运行 |

---

## 五、claim 改进路径

| 阶段 | claim |
|---|---|
| 当前（fallback） | "bounded CodeAct 执行链路可工作，使用 deterministic fallback 生成代码" |
| 改进后（API 偶尔成功） | "LLM API 生成的代码在 AST policy 审计后于 bwrap 沙箱中运行，生成成功率 N/5" |
| 目标（API 稳定） | "LLM API 生成的 Python action 通过 AST policy 并在 bwrap 沙箱中稳定运行" |
