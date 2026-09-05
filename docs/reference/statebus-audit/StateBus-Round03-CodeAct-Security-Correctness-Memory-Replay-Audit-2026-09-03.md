# StateBus Round 03 — CodeAct 全链路源码审计与加固设计

> 审计对象：`qcrs/os`  
> 审计分支：`master`  
> 审计基线 commit：`8bfc6464ec236c0e121911095fc283129b0e7696`  
> 审计日期：2026-09-03  
> 范围：`CodeGenerationRequest → Prompt → Python Source → Policy → bwrap Sandbox → Resource Limits → Execution → Repair → Validator → Artifact → Memory Recipe Reuse`  
> 目标：判断当前 CodeAct 是否真的是一个**受 Runtime Authority 约束、可审计、fail-closed、可安全重放的 bounded execution provider**，并给出下一阶段逐文件修改方案。

---

# 0. 先给结论

Round 03 的结论不是“CodeAct 做得很差”。

恰恰相反：

> **StateBus 当前正式 Adaptive LLM CodeAct 路径已经具备比较完整的 authority → static policy → kernel isolation → output validation → quality gate → artifact hash → memory compatibility 链。**

尤其有一个必须先澄清的事实：

```text
Adaptive LLM CodeAct
并不会在 bwrap 不可用时
偷偷 fallback 到 resource-only subprocess。
```

正式路径是：

```text
LlmCodeActRunner
    ↓
require_bwrap = True
    ↓
check_llm_bwrap_readiness()
    ↓
run_llm_bwrap()
    ↓
bwrap 不可用 / readiness probe 失败
    ↓
NOT_EXECUTED
```

因此此前最担心的：

```text
bwrap failure
    ↓
裸 subprocess
    ↓
模型代码直接在 host 执行
```

**在当前 Adaptive LLM CodeAct 主链中没有发现。**

但是源码审计同时发现了几个比“有没有 bwrap”更值得修的问题。

## 0.1 风险优先级

| Priority | 问题 | 判断 |
|---|---|---|
| **P0** | repair 后 Memory recipe 保存的可能仍是 **初始 source，而不是最终 verified source** | **真实 correctness / replay identity bug** |
| **P0/P1** | `VERIFIED artifact` 被 `mark_verified()` 自动提升为 `replay_ready=True` | Artifact verification 与 Recipe replay eligibility 混在一起 |
| **P1** | AST policy 是 denylist，可通过 allowed module 的内部对象图绕过“禁止 os/sys”语义 | bwrap 仍挡住 host，但“bounded Python language surface”并不严格成立 |
| **P1** | `stdout/stderr` 使用 `capture_output=True`，父进程没有 byte cap | child RLIMIT_AS 不限制 parent 捕获缓冲，存在 host memory amplification |
| **P1** | `_set_limit()` 对 `setrlimit` 失败静默忽略 | policy 声称的资源限制与实际 enforced limit 可能不一致 |
| **P1** | LLM CodeAct `nproc_limit=65536` | 对“不可信代码”的 process budget 过宽，应与 launcher 限制解耦 |
| **P1/P2** | 没有 CodeAct 专属 seccomp / cgroup aggregate budget | namespace 很强，但 syscall / aggregate process-resource 仍可进一步 harden |
| **P2** | Prompt 把动态 contract 放在长 static rules 前面 | 不利于单 vLLM 下的 APC prefix reuse |
| **P2** | policy/runtime/quality 三类 repair 各允许 1 次，总计最多可产生 3 次额外 LLM repair | 成本边界需要 global repair budget |
| **P2** | `ExactReplay / ValidatedReplay` 实际是 **recipe replay + current-input recomputation** | 命名与 telemetry 容易被误解为“直接复用结果/跳过执行” |
| **P2** | `LlmCodeActCache` 与 Memory recipe reuse 是两套机制，命名/指标还不够清楚 | 需要显式区分 result cache 与 recipe replay |
| **P2** | Controlled Formal 的 operation semantics/validator contract 很强 | 25/25 证明 contract-aware execution，不证明 open-world CodeAct generalization |

---

# 1. Round 03 到底在审什么

CodeAct 的核心价值不是：

```text
LLM 会写 Python
```

而是：

```text
Planner / Runtime
决定“这个步骤允许用 Python”

        ↓

CapabilityGrant
决定“这个 Python 只能读哪些 Ref、
输出什么 contract、
用多少资源”

        ↓

LLM
只负责提出 candidate source

        ↓

Runtime
审代码
隔离执行
验证结果
决定是否 commit
```

这和原始 CodeAct 论文的思想是一致的，但 StateBus 做了更强的 Runtime Authority 收口。

ICML 2024 的 CodeAct 论文提出：

```text
Text / JSON action
        ↓
Executable Code Action
```

让 Agent 可以组合工具、动态修正执行动作。

官方 `xingyaoww/code-act` 的实现把 code execution 放在独立 Docker/Jupyter execution engine 中。

StateBus 当前做的不是照搬这个架构，而是更偏：

```text
bounded data-transformation provider
```

即：

```text
LLM Python
不是 arbitrary agent shell
而是一个被 capability / Ref / schema / validator 包围的 execution provider。
```

这条定位是对的。

---

# 2. 当前真实主链

当前 Adaptive Python 主链可以还原为：

```text
ApprovedPlan
    │
    ▼
PlanStepProposal
capability_id = execute_bounded_python_v2
    │
    ▼
AdaptiveRuntimeEngine
    │
    ▼
CapabilityGrant
    │
    ├─ task_id
    ├─ step_id
    ├─ attempt_id
    ├─ input_ref_ids
    ├─ output_contract_version
    ├─ approved_plan_hash
    ├─ max_runtime_ms
    └─ expires_at_ns
    │
    ▼
AdaptiveCapabilityDispatcher._dispatch_llm_python()
    │
    ├─ resolve verified artifacts
    ├─ resolve verified evidence pack
    ├─ resolve compatible memory inputs
    ├─ choose business validator
    ├─ build CodeGenerationPolicy
    ├─ build CodeGenerationRequest
    └─ build prompt
    │
    ▼
code_source_factory()
    │
    ▼
raw LLM Python
    │
    ▼
LlmCodeActRunner.execute()
    │
    ├─ validate request ↔ grant
    ├─ consume one-shot grant
    ├─ extract source
    ├─ AST/source audit
    │     └─ optional policy repair ×1
    │
    ├─ bwrap readiness
    ├─ verified-result cache lookup
    ├─ materialize RO inputs / RW output
    │
    ▼
run_llm_bwrap()
    │
    ├─ namespaces
    ├─ no network
    ├─ non-root identity
    ├─ minimal mounts
    └─ RLIMIT
    │
    ▼
Python execution
    │
    ├─ runtime failure
    │     └─ optional runtime repair ×1
    │
    ▼
output validator
    │
    ├─ exactly one output
    ├─ no symlink
    ├─ JSON
    ├─ byte budget
    ├─ shape
    ├─ exact fields
    └─ primitive types
    │
    ▼
Capability Validator
    │
    ├─ provenance
    ├─ completion criteria
    ├─ recomputation / contract validation
    └─ optional quality repair ×1
    │
    ▼
ExecutionArtifactRef
CANDIDATE
    │
    ▼
mark_verified()
    │
    ▼
VERIFIED + replay_ready=True
    │
    ▼
execution_recipes_by_artifact
    │
    ▼
AdaptiveMainline._commit_verified_memory()
    │
    ▼
MemoryRef.metadata.execution_recipe
    │
    ▼
future MemoryQuery
    │
    ▼
_compatibility_decision()
    │
    ▼
ASSIST / VALIDATED_REPLAY / EXACT_REPLAY
    │
    ▼
_dispatch_llm_python()
    │
    └─ recipe["source"] 替代新的 LLM generation
```

这条链整体是成立的。

---

# 3. 先区分两套 CodeAct：这是审计时最容易混淆的地方

当前 repo 同时有：

```text
statebus/runtime/codeact.py
statebus/runtime/llm_codeact.py
```

它们不是同一条安全路径。

---

## 3.1 `codeact.py`

这里是较早的：

```text
CodeActRunner
```

它生成 deterministic script，并调用：

```python
self._sandbox_runner.run(...)
```

而 `CodeActSandboxRunner.run()` 支持：

```text
auto
bwrap
resource
none
```

并且：

```text
requested_backend = auto
bwrap failed
    ↓
resource backend
```

是允许的。

所以：

> **legacy/deterministic CodeAct 路径本身不是严格 fail-closed bwrap-only。**

