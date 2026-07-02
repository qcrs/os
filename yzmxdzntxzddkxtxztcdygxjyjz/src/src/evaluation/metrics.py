"""
性能评测模块 - 收集和分析系统性能指标
"""

import logging
import time
from typing import Dict, List, Any
from dataclasses import dataclass, asdict
from datetime import datetime
from collections import defaultdict


@dataclass
class PerformanceMetrics:
    """性能指标数据类"""

    task_id: str
    task_start_time: float
    task_end_time: float = 0.0
    message_count: int = 0
    text_tokens: int = 0
    text_chars: int = 0
    state_transfer_count: int = 0
    state_transfer_bytes: int = 0
    memory_hits: int = 0
    memory_misses: int = 0
    mode: str = "structured"  # structured | text_only | hybrid

    def get_duration(self) -> float:
        """获取任务耗时（秒）"""
        if self.task_end_time == 0:
            return 0
        return self.task_end_time - self.task_start_time

    def get_memory_hit_rate(self) -> float:
        """获取记忆命中率"""
        total = self.memory_hits + self.memory_misses
        if total == 0:
            return 0.0
        return self.memory_hits / total

    def to_dict(self) -> Dict:
        """转换为字典"""
        data = asdict(self)
        data["duration_ms"] = self.get_duration() * 1000
        data["memory_hit_rate"] = self.get_memory_hit_rate()
        return data


class MetricsCollector:
    """
    性能指标收集器
    """

    def __init__(self):
        self.logger = logging.getLogger("MetricsCollector")
        self.metrics: Dict[str, PerformanceMetrics] = {}
        self.current_task_id: str = None

    def start_task(self, task_id: str, mode: str = "structured") -> str:
        """
        开始任务计时

        Args:
            task_id: 任务ID
            mode: 通信模式

        Returns:
            任务ID
        """
        self.current_task_id = task_id
        metrics = PerformanceMetrics(
            task_id=task_id,
            task_start_time=time.time(),
            mode=mode,
        )
        self.metrics[task_id] = metrics
        self.logger.info(f"Started metrics collection for task: {task_id}")
        return task_id

    def end_task(self, task_id: str):
        """
        结束任务计时

        Args:
            task_id: 任务ID
        """
        if task_id in self.metrics:
            self.metrics[task_id].task_end_time = time.time()
            self.logger.info(f"Ended metrics collection for task: {task_id}")

    def record_message(self, task_id: str, message_type: str, size_bytes: int = 0, tokens: int = 0):
        """
        记录消息

        Args:
            task_id: 任务ID
            message_type: 消息类型 (text|state|binary)
            size_bytes: 消息大小
            tokens: token数量
        """
        if task_id not in self.metrics:
            return

        metrics = self.metrics[task_id]
        metrics.message_count += 1

        if message_type == "text":
            metrics.text_tokens += tokens
            metrics.text_chars += size_bytes
        elif message_type == "state":
            metrics.state_transfer_count += 1
            metrics.state_transfer_bytes += size_bytes

    def record_memory_hit(self, task_id: str):
        """记录记忆命中"""
        if task_id in self.metrics:
            self.metrics[task_id].memory_hits += 1

    def record_memory_miss(self, task_id: str):
        """记录记忆未命中"""
        if task_id in self.metrics:
            self.metrics[task_id].memory_misses += 1

    def get_task_metrics(self, task_id: str) -> Dict:
        """获取任务指标"""
        if task_id not in self.metrics:
            return {}
        return self.metrics[task_id].to_dict()

    def get_all_metrics(self) -> List[Dict]:
        """获取所有任务指标"""
        return [m.to_dict() for m in self.metrics.values()]


