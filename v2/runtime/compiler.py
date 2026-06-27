from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from v2.contracts import (
    CanonicalTaskSpec,
    CompilerStatus,
    TaskCompilerInput,
    TaskCompilerResult,
    TaskMode,
)


@dataclass
class TaskCompiler:
    default_task_family: str = "financial_report_analysis"
    default_required_tools: tuple[str, ...] = ("table_retriever", "semantic_retriever")

    def compile(self, compiler_input: TaskCompilerInput) -> TaskCompilerResult:
        parsed = self._try_parse_spec_json(compiler_input.request_text)
        if parsed is not None:
            return TaskCompilerResult(
                status=CompilerStatus.COMPILED,
                canonical_task_spec=self._canonical_from_mapping(parsed),
            )
        if compiler_input.task_mode == TaskMode.BENCHMARK_STRICT:
            return TaskCompilerResult(
                status=CompilerStatus.REJECTED,
                canonical_task_spec=None,
                compiler_errors=("benchmark_strict_requires_precompiled_canonical_spec",),
            )
        heuristic = self._heuristic_compile(compiler_input)
        if heuristic is None:
            return TaskCompilerResult(
                status=CompilerStatus.OPAQUE_FREEFORM,
                canonical_task_spec=None,
                compiler_warnings=("interactive_fallback_to_opaque_freeform",),
            )
        return TaskCompilerResult(
            status=CompilerStatus.COMPILED,
            canonical_task_spec=heuristic,
            compiler_warnings=("interactive_heuristic_compile",),
        )

    def _try_parse_spec_json(self, request_text: str) -> dict[str, Any] | None:
        request_text = request_text.strip()
        if not request_text.startswith("{"):
            return None
        try:
            parsed = json.loads(request_text)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        if "task_family" not in parsed or "intent_op" not in parsed:
            return None
        return parsed

    def _canonical_from_mapping(self, mapping: dict[str, Any]) -> CanonicalTaskSpec:
        return CanonicalTaskSpec(
            task_family=str(mapping.get("task_family", self.default_task_family)),
            intent_op=str(mapping.get("intent_op", "opaque_intent")),
            target_entities=tuple(mapping.get("target_entities", [])),
            time_scope=str(mapping.get("time_scope", "")),
            required_outputs=tuple(mapping.get("required_outputs", [])),
            required_tools=tuple(mapping.get("required_tools", self.default_required_tools)),
            arguments=dict(mapping.get("arguments", {})),
        )

    def _heuristic_compile(self, compiler_input: TaskCompilerInput) -> CanonicalTaskSpec | None:
        request_text = compiler_input.request_text.strip()
        if not request_text:
            return None
        lowered = request_text.lower()
        intent_op = "summarize_risk"
        if "compare" in lowered:
            intent_op = "compare_metric"
        elif "chart" in lowered or "plot" in lowered:
            intent_op = "generate_chart"
        target_entities = tuple(
            token.strip(",. ")
            for token in request_text.split()
            if token[:1].isupper() and len(token.strip(",. ")) > 1
        )[:3]
        required_outputs = (
            tuple(compiler_input.requested_outputs)
            if compiler_input.requested_outputs
            else ("summary_text",)
        )
        return CanonicalTaskSpec(
            task_family=compiler_input.corpus_family or self.default_task_family,
            intent_op=intent_op,
            target_entities=target_entities,
            required_outputs=required_outputs,
            required_tools=self.default_required_tools,
            arguments={"request_text": request_text},
        )