这不一定是 bug。

如果这里执行的是：

```text
Runtime 自己生成的可信 deterministic script
```

resource fallback 可以是一个产品策略。

但是它绝对不能和：

```text
LLM-authored untrusted Python
```

混在一起。

---

## 3.2 `llm_codeact.py`

正式 Adaptive LLM Python 使用：

```text
LlmCodeActRunner
```

它要求：

```python
if not request.policy.require_bwrap:
    raise CodePolicyError("llm_codeact_requires_bwrap")
```

并且最终执行：

```python
sandbox_runner.run_llm_bwrap(...)
```

不会调用 generic `run()`。

所以当前必须冻结一个明确的架构规则：

```text
Runtime-authored deterministic script
    → legacy/general sandbox policy

LLM-authored source
    → LLM_BOUNDED_PYTHON
    → bwrap-required path only
```

---

## 3.3 建议改名

建议后续直接把命名硬化：

```text
CodeActRunner
    ↓
DeterministicScriptRunner
```

或者：

```text
LegacyDeterministicCodeActRunner
```

保留：

```text
LlmCodeActRunner
```

这样以后不会有人看到：

```text
CodeActSandboxRunner.run() 支持 resource fallback
```

就错误得出：

```text
StateBus LLM CodeAct fail-open
```

。

---

# 4. `CodeGenerationRequest`：当前 contract 的优点和问题

当前 `CodeGenerationRequest` 包含：

```text
task_id
step_id
attempt_id

approved_plan_hash
capability_grant_hash
capability_id

input_ref_ids
input_manifest_digest

output_schema

model_signature
prompt_signature
runtime_signature

policy

task_goal
operation_semantics
completion_criteria
output_contract_version
validator_id
quality_constraints

authorized_input_schema
authorized_input_schemas
expected_output_shape

provenance_item_ids
retrieval_context
memory_inputs
```

---

# 5. 这份 Request 做对了什么

它没有让 LLM 自己决定：

```text
读哪个文件
output 写哪里
允许哪些 import
validator 是什么
resource budget 是多少
input refs 是什么
```

这些全部是：

```text
Controller / Runtime owned
```

。

这正是 StateBus 相较普通“让 Agent 写 Python 然后 subprocess.run”的核心系统差异。

---

## 5.1 Authority chain 是闭合的

`LlmCodeActRunner._validate_request()` 会重新检查：

```text
request.schema_version

policy.enabled
policy.require_bwrap

policy.capability_id
    ==
request.capability_id

registry descriptor.execution_kind
    ==
LLM_BOUNDED_PYTHON

grant.grant_hash
    ==
request.capability_grant_hash

grant.capability_id
    ==
request.capability_id

task / step / attempt scope

session scope

approved_plan_hash

grant expiry

input_ref_ids
    ==
grant.input_ref_ids

registered validator

safe input/output path policy
```

因此不是：

```text
Dispatcher 组完 Request
Runner 盲信它
```

而是：

```text
Dispatcher
    ↓
Request
    ↓
Runner 再做 authority binding validation
```

这一点应当保留。

---

# 6. 但 `CodeGenerationRequest` 现在混了两类东西

当前一个 Request 同时承担：

### A. Security / authority contract

```text
grant
input refs
paths
policy
budget
output schema
validator binding
```

### B. Semantic execution scaffold

```text
task_goal
operation_semantics
quality_constraints
retrieval_context
memory_inputs
```

Controlled Formal 下这是合理的。

但 External Benchmark 下：

```text
operation_semantics
quality_constraints
output schema
```

如果来源是 benchmark adapter 的 closed-set classification，就可能变成此前 Round 02 已经发现的：

```text
ADAPTER_SEMANTIC_DERIVATION
```

。

所以 Round 03 不建议删这些字段，而是给它们加**来源等级**。

---

# 7. 建议的 Contract After

第一阶段不用重构成十几个 dataclass。

建议最小改成：

```python
@dataclass(frozen=True)
class CodeSemanticAuthority:
    task_goal: str

    operation_semantics: dict[str, object]
    quality_constraints: dict[str, object]
    completion_criteria: dict[str, object]

    visibility_manifest_hash: str

    semantic_authority_class: str
    # controlled_contract
    # public_declared
    # public_mechanical
```

然后：

```python
CodeGenerationRequest:
    ...
    semantic_authority: CodeSemanticAuthority
```

External lane hard规则：

```text
ADAPTER_SEMANTIC_DERIVATION
PRIVATE_GOLD
PRIVATE_GRADER
AUDIT_ONLY
```

不能进入：

```text
CodeGenerationRequest.semantic_authority
```

。

这样 CodeAct 本身就不会和某个 benchmark 永久绑定。

---

# 8. Prompt：当前最大的问题不是安全，而是“太混”

当前 `build_code_generation_prompt()` 做了非常多工作：

```text
Allowed imports
Allowed paths
Numeric mode
Output path
Required fields
Output schema
Task goal
Operation semantics
Completion criteria
Validator ID
Quality constraints
Input schema
Retrieval context
Memory inputs

然后再跟一大段固定安全/数据处理规则。
```

安全上没大问题。

但是对你们：

```text
single vLLM
multi logical agents
APC
```

架构来说，它并不是最优排列。

---

# 9. 当前 Prompt Layout 会损失 APC prefix reuse

现在大致：

```text
[少量 static instructions]

[动态 capability / path / schema]
[动态 task goal]
[动态 operation semantics]
[动态 completion criteria]
[动态 retrieval context]
[动态 memory]

[很长一段 static policy instructions]
```

这意味着：

```text
不同 CodeAct request
```

很早就开始 token divergence。

因此后面很长的：

```text
static policy rules
```

无法形成长 exact-prefix hit。

---

# 10. 推荐 Prompt Layout

改成：

```text
┌─────────────────────────────────┐
│ Stable CodeAct Policy Prefix    │
│                                 │
│ - execution model               │
│ - no network                    │
│ - no subprocess                 │
│ - fixed Path rules              │
│ - JSON rules                    │
│ - missing-value rules           │
│ - output discipline             │
│ - repair discipline             │
└─────────────────────────────────┘
                 ↓
        APC reusable prefix
                 ↓
┌─────────────────────────────────┐
│ Capability Contract             │
│                                 │
│ allowed imports                 │
│ allowed paths                   │
│ output contract                 │
│ schema                          │
└─────────────────────────────────┘
                 ↓
┌─────────────────────────────────┐
│ Dynamic Task Suffix             │
│                                 │
│ task_goal                       │
│ public operation semantics      │
│ input schema                    │
│ retrieval context               │
│ memory assist                   │
└─────────────────────────────────┘
```

也就是：

> **Static Rules First，Dynamic Contract Last。**

这不是“prompt engineering 小优化”。

它可以直接和你们已经做的：

```text
shared prefix / APC
```

形成系统级闭环。

---

# 11. Validator ID 没必要暴露给模型

当前 prompt 包含：

```text
Validator ID: xxx
```

模型真正需要的是：

```text
output semantics
quality requirements
```

而不是：

```text
内部 validator 的注册 ID
```

建议：

```text
validator_id
```

保留在 Runtime `CodeGenerationRequest` 内部，

但不 render 到 LLM prompt。

理由有三个：

1. 减少 implementation coupling；
2. External Benchmark 下避免向模型暴露内部 grader topology；
3. 模型无法从 validator ID 获得合法的新 authority。

---

# 12. Retrieval Context 的定位也要进一步明确

当前 CodeAct 可以收到：

```text
最多约 8 个 evidence item
每个 rendered_text 截断约 800 chars
```

它们用于：

```text
terminology
locator
method selection
```

Prompt 已经明确：

```text
numeric output 必须来自 verified JSON artifact
retrieved text 不扩大 value authority
```

这是好设计。

但是 external data-agent 场景需要再加：

```text
retrieval context = untrusted semantic data
```

不能把 evidence 中的文字当系统指令。

建议将 Prompt 结构显式化：

```text
<sb-authorized-task-contract>
...
</sb-authorized-task-contract>

<sb-untrusted-retrieved-context>
...
</sb-untrusted-retrieved-context>
```

重点不是靠 XML tag 获得安全性。

真正安全仍由：

```text
Grant + File Ref + bwrap + Validator
```

保证。

tag 只是降低 prompt injection 对 algorithm choice 的影响。

---

# 13. Python Source Policy：当前已经不算简单字符串过滤

当前 `audit_generated_source()` 做了：