class PerformanceAnalyzer:
    """
    性能分析器 - 对比不同模式的性能
    """

    def __init__(self):
        self.logger = logging.getLogger("PerformanceAnalyzer")
        self.results_by_mode: Dict[str, List[Dict]] = defaultdict(list)

    def add_result(self, metrics: Dict):
        """添加性能指标"""
        mode = metrics.get("mode", "unknown")
        self.results_by_mode[mode].append(metrics)

    def compare_modes(self) -> Dict[str, Any]:
        """
        对比不同通信模式的性能

        Returns:
            对比结果
        """
        comparison = {}

        modes = list(self.results_by_mode.keys())
        if len(modes) < 2:
            return {"error": "Need at least 2 modes for comparison"}

        # 计算每个模式的平均指标
        for mode in modes:
            results = self.results_by_mode[mode]
            if not results:
                continue

            avg_metrics = {
                "mode": mode,
                "count": len(results),
                "avg_duration_ms": sum(r["duration_ms"] for r in results) / len(results),
                "avg_messages": sum(r["message_count"] for r in results) / len(results),
                "avg_text_tokens": sum(r["text_tokens"] for r in results) / len(results),
                "avg_state_transfers": sum(r["state_transfer_count"] for r in results) / len(results),
                "avg_memory_hit_rate": sum(r["memory_hit_rate"] for r in results) / len(results),
            }
            comparison[mode] = avg_metrics

        # 计算改进比例
        if len(modes) >= 2:
            baseline_mode = modes[0]
            comparison["improvements"] = {}

            for mode in modes[1:]:
                baseline = comparison[baseline_mode]
                target = comparison[mode]

                improvement = {
                    "vs_mode": baseline_mode,
                    "duration_reduction": (
                        (baseline["avg_duration_ms"] - target["avg_duration_ms"]) / baseline["avg_duration_ms"] * 100
                    ),
                    "message_reduction": (
                        (baseline["avg_messages"] - target["avg_messages"]) / baseline["avg_messages"] * 100
                        if baseline["avg_messages"] > 0
                        else 0
                    ),
                    "token_reduction": (
                        (baseline["avg_text_tokens"] - target["avg_text_tokens"]) / baseline["avg_text_tokens"] * 100
                        if baseline["avg_text_tokens"] > 0
                        else 0
                    ),
                    "memory_hit_improvement": target["avg_memory_hit_rate"] - baseline["avg_memory_hit_rate"],
                }
                comparison["improvements"][mode] = improvement

        return comparison

    def generate_report(self) -> str:
        """生成性能报告"""
        comparison = self.compare_modes()

        report = f"""
================== Performance Comparison Report ==================
Generated: {datetime.now().isoformat()}

{self._format_comparison(comparison)}

====================================================================
"""
        return report

    def _format_comparison(self, comparison: Dict) -> str:
        """格式化对比结果"""
        if "error" in comparison:
            return f"Error: {comparison['error']}"

        lines = []

        # 显示每个模式的指标
        for mode, metrics in comparison.items():
            if mode == "improvements":
                continue
            lines.append(f"\nMode: {mode}")
            lines.append(f"  Tasks: {metrics['count']}")
            lines.append(f"  Avg Duration: {metrics['avg_duration_ms']:.2f}ms")
            lines.append(f"  Avg Messages: {metrics['avg_messages']:.1f}")
            lines.append(f"  Avg Tokens: {metrics['avg_text_tokens']:.1f}")
            lines.append(f"  Avg State Transfers: {metrics['avg_state_transfers']:.1f}")
            lines.append(f"  Memory Hit Rate: {metrics['avg_memory_hit_rate']:.1%}")

        # 显示改进
        if "improvements" in comparison:
            lines.append("\n\nPerformance Improvements:")
            for mode, improvement in comparison["improvements"].items():
                lines.append(f"\n{mode} vs {improvement['vs_mode']}:")
                lines.append(f"  Duration Reduction: {improvement['duration_reduction']:.1f}%")
                lines.append(f"  Message Reduction: {improvement['message_reduction']:.1f}%")
                lines.append(f"  Token Reduction: {improvement['token_reduction']:.1f}%")
                lines.append(f"  Memory Hit Improvement: {improvement['memory_hit_improvement']:.1%}")

        return "\n".join(lines)