```text
ast.parse()
symtable undefined-name analysis

source byte budget
AST node budget
loop budget

import root allowlist

forbidden calls
forbidden names
forbidden attributes
forbidden AST node types

Path alias tracking
Path variable propagation

nonliteral path rejection
absolute / parent path rejection

required input path literal check
required output write check

special numeric parser check
```

这其实已经比很多 demo 级 CodeAct 强很多。

---

# 14. 当前 forbidden surface

### Calls

```text
eval
exec
compile
open
input
__import__

getattr
setattr
delattr

globals
locals
vars

help
dir
```

### Names

```text
os
sys
subprocess
socket
requests
urllib
http
shutil
builtins
ctypes
pickle
marshal

__file__
__loader__
__spec__
```

### Attributes

包括：

```text
cwd
home
resolve
absolute
glob
rglob
iterdir
walk
environ

system
popen
fork
spawn
run
call
Popen

unlink
rename
symlink_to
hardlink_to
chmod
chown
touch
mkdir
rmdir
```

。

---

# 15. 但是这里有一个必须承认的设计事实

> **Python AST denylist 不能被当成真正的 security boundary。**

原因不是“你们漏了一个危险函数”这么简单。

Python 模块本身是对象图。

即使禁止：

```python
import os
import sys
```

allowed module 也可能持有其它 module reference。

---

# 16. 一个结构性绕过例子：`collections._sys`

当前 policy 默认允许：

```text
collections
```

Python 的 `collections` module 内部持有：

```python
collections._sys
```

。

当前 AST 只禁止：

```text
attribute.startswith("__")
```

也就是双下划线。

但：

```text
_sys
```

是单下划线，不会被拒绝。

于是从当前规则出发，结构上存在这种访问链：

```python
import collections

system_modules = collections._sys.modules
os_module = system_modules["os"]
```

这里没有出现：

```python
import os
```

也没有：

```python
Name("os")
```

。

进一步，当前 forbidden attributes/calls 中并没有覆盖所有：

```text
exec*
spawn*
```

变体。

例如：

```text
execvp
spawnv
spawnve
```

不是当前 exact denylist 的完整覆盖范围。

---

# 17. 这意味着什么

必须分成两个结论。

## 17.1 不意味着 host 已经能逃逸

因为后面还有：

```text
bwrap
mount namespace
PID namespace
network namespace
non-root
read-only inputs
minimal writable output
```

。

所以这个问题不是：

```text
P0 host RCE
```

。

---

## 17.2 但意味着你们不能声称

```text
AST policy 保证模型只能运行纯 json/statistics/pathlib data transform
```

。

更准确的是：

> AST Policy 是第一层 semantic/safety lint；真正的 security boundary 必须是 OS sandbox。

这是架构表述上非常重要的一点。

---

# 18. AST Policy 应该怎么改

不推荐继续无限补 denylist：

```text
execvp
execvpe
spawnv
spawnve
...
```

因为永远补不完。

推荐改为两层。

---

## 18.1 Layer A：module/private-object hardening

至少加入：

```text
任何 module attribute 以 "_" 开头
    → reject
```

尤其：

```text
_sys
_os
_importlib
```

。

---

## 18.2 Layer B：positive API surface

对允许模块声明：

```python
_ALLOWED_MODULE_APIS = {
    "json": {
        "loads",
        "dumps",
    },
    "statistics": {
        "mean",
        "median",
        "pstdev",
        "pvariance",
    },
    "re": {
        "match",
        "search",
        "sub",
        "compile",
    },
    "collections": {
        "Counter",
        "defaultdict",
    },
}
```

对于：

```text
Path object
```

只允许：

```text
read_text
write_text
```

对于普通：

```text
str/list/dict
```

可以提供一套数据处理 method allowlist。

这样：

```text
module object traversal
```

就不会无限扩大。

---

# 19. 但是依然不要把 static policy 当 kernel sandbox

即便做 positive API allowlist，也应该把它定位成：

```text
Source Policy
=
减少错误行为
限制 action surface
提高可解释性
提前失败
```

而不是：

```text
Source Policy
=
Python sandbox
```

。

真正安全链应该是：

```text
Authority
    ↓
Source Policy
    ↓
Kernel Isolation
    ↓
Output Validation
    ↓
Semantic Quality Gate
```

五层缺一不可。

---

# 20. bwrap Sandbox：这一部分整体是当前 CodeAct 最强的地方

当前正式 LLM 路径在执行前会真实运行：

```text
readiness probe
```

而不是：

```text
which bwrap
```

。

probe 会验证：

```text
uid != 0
gid != 0

network unavailable

inputs write denied
outside write denied

project repo not mounted
host project path not mounted
other task workspace not mounted

output writable
```

。

这个设计应该保留。

---

# 21. 当前 `_run_llm_bwrap()` 的 namespace

当前使用：

```text
--die-with-parent
--new-session

--unshare-pid
--unshare-ipc
--unshare-uts
--unshare-net

--proc /proc
--dev /dev
--tmpfs /tmp
```

。

这覆盖了最关键的：

```text
process visibility
IPC
hostname
network
```

。

尤其：

```text
--new-session
```

也是 bubblewrap 官方文档明确强调的 sandbox hardening 参数之一。

---

# 22. Filesystem mount 也比较收敛

LLM CodeAct 不是把整个 StateBus repo bind 进去。

它大致只暴露：

```text
/usr
/usr/local
/bin
/lib
/lib64

Python runtime prefix

少量 /etc loader / identity files

/generated.py          RO
/inputs                RO
/outputs               RW
/tmp                   tmpfs
```

。

并且 readiness 还明确检查：

```text
/sandbox/project
```

不存在。

这一点比旧 `CodeActRunner._run_bwrap()` 强很多。

旧 runner 会：

```text
ro-bind project_root → /sandbox/project
bind entire workspace → /sandbox/workspace
```

。

因此再次证明：

```text
legacy deterministic runner
≠
LLM CodeAct security profile
```

。

---

# 23. 非 root identity

当前有两种情况。

## Host Runtime 本身是 root

进入 bwrap 后：

```text
setpriv
--reuid 65534
--regid 65534
--clear-groups
```

再运行 Python。

## Host Runtime 非 root

使用：

```text
--unshare-user
--uid 65534
--gid 65534
```

。

readiness probe 会实际断言：

```text
uid/gid != 0
```

。

这是正确的。

---

# 24. Bubblewrap 官方本身也提醒了一件事

Bubblewrap 官方文档明确说：

> bubblewrap 是构建 sandbox 的工具，而不是一套自动完整的 security policy。

安全程度取决于调用方选择的：

```text
namespace
mount
session
seccomp
device
resource
```

参数。

所以：

> StateBus 当前安全性的证据应该是“StateBus bwrap policy + executable readiness tests”，而不是“我们用了 bwrap”。

你们现在已经走在正确方向上。

---

# 25. 当前 Sandbox 最大缺口：没有 CodeAct 专属 seccomp

Bubblewrap 支持：

```text
seccomp filters
```

。

当前 StateBus `_run_llm_bwrap()` 没有看到：

```text
--seccomp
```

。

这意味着：

```text
文件系统和 namespace 被隔离
```

但 sandbox 内 Python 最终仍然直接面向：

```text
host Linux syscall ABI
```

。

---

# 26. 为什么 AST bypass 让 seccomp 更值得做

如果 Source Policy 真能保证：

```text
只能 json.loads + arithmetic + write_text
```

那么 syscall surface 已经非常窄。

但是前面已经证明：

```text
Python module object traversal
```

让 static policy 很难成为绝对边界。

因此更合理的组合是：

```text
positive API source lint
        +
bwrap namespaces
        +
seccomp
```

。

---

# 27. 要不要直接换 gVisor？

**现在不建议。**

gVisor 的隔离更强：

```text
application syscall
    ↓
gVisor Sentry
    ↓
userspace application kernel
    ↓
有限 host syscalls
```

它不是简单 syscall filter，而是重新实现 Linux syscall interface 的 userspace kernel。

这对：

```text
public multi-tenant arbitrary hostile code execution
```

非常适合。

但你们当前是：

```text
比赛
本地 A100
单机
bounded data CodeAct
```

。

为了 CodeAct 把整个 Runtime 搬到 gVisor：

```text
工程复杂度
部署复杂度
debug 成本
性能不确定性
```

都不划算。

---

# 28. nsjail 值得作为设计参考，但也不必马上迁移

Google `nsjail` 把：

```text
namespaces
rlimit
cgroup
seccomp-bpf
```

放在同一个 policy 系统里。

这是值得借鉴的。

尤其：

```text
seccomp allowlist
cgroup v2
pids max
```

比你们当前单纯：

```text
bwrap + RLIMIT
```

更容易形成“实际 enforced resource receipt”。

但当前更合理的路线是：

> **继续使用 bwrap，补 seccomp + cgroup，而不是为了名字更专业换 runner。**

---

# 29. 推荐 Sandbox Tier

## Tier 0 — 当前

```text
bwrap namespaces
non-root
mount isolation
network isolation
RLIMIT
```

已经能作为正式 baseline。

---

## Tier 1 — 本项目推荐

```text
bwrap
+
seccomp profile
+
cgroup v2:
    memory.max
    pids.max
    cpu.max / timeout
+
bounded stdout/stderr
+
minimal Python rootfs
```

这是你们应该做到的目标。

---

## Tier 2 — 未来 hostile multi-tenant

```text
gVisor / microVM
```

不属于当前比赛必做项。

---

# 30. Resource Limits：当前有，但“可证明性”还不够

`CodeGenerationPolicy` 当前提供：

```text
timeout_seconds
cpu_seconds
address_space_bytes
file_size_bytes
nofile_limit
nproc_limit
```

这很好。

问题在执行细节。

---

# 31. `_set_limit()` 静默忽略失败

当前：

```python
try:
    resource.setrlimit(...)
except (OSError, ValueError):
    return
```

。

所以理论上会出现：

```text
Policy:
address_space_bytes = 2 GiB

Runtime:
setrlimit failed

Record:
仍然只有 policy digest
```

。

这会让：

```text
declared budget
≠
actual enforced budget
```

。

---

# 32. 建议增加 `SandboxResourceReceipt`

例如：

```python
@dataclass(frozen=True)
class SandboxResourceReceipt:
    cpu_seconds_requested: int
    cpu_seconds_applied: bool

    address_space_bytes_requested: int
    address_space_applied: bool

    file_size_bytes_requested: int
    file_size_applied: bool

    nofile_requested: int
    nofile_applied: bool

    pids_requested: int
    pids_applied: bool

    cgroup_id: str
    cgroup_memory_max: int
    cgroup_pids_max: int

    receipt_hash: str
```

对于 critical resource：

```text
apply failed
    ↓
do not execute untrusted source
```

。

---

# 33. `nproc_limit = 65536` 太宽

`CodeGenerationPolicy` 默认：

```text
nproc_limit = 65,536
```

。

源码注释解释了：

```text
host-side orchestration / nested namespace launcher
需要较高 inherited RLIMIT_NPROC
```

。

这个动机可以理解。

但是这里混了：

```text
launcher resource requirement
```

和：

```text
untrusted payload process budget
```

。

两者应该分开。

---

# 34. 推荐

```text
Sandbox Launcher
    pids allowance:
    足够启动 bwrap / setpriv / python

Payload Cgroup
    pids.max:
    8 / 16 / 32
```

。

不要让：

```text
65,536
```

变成“模型程序允许产生的 process 数”。

---

# 35. 当前还有一个实际 DoS 面：stdout / stderr

当前：

```python
subprocess.run(
    ...,
    text=True,
    capture_output=True,
)
```

。

`RLIMIT_AS` 限制的是：

```text
child process
```

。

但是 `capture_output=True` 的内容最终由：

```text
parent Runtime process
```

收集。

于是模型可以做：

```python
for ...:
    print(...)
```

。

即使 child 自己内存没有爆：

```text
parent captured stdout
```

仍然可能不断增长。

当前只有：

```text
_runtime_diagnostic()
    → 最后截断到 4000 chars
```

但那是在：

```text
subprocess 已经结束以后
```

。

并不能限制 capture 过程。

---

# 36. 这是一个真实 P1 hardening 项

推荐：

```text
stdout_max_bytes = 256 KiB
stderr_max_bytes = 256 KiB
```

执行方式可以是：

### 方案 A

```text
stdout / stderr
→ capped temp file
```

结束后读取 bounded tail。

### 方案 B

Runtime 自己 drain pipe：

```text
read N bytes
超过阈值
    ↓
kill sandbox
    ↓
output_budget_exceeded
```

。

对你们来说 A 更简单。

---

# 37. 还应该增加

```text
RLIMIT_CORE = 0
```

避免 sandbox crash 生成 core。

并考虑：

```text
pids.max
memory.max
```

使用 cgroup v2 做 aggregate 限制。

因为：

```text
RLIMIT_CPU
```

本质更偏 per-process。

如果进程 fanout 被绕出来：

```text
aggregate CPU
```

最好由 cgroup 管。

---

# 38. Execution：one-shot Grant 设计是对的

`LlmCodeActRunner.execute()` 一开始：

```text
validate request ↔ grant
```

然后：

```text
grant_hash
```

会被放进：

```text
_consumed_grant_hashes
```

。

同一个 grant 不能再次 execute。

这意味着：

```text
candidate failed
```

不会变成：

```text
同一个 authority token 无限执行
```

。

repair 是在：

```text
同一个 bounded runner lifecycle
同一组 input authority
同一份 policy
```

中发生。

这是合理的。

---

# 39. Repair：当前没有发现“修代码顺便扩大权限”

Repair callback 收到：

```text
same CodeGenerationRequest
same base prompt
previous source
violations / runtime diagnostics / quality codes
```

。

repair 完之后：

```text
重新 audit_generated_source()
```

。

如果 repair 新加：

```text
socket
subprocess
unsafe path
```

会被重新拒绝。

并且执行仍然：

```text
same bwrap
same input_files
same output path
```

。

所以当前 repair architecture 是：

```text
repair changes implementation
≠
repair changes authority
```

这一点是对的。

---

# 40. 当前三类 repair

现在最多分别：

```text
policy repair × 1
runtime repair × 1
quality repair × 1
```

。

所以一个 CodeAct step 理论上可能发生：

```text
initial generation
+
policy repair
+
runtime repair
+
quality repair
```

也就是：

```text
最多 4 次 Executor LLM generation
```

。

---

# 41. 对低开销比赛，这个边界还应该更明确

建议增加：

```python
max_total_repairs: int = 2
max_total_generation_tokens: int
max_total_executor_wall_ms: int
```

。

这样 policy 可以表达：

```text
每类最多 1 次
并且全局最多 2 次
```

。

---

# 42. Formal repair prompt 本身没有发现 authority leak

当前 Formal runner 的 repair prompt 会加入：

```text
previous_source
violations
runtime diagnostic
output type guidance
operation semantics
completion criteria
output schema
```

。

特别是 quality mismatch：

```text
validator 不给 expected value
```

而只告诉：

```text
error code
```

。

这是正确的方向。

---

# 43. 但 Repair Prompt 仍然存在两个工程问题

## 43.1 Token 成本

它把：

```text
完整原始 prompt
+
previous source
+
repair diagnostics
+
semantic contract
```

全部重新发送。

CodeAct 的修复请求可能非常长。

---

## 43.2 APC prefix

如果改成：

```text
Stable CodeAct Policy Prefix
    ↓
Dynamic repair suffix
```

那么：

```text
initial generation
policy repair
runtime repair
quality repair
```

之间都可以复用很长的 prefix KV。

这和你们 APC 路线天然协同。

---

# 44. Validator：这是当前 CodeAct correctness 的真正核心

Sandbox 只能保证：

```text
程序不会随便访问 host
```

它不能保证：

```text
程序算对了
```

。

StateBus 的强点是执行后还有：

```text
Capability Validator
```

。

---

# 45. 当前 output validator 很严格

执行完后 `_validate_output()` 检查：

```text
expected output file 必须存在

不能是 symlink

outputs 下只能有一个 file/symlink

必须是 JSON

byte budget

object / array shape

array 不能为空

每行字段必须 exactly == output_schema

number 必须 finite

integer 不能 bool

boolean 必须 bool

required_output_fields 必须存在
```

。

这是一层很好的：

```text
structural gate
```

。

---

# 46. 后面还有 business validator

当前 registry 包括：

```text
metric_series
period_comparison
aggregation
join
anomaly
conflict
cited_report
generic_analysis
```

。

Controlled path 中：

```text
period comparison
aggregation
anomaly
```

可以 Runtime recompute。

这就是为什么 CodeAct 不只是：

```text
程序跑完 exit=0
```

就算成功。

---

# 47. 但 `generic_analysis` 必须正确表述

`generic_analysis` 明确没有能力：

```text
独立重算 arbitrary model-selected analysis
```

。

它主要验证：

```text
provenance
non-empty
required fields
finite values
completion criteria
```

并设置：

```text
recomputation_evaluated = False
```

。

但是如果这些 generic checks 都通过：

```text
verified = True
```

。

所以：

> **`VERIFIED` 当前不是统一强度的“语义正确”。**

它可能表示：

### Controlled validator

```text
Runtime independently recomputed
```

也可能表示：

### Generic validator

```text
schema + provenance + generic invariants passed
```

。

---

# 48. 建议增加 `VerificationStrength`

例如：

```text
STRUCTURAL
CONTRACT_VALIDATED
INDEPENDENT_RECOMPUTATION
```

。

External native benchmark 的隐藏 grader：

```text
不要塞进 Runtime
```

。

所以不需要：

```text
BENCHMARK_GOLD_VERIFIED
```

这种内部状态。

Native evaluator 继续留在 Runtime 外。

---

# 49. 为什么这个字段对 Memory Replay 很重要

因为：

```text
Artifact verified
```

和：

```text
这份 execution recipe 可以以后自动重放
```

不是一回事。

而当前源码恰好把两者混在了一起。

---

# 50. 一个重要的设计问题：`mark_verified()` 自动 `replay_ready=True`

`ExecutionArtifactRef` 默认：

```python
verification_state = CANDIDATE
replay_ready = False
```

。

但：

```python
ArtifactLifecycleManager.mark_verified()
```

会直接：

```python
verification_state = VERIFIED
replay_ready = True
```

。

也就是：

```text
Artifact Verified
        ↓
Recipe Replay Ready
```

被自动等价了。

---

# 51. 这对 CodeAct 不够严谨

一个 artifact 可以因为：

```text
generic schema/provenance validator
```

而 VERIFIED。

但它对应的 Python recipe 是否适合：

```text
VALIDATED_REPLAY
```

还需要判断：

```text
最终 source 是否精确绑定
policy 是否相同
validator strength 是否足够
input contract 是否兼容
runtime signature 是否兼容
source 是否仍能重新通过 policy
```

。

所以建议拆成：

```text
ArtifactVerification
```

和：

```text
ReplayEligibility
```

两个 gate。

---

# 52. 推荐 After

```text
Candidate Artifact
    ↓
Artifact Validator
    ↓
VERIFIED

        │
        └───────────────┐
                        ↓
              ReplayEligibilityGate
                        │
              ┌─────────┴─────────┐
              ▼                   ▼
       REPLAY_NOT_READY       REPLAY_READY
```

不要让：

```python
mark_verified()
```

自动设置：

```text
replay_ready=True
```

。

---

# 53. Round 03 最重要的源码问题：Verified Recipe 保存错 source

这是这一轮最值得先修的问题。

当前 `_dispatch_llm_python()` 做：

```python
source = code_source_factory(...)
```

然后：

```python
outcome = self.codeact_runner.execute(
    raw_response=source,
    ...
)
```

。

---

# 54. 但 Runner 内部会修改 source

`LlmCodeActRunner.execute()` 内部：

```text
candidate.source
```

可能经历：

```text
initial source

↓ policy repair

repaired source #1

↓ runtime repair

repaired source #2

↓ quality repair

repaired source #3
```

最终：

```text
artifact
quality report
record.source_hash
```

绑定的是：

```text
最终 candidate.source
```

。

---

# 55. 但 Dispatcher 成功以后存 recipe 用的是外层 `source`

当前：

```python
self.context.execution_recipes_by_artifact[artifact.artifact_id] = {
    "execution_kind": ...,
    "capability_id": step.capability_id,
    "output_contract_version": grant.output_contract_version,
    "source": source,
    "source_hash": sha256_digest(source.encode("utf-8")),
}
```

这里的：

```text
source
```

还是：

```text
runner 调用之前的初始 source
```

或者：

```text
memory replay 取出的 old source
```

。

它不是：

```text
最终通过 repair 后被验证的 candidate.source
```

。

---

# 56. 然后 Memory Commit 又把这份 recipe 当 verified recipe

`AdaptiveMainlineRunner._commit_verified_memory()` 会检查：

```text
terminal executor artifact VERIFIED

artifact bytes hash correct

quality_report.output_artifact_hash
    ==
artifact.blob_hash

quality report verified
```

这部分都很好。

然后：

```python
recipe = context.execution_recipes_by_artifact[artifact_id]
```

。

只检查：

```text
recipe 是非空 dict
```

。

并不会检查：

```text
recipe["source_hash"]
    ==
CodeExecutionRecord.source_hash
```

。

---

# 57. 最终这份 recipe 被放进

```text
MemoryRef.metadata["execution_recipe"]
```

。

未来：

```text
MemoryQuery
    ↓
_compatibility_decision()
    ↓
VALIDATED_REPLAY / EXACT_REPLAY
```

之后：

```python
source = replay_recipe["source"]
```

。

---

# 58. 所以实际链是

```text
Initial Source A
    ↓
Quality Failed
    ↓
Repair
    ↓
Verified Source B
    ↓
Artifact(B) VERIFIED
    ↓
Quality(B) VERIFIED
    ↓
Memory Commit
    ↓
recipe.source = A   ← 当前问题
    ↓
future replay
    ↓
execute A again
```

。

这违反了：

```text
Validated Replay
```

最基本的 identity。

---

# 59. 严重性怎么判断

它不是：

```text
host security escape
```

因为 replay source 仍然会：

```text
重新 AST audit
重新 bwrap
重新 output validate
重新 quality validate
```

。

所以即使 A 有问题，通常仍会失败或再次 repair。

但是它会导致：

```text
ValidatedReplay 不是真的 replay verified program

ExactReplay 不 deterministic

skip LLM generation 的收益可能消失

repair 可能再次发生

如果 generic validator 较弱，
错误原始 recipe 甚至可能在另一个输入上被 generic gate 接受

telemetry / claim 与实际 verified source identity 不一致
```

。

因此这个问题应该定为：

> **P0 correctness / evidence integrity bug。**

比赛系统尤其不能出现：

```text
我们声称“validated recipe replay”
但 recipe 本身不是当时被验证的程序
```

。

---

# 60. 修复方式很直接

## 60.1 `LlmCodeActOutcome` 暴露 final verified candidate

Before：

```python
@dataclass(frozen=True)
class LlmCodeActOutcome:
    record: CodeExecutionRecord
    policy_report: CodePolicyReport
    repairs: tuple[CodeRepairRecord, ...]
    artifact: ExecutionArtifactRef | None = None
    ...
```

After：

```python
@dataclass(frozen=True)
class LlmCodeActOutcome:
    record: CodeExecutionRecord
    policy_report: CodePolicyReport
    repairs: tuple[CodeRepairRecord, ...]

    final_candidate: GeneratedCodeCandidate | None = None

    artifact: ExecutionArtifactRef | None = None
    ...
```

只有成功 verified 时：

```text
final_candidate
```

才允许用于 replay recipe。

---

# 61. Dispatcher 必须保存 final source

After：

```python
verified_candidate = outcome.final_candidate

recipe = {
    "execution_kind": ExecutionKind.LLM_BOUNDED_PYTHON.value,
    "capability_id": step.capability_id,
    "output_contract_version": grant.output_contract_version,

    "source": verified_candidate.source,
    "source_hash": verified_candidate.source_hash,

    "quality_report_hash": outcome.record.quality_report_hash,
    "policy_digest": request.policy.policy_digest,
    "prompt_bundle_digest": request.prompt_signature,
    "runtime_signature": request.runtime_signature,
}
```

。

---

# 62. Memory Commit 增加 hard gate

```text
recipe.source_hash
    ==
CodeExecutionRecord.source_hash
```

否则：

```text
execution_recipe_source_hash_mismatch
    ↓
DO NOT COMMIT REPLAY RECIPE
```

。

---

# 63. 进一步建议：Recipe V2

建议正式定义：

```python
@dataclass(frozen=True)
class VerifiedExecutionRecipe:
    execution_kind: str
    capability_id: str
    output_contract_version: str

    source_hash: str
    source_ref: str

    policy_digest: str
    sandbox_policy_digest: str

    prompt_bundle_digest: str
    runtime_signature: str

    validator_digest: str
    quality_report_hash: str

    input_contract_fingerprint: str

    max_replay_class: str

    schema_version: str = "statebus.verified_execution_recipe.v2"
```

不一定必须把整个 Python source 永远塞在 metadata。

可以：

```text
source
→ CAS / workspace verified source blob

recipe
→ source_ref + source_hash
```

。

这更符合 StateBus typed state / artifact identity 风格。

---

# 64. Memory 当前 compatibility gate 本身其实做得不错

`_compatibility_decision()` 已经检查：

```text
Memory COMMITTED
Runtime validation PASSED

runtime signature

output contract

validator digest

canonical task family/intent/output

input schema drift

input lineage
```

。

然后才决定：

```text
ASSIST
VALIDATED_REPLAY
EXACT_REPLAY
```

。

这条 policy 思路是对的。

真正缺的是：

> **recipe 本身的 verification identity 没有被强绑定。**

---

# 65. `ExactReplay` 当前其实不是“结果直接复用”

当前 replay 最终仍然：

```text
recipe.source
    ↓
LlmCodeActRunner.execute()
    ↓
bwrap
    ↓
current input
    ↓
new output
```

。

所以：

```text
EXACT_REPLAY
```

当前更准确应该理解成：

> **Exact Recipe Replay**

不是：

```text
直接返回旧 artifact
```

。

---

# 66. `ValidatedReplay` 也一样

它做的是：

```text
跳过 LLM code generation
复用已验证 execution recipe
在当前输入上重新执行
```

。

这是一个很好的机制。

但 telemetry 名字要准确。

---

# 67. 当前一个指标容易被误读

`_record_memory_consumption()` 内部记录：

```text
skipped_generation_step_count
skipped_llm_call_count
```

但返回 metrics 时又叫：

```text
skipped_step_count
```

。

实际上：

```text
Runtime Executor step 没有被 skip
```

。

只是：

```text
source generation 被 skip
```

。

建议改成：

```text
recipe_replay_count
code_generation_skipped_count
executor_llm_call_skipped_count
sandbox_execution_reused_count = 0
artifact_result_reused_count = 0
```

。

这样证据不会夸大。

---

# 68. LlmCodeActCache 和 Memory Recipe 是两回事

当前还有：

```text
LlmCodeActCache
```

。

它是：

```text
同进程
verified result cache

same task
same session

new authorized grant
artifact still readable/hash correct
```

。

Key 包括：

```text
task_id
capability
semantic input digest
source hash
model signature
prompt signature
runtime signature
policy
output schema
```

。

这条 cache 很保守，安全性不错。

---

# 69. Memory Recipe 则是

```text
persistent
cross-run / cross-task compatible memory

不复用 output
而是复用 execution recipe
```

。

两者建议正式命名：

```text
VerifiedResultCache

VerifiedRecipeMemory
```

不要统称：

```text
CodeAct cache
```

。

---

# 70. Cache 还有一个小效率问题

如果：

```text
initial A
↓
repair
↓
final B
```

cache 最终：

```text
put(key(B))
```

。

下次同样 LLM 再产生：

```text
A
```

预执行 lookup 使用：

```text
key(A)
```

。

因此不会 hit 已有 B。

这不是 correctness bug。

只是：

```text
repair-heavy task
result cache 命中率可能偏低
```

。

Recipe Memory 修好后，这个问题没那么重要。

---

# 71. Artifact 链已经很接近完整 execution receipt

成功 CodeAct artifact 当前 metadata 有：

```text
schema_version
source_hash
quality_report_hash
session_id
attempt_id
```

。

`CodeExecutionRecord` 又有：

```text
request_hash
source_hash
raw_response_hash

policy_report_hash

sandbox requested/actual backend
sandbox readiness digest
sandbox policy digest
sandbox uid/gid
mount policy digest

input ref ids

output hash
output schema valid
output quality valid

exit code
timeout

validator errors
quality report hash

verified artifact id
runtime error
```

。

这其实已经非常像：

```text
CodeExecutionReceipt
```

。

---

# 72. 建议正式化 Receipt

未来不要让：

```text
Artifact metadata
CodeExecutionRecord
PolicyReport
QualityReport
Memory recipe
```

各自只靠散落 hash 关联。

可以定义：

```python
CodeExecutionReceipt:
    grant_hash

    request_hash

    initial_source_hash
    final_source_hash

    repair_chain_hash

    source_policy_report_hash

    sandbox_readiness_digest
    sandbox_policy_digest
    sandbox_resource_receipt_hash

    input_manifest_digest

    output_hash

    output_validation_hash
    quality_report_hash

    artifact_id

    verification_strength
    replay_eligibility

    receipt_hash
```

。

然后：

```text
Artifact.metadata.execution_receipt_hash
MemoryRecipe.execution_receipt_hash
```

都指向它。

这样你们的：

```text
provenance
audit
replay
```

叙事会非常强。

---

# 73. 25/25 到底证明了什么

此前 Formal CodeAct 从：

```text
14 / 25
```

提升到：

```text
25 / 25
```

这件事是有价值的。

它证明：

```text
固定 DSL expressiveness 不够
    ↓
LLM Bounded Python
可以覆盖 branch/recombine/custom parse/statistics 等更复杂执行需求
```

。

同时证明了：

```text
Generated Source
→ policy
→ sandbox
→ repair
→ validator
```

这整条 controlled contract execution 可以闭环。

---

# 74. 但是 25/25 不能被写成

```text
StateBus CodeAct 已经能通用解决任意数据分析任务
```

。

因为当前 Formal adapter 会给 Runtime：

```text
operation_semantics
source schema
output schema
quality constraints
formal validator contract
```

。

并且 Formal 的 repair prompt 会再次拿到：

```text
controller-owned semantic contract
```

。

这在 Controlled Benchmark 中完全合理。

但它证明的是：

> **contract-aware bounded code execution reliability。**

不是：

> **unknown external data-agent generalization。**

---

# 75. External Benchmark 下 CodeAct 应该怎么测

未来 IDA-Bench 入口应该：

```text
original task instruction
+
public assets
+
public declared constraints
```

进入 Runtime。

不能由 adapter 额外生成：

```text
hidden operation formula
adapter-selected method
hidden output field semantics
reference implementation
```

。

然后：

```text
Runtime generic CodeAct validator
```

只做：

```text
sandbox
schema
provenance
declared constraints
```

。

最终答案对不对：

```text
IDA native evaluator
```

在 Runtime 外判断。

---

# 76. External 下的 `VERIFIED` 也需要正确命名

建议：

```text
RuntimeVerifiedArtifact
```

表示：

```text
这个 artifact：
来源合法
执行合法
格式合法
provenance 合法
```

。

不是：

```text
benchmark answer guaranteed correct
```

。

这会和 Round 02 Benchmark Boundary 完全一致。

---

# 77. CodeAct 为什么仍然值得保留

这轮审计没有得出：

```text
Python 太危险，删掉 CodeAct
```

。

相反：

> **CodeAct 是你们 Routing 架构里最重要的 execution provider 之一。**

因为：

```text
DSL
    → 低成本
    → 易验证
    → expressiveness 有 ceiling

Bounded Python
    → 高 expressiveness
    → LLM generation cost 更高
    → sandbox / verification cost 更高
```

。

所以未来应该由：

```text
ExecutionBindingPolicy
```

决定：

```text
simple transformation
    → DSL

complex branch / parse / join / custom logic
    → CodeAct
```

。

---

# 78. 这才是 CodeAct 最适合 StateBus 的定位

不是：

```text
每个任务都用 CodeAct
```

而是：

```text
CodeAct
=
high-expressiveness bounded execution provider
```

。

Routing 第一原则仍然是：

```text
eligibility first
cost second
```

。

---

# 79. Round 03 推荐的最终架构

```text
Logical Analysis Step
        │
        ▼
ExecutionBindingPolicy
        │
        ├─────────────┐
        │             │
        ▼             ▼
 Transform DSL     Bounded Python
                   CodeAct
                      │
                      ▼
            CodeAuthorityContract
                      │
                      ▼
              LLM Source Candidate
                      │
                      ▼
               Source Policy
                 / AST lint
                      │
                      ▼
              bwrap + seccomp
              + cgroup budget
                      │
                      ▼
             Structural Validator
                      │
                      ▼
             Capability Validator
                      │
                      ▼
             Verification Receipt
                      │
              ┌───────┴────────┐
              ▼                ▼
        Verified Artifact   ReplayEligibility
                                │
                                ▼
                       VerifiedRecipeMemory
```

---

# 80. Before → After：最值得改的 Contract

## Before

```text
CodeGenerationRequest
CodeGenerationPolicy
CodePolicyReport
CodeRepairRecord
CodeExecutionRecord
ExecutionArtifactRef
MemoryRef.metadata.execution_recipe
```

---

## After

保留上面这些，但增加：

```text
CodeSemanticAuthority
SandboxResourceReceipt
CodeExecutionReceipt
VerifiedExecutionRecipe
ReplayEligibilityReceipt
VerificationStrength
```

不需要一次性全部做。

---

# 81. 实施顺序：C0

# C0 — Repair / Recipe Identity Correctness

这是第一优先级。

修改：

```text
statebus/runtime/llm_codeact.py
statebus/runtime/adaptive_dispatcher.py
statebus/runtime/adaptive_mainline.py
```

---

## C0.1 `LlmCodeActOutcome`

增加：

```text
final_candidate
```

。

---

## C0.2 `_dispatch_llm_python`

recipe 使用：

```text
outcome.final_candidate.source
outcome.final_candidate.source_hash
```

。

禁止使用 outer：

```text
source
```

。

---

## C0.3 `_commit_verified_memory`

增加：

```text
recipe.source_hash
==
CodeExecutionRecord.source_hash
```

hard gate。

---

## C0.4 测试

必须加：

```text
test_policy_repaired_codeact_recipe_uses_final_verified_source

test_runtime_repaired_codeact_recipe_uses_final_verified_source

test_quality_repaired_codeact_recipe_uses_final_verified_source

test_memory_commit_rejects_recipe_source_hash_mismatch

test_validated_replay_source_hash_matches_verified_execution_record
```

。

---

# 82. 实施顺序：C1

# C1 — Source Policy Hardening

修改：

```text
statebus/runtime/llm_codeact.py
tests/test_llm_codeact_policy.py
```

。

---

## C1.1 禁止 private module traversal

至少：

```text
module attribute startswith("_")
    → reject
```

。

---

## C1.2 Module API positive allowlist

不要再只做：

```text
allowed module root
```

。

增加：

```text
allowed module APIs
```

。

---

## C1.3 Adversarial policy tests

至少：

```text
test_policy_rejects_collections_private_sys_escape

test_policy_rejects_transitive_sys_modules_access

test_policy_rejects_execvp_family

test_policy_rejects_spawn_family

test_policy_rejects_private_module_attributes

test_policy_does_not_treat_ast_allowlist_as_sandbox_boundary
```

。

---

# 83. 实施顺序：C2

# C2 — Sandbox / Resource Hardening

修改：

```text
statebus/runtime/codeact_sandbox.py
statebus/contracts/llm_codeact.py
tests/test_llm_codeact_sandbox.py
```

。

---

## C2.1 bounded stdout / stderr

增加：

```text
stdout_max_bytes
stderr_max_bytes
```

。

---

## C2.2 RLIMIT enforcement receipt

不允许 critical rlimit 失败后静默继续。

---

## C2.3 process budget 分层

拆开：

```text
launcher_nproc_limit

payload_pids_max
```

。

---

## C2.4 cgroup v2

至少：

```text
memory.max
pids.max
```

。

CPU 可继续：

```text
wall timeout + RLIMIT_CPU
```

第一版即可。

---

## C2.5 seccomp

推荐先做：

```text
deny obvious privilege/kernel attack syscalls
```

而不是一上来做极窄 allowlist。

后续再根据 Python syscall trace 收紧。

---

# 84. Seccomp 第一版建议

思路可以参考 Docker default seccomp：

```text
deny dangerous syscalls
allow常规 Python runtime syscall
```

优先阻断：

```text
bpf
keyctl
add_key
request_key

ptrace
process_vm_readv
process_vm_writev

mount
umount2
pivot_root

reboot
kexec_load

init_module
finit_module
delete_module

swapon
swapoff

perf_event_open

open_by_handle_at
```

具体名单要基于：

```text
openEuler kernel
Python runtime
bwrap nesting方式
```

实际 trace 再冻结。

不要凭文档直接硬写最终 profile。

---

# 85. 实施顺序：C3

# C3 — Verification / Replay Semantics

修改：

```text
statebus/runtime/workspace.py
statebus/refs/models.py
statebus/runtime/adaptive_mainline.py
statebus/memory/store.py
```

。

---

## C3.1 不再 `mark_verified → replay_ready=True`

改成：

```text
mark_verified()
    → verification only

mark_replay_ready()
    → separate gate
```

。

---

## C3.2 Verification Strength

至少：

```text
STRUCTURAL
CONTRACT_VALIDATED
INDEPENDENT_RECOMPUTATION
```

。

---

## C3.3 Recipe Replay Eligibility

```text
source identity valid
policy compatible
runtime compatible
validator compatible
contract compatible
verification strength sufficient
```

才允许：

```text
VALIDATED_REPLAY
```

。

---

# 86. 实施顺序：C4

# C4 — Prompt / APC / Cost

修改：

```text
statebus/runtime/llm_codeact.py
benchmark bindings / executor prompt callers
telemetry
```

。

---

## C4.1 Stable prefix first

冻结：

```text
CodeActPolicyPrefixV2
```

。

---

## C4.2 Dynamic suffix

只放：

```text
task
schema
semantic contract
retrieval
memory
```

。

---

## C4.3 Repair prompt

复用同一：

```text
CodeActPolicyPrefixV2
```

。

---

## C4.4 全局 repair budget

增加：

```text
max_total_repairs
max_executor_generation_tokens
```

。

---

# 87. 实施顺序：C5

# C5 — External CodeAct Lane

等 Round 02 的：

```text
ExternalTaskEnvelope
InputAssetRef
Visibility Audit
```

先落地。

再做：

```text
IDA-Bench
```

。

此时 CodeAct Request 只允许：

```text
PUBLIC_RAW
PUBLIC_DECLARED_CONSTRAINT
PUBLIC_MECHANICAL_DERIVATION
```

。

---

# 88. 需要补的测试矩阵

## Authority

```text
grant mismatch
expired grant
input ref mismatch
capability mismatch
output contract mismatch
reused grant
```

已有一部分，继续保留。

---

## Source Policy

```text
direct os import

alias import

private module traversal

sys.modules traversal

exec/spawn family

dunder access

dynamic path

Path alias

Path derived variable

file mutation

reflection
```

。

---

## Sandbox

```text
network unavailable

repo unavailable

other task workspace unavailable

input RO

output only RW

non-root

GPU device unavailable

host /home unavailable

stdout cap

stderr cap

timeout

pid cap

memory cap

rlimit apply failure
```

。

---

## Repair

```text
policy repair no authority expansion

runtime repair no authority expansion

quality repair no answer leakage

repair total budget

repair final source identity
```

。

---

## Output

```text
symlink
extra output
invalid JSON
oversize
NaN
Infinity
wrong fields
wrong primitive type
empty array
```

。

---

## Artifact / Memory

```text
artifact hash mismatch

quality hash mismatch

recipe hash mismatch

final source hash mismatch

policy digest mismatch

validator digest mismatch

runtime signature mismatch

schema drift

lineage drift

exact recipe replay

validated recipe replay

generic verified artifact not automatically replay eligible
```

。

---

# 89. 哪些现有实现应该保留，不要重写

这轮不是“大改 CodeAct”。

以下全部建议保留：

```text
CapabilityGrant binding

one-shot grant consumption

CodeGenerationRequest

CodeGenerationPolicy

AST preflight

bwrap-required formal LLM path

readiness probe

non-root execution

network namespace

RO input / RW output split

output exact schema gate

quality validator registry

repair re-audit

verified result cache

Memory compatibility gate
```

。

---

# 90. 哪些不要做

当前不建议：

```text
为了 CodeAct 上 Firecracker

把整个系统换成 gVisor

删除 AST policy

允许 arbitrary pip install

把 repo mount 给 Executor

给 CodeAct 网络访问

把 benchmark grader 放进 Runtime

让 repair 修改 CapabilityGrant

让 Planner 直接生成 filesystem path

为了通用性直接开放 pandas/numpy/sklearn 全环境
```

。

尤其：

```text
pandas/numpy
```

是否加入，应该等：

```text
IDA-Bench
```

实际需要再决定。

---

# 91. 和 Routing 的关系

Round 01 路由方案中已经冻结：

```text
Logical Capability
    ≠
Execution Provider
```

。

CodeAct 正好是第一个最适合验证这个架构的地方。

未来：

```text
Logical:
analyze_verified_data_v1

Providers:
    transform_dsl_v2
    bounded_python_v2
```

。

---

# 92. Execution Binding 应该做什么

如果：

```text
simple filter
sort
aggregate
period diff
```

优先：

```text
DSL
```

。

如果发现：

```text
branch + recombine
complex parser
custom categorical rules
self join
pivot-like logic
multi-stage custom reduction
```

才：

```text
CodeAct
```

。

---

# 93. CodeAct 不是“高级就一定开”

这对比赛很重要。

因为 CodeAct 有：

```text
额外 Executor LLM call

大 prompt

source generation token

sandbox spawn

output validation

repair possibility
```

。

所以 Router 合法决策必须包括：

```text
BYPASS_CODEACT
```

。

---

# 94. 和 Memory 的关系

修完 recipe identity 后，Memory 最值得保留的不是：

```text
过去答案
```

而是：

```text
过去被验证过的 execution recipe
```

。

这非常符合你们：

```text
shared memory
```

赛题要求。

链路可以正式讲成：

```text
Task N
    ↓
LLM writes Python
    ↓
Runtime verifies recipe
    ↓
Memory stores VerifiedExecutionRecipe

Task N+1
    ↓
compatibility gate
    ↓
reuse recipe
    ↓
skip Executor code-generation call
    ↓
recompute on current verified input
```

。

这个故事比：

```text
memory 里存一段文字经验
```

强很多。

---

# 95. 但必须把证据做对

未来 benchmark 应同时记录：

```text
recipe candidate count

compatible recipe count

recipe reuse count

code generation skipped count

repair avoided count

sandbox execution count

output recomputation count

quality pass rate

LLM prompt tokens saved

LLM completion tokens saved

E2E latency delta
```

。

不要用模糊的：

```text
memory hit
```

一个数字。

---

# 96. 当前可以写进比赛材料的 CodeAct claim

推荐：

> **StateBus 将模型生成的 Python 视为未受信任的执行候选，而不是直接动作。Runtime 将其绑定到一次性 CapabilityGrant 和已验证输入 Ref，经静态 source policy、bwrap namespace 隔离、资源预算、严格输出 schema 与 capability quality gate 后，才产生 VERIFIED Artifact；通过兼容性校验的 verified execution recipe 可在后续相关任务中跳过代码生成并对当前输入重新计算。**

这个 claim 基本符合当前实现。

但是在 C0 修复前：

```text
verified execution recipe
```

这句话还不能完全硬说。

因为 repair recipe identity 还有问题。

---

# 97. 修完 C0 后，CodeAct 会从“功能完成”变成“证据闭环”

当前已经有：

```text
LLM generation
sandbox
repair
validator
artifact
memory
```

。

但缺的最后一环是：

```text
被存进 Memory 的 recipe
必须就是被验证的那一个 source
```

。

这一个 hash identity 修好之后：

```text
Generation
    ↓
Verification
    ↓
Artifact
    ↓
Recipe
    ↓
Memory
    ↓
Replay
```

才真正是闭环。

---

# 98. 最终评级

| 维度 | 当前评价 |
|---|---|
| Capability Authority | **强** |
| Grant Scope | **强** |
| Input Isolation | **强** |
| bwrap Fail-Closed | **强** |
| Network Isolation | **强** |
| Non-root | **强** |
| Static Source Policy | **中强，但 denylist 不可当 security boundary** |
| Resource Isolation | **中等，需要 bounded logs / enforce receipt / cgroup** |
| Repair Authority | **强** |
| Output Structural Validation | **强** |
| Controlled Semantic Validation | **强** |
| External Semantic Validation | **只能 generic，不能过度 claim** |
| Artifact Identity | **强** |
| Recipe Identity | **存在 P0 correctness gap** |
| Memory Compatibility | **强** |
| Replay Semantics | **设计不错，但 verification/replay eligibility 混合** |
| Token / APC Efficiency | **还有明显优化空间** |
| Contest Narrative | **有潜力成为核心工程亮点** |

---

# 99. 我建议下一步实际只做三个 Slice

不要一次重写。

## Slice C0-A

```text
Final Verified Source Identity
```

只修：

```text
LlmCodeActOutcome
Dispatcher recipe
Memory commit gate
tests
```

。

---

## Slice C0-B

```text
Replay Eligibility Separation
```

只修：

```text
mark_verified != replay_ready
recipe eligibility
verification strength
tests
```

。

---

## Slice C1

```text
Sandbox Hardening
```

只做：

```text
bounded stdout/stderr
rlimit receipt
private module traversal test/fix
pids cap
```

。

seccomp 可以作为 C1.2。

---

# 100. 下一轮建议

Round 03 完成后，下一轮不应该继续扩 CodeAct。

更值得继续的是：

# Round 04 — Shared Memory / Memory Runtime

逐代码审：

```text
MemoryQuery
    ↓
keyword / tags / embedding
    ↓
RRF
    ↓
compatibility
    ↓
ASSIST / VALIDATED_REPLAY / EXACT_REPLAY
    ↓
role consumption
    ↓
behavioral effect
    ↓
commit / invalidation
```

重点判断：

```text
当前 shared memory 到底是真的跨任务可复用，
还是 benchmark-oriented memory plumbing；

embedding retrieval 是否真带来选择收益；

Replay 与 Assist 是否分得足够干净；

Memory commit 是否可能污染后续任务；

当前 SQLite / FTS5 / FAISS 路线是否合理；

LongMemEval-V2 入口之前还缺什么。
```

这会和本 Round 的：

```text
VerifiedRecipeMemory
```

直接衔接。

---

# Appendix A — 关键源码文件

本轮主要审计：

```text
statebus/contracts/llm_codeact.py

statebus/runtime/llm_codeact.py
statebus/runtime/codeact.py
statebus/runtime/codeact_sandbox.py
statebus/runtime/adaptive_dispatcher.py
statebus/runtime/adaptive_mainline.py
statebus/runtime/capability_validators.py
statebus/runtime/workspace.py

statebus/refs/models.py

statebus/memory/models.py
statebus/memory/store.py

statebus/benchmark/adaptive_formal_mainline.py

tests/test_llm_codeact_policy.py
tests/test_llm_codeact_sandbox.py
tests/test_adaptive_codeact_integration.py
```

---

# Appendix B — 外部设计参考

## CodeAct

Xingyao Wang et al., **Executable Code Actions Elicit Better LLM Agents**, ICML 2024, arXiv:2402.01030.

借鉴点：

```text
Executable code as flexible action representation
multi-turn correction
code execution feedback
```

StateBus 不应照搬：

```text
arbitrary interactive shell
```

而应继续保持：

```text
Runtime-authorized bounded execution provider
```

。

---

## Bubblewrap

`containers/bubblewrap`

关键启发：

```text
bubblewrap 本身是 sandbox construction toolkit
security policy 由调用方参数决定

mount namespace
PID namespace
IPC namespace
network namespace
user namespace
seccomp
--new-session
```

因此 StateBus 应继续把：

```text
bwrap policy
```

做成可审计 contract，而不是只记录：

```text
backend=bwrap
```

。

---

## nsjail

`google/nsjail`

值得借鉴：

```text
namespace
seccomp-bpf
rlimit
cgroup v2
```

统一 policy 的做法。

当前不必迁移。

---

## gVisor

`google/gvisor`

值得理解：

```text
userspace application kernel
intercept application syscalls
reduce direct host-kernel syscall surface
```

适合：

```text
hostile multi-tenant arbitrary code
```

。

当前 StateBus 不需要为了比赛迁移到 gVisor。

---

## Docker / OpenHands

Docker 官方默认 seccomp 使用 syscall allowlist 风格。

OpenHands 等通用 coding-agent runtime 更强调：

```text
containerized arbitrary code environment
```

。

StateBus 与它们的差异应保持：

```text
OpenHands:
general coding workspace

StateBus CodeAct:
typed input refs
bounded capability
fixed output contract
controller validator
verified artifact
recipe memory
```

。

这反而是 StateBus 的特色。

---

# Appendix C — 最终一句话

Round 03 最终不是发现：

```text
CodeAct 是 toy
```

。

而是发现：

> **当前 CodeAct 的执行安全主链已经比较完整；真正影响系统可信度的核心缺口，是“最终被验证的程序”与“之后被记忆/重放的 recipe”之间还没有形成严格 identity binding，同时 OS isolation 的资源与 syscall 边界还需要从“存在”升级为“可证明”。**

优先修掉这两个点，CodeAct 就可以从：

```text
一个成功率增强功能
```

升级成：

```text
StateBus 的正式高表达力 Execution Provider
+
可验证 Recipe Memory
```

。
