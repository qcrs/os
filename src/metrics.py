"""Performance metrics collection and reporting."""

import time
from dataclasses import dataclass, field


@dataclass
class Metrics:
    """Collects and reports performance metrics for the multi-agent demo."""

    timings: dict[str, list[float]] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)
    store_ops: list[dict] = field(default_factory=list)
    # Communication protocol metrics
    message_log: list[dict] = field(default_factory=list)
    # LLM token usage per agent call
    token_log: list[dict] = field(default_factory=list)
    # Context compression records for structured protocol
    compression_log: list[dict] = field(default_factory=list)
    # Latent KV mode metrics
    latent_steps_log: list[dict] = field(default_factory=list)
    latent_kv_bytes_log: list[dict] = field(default_factory=list)

    def reset(self):
        """Reset all metrics (for mode comparison)."""
        self.timings.clear()
        self.counters.clear()
        self.store_ops.clear()
        self.message_log.clear()
        self.token_log.clear()
        self.compression_log.clear()
        self.latent_steps_log.clear()
        self.latent_kv_bytes_log.clear()

    def record_message(self, source: str, target: str, action: str,
                       param_chars: int, result_chars: int,
                       has_embedding: bool, embedding_dims: int = 0):
        """Record an inter-agent message for communication overhead tracking."""
        self.message_log.append({
            "source": source,
            "target": target,
            "action": action,
            "param_chars": param_chars,
            "result_chars": result_chars,
            "has_embedding": has_embedding,
            "embedding_dims": embedding_dims,
            "timestamp": time.time(),
        })

    def record_tokens(self, agent: str, input_tokens: int, output_tokens: int):
        """Record LLM token usage for an agent call."""
        self.token_log.append({
            "agent": agent,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "timestamp": time.time(),
        })

    def record_context_compression(
        self, original_chars: int, compressed_chars: int, source: str
    ):
        """Record protocol-driven context compression statistics."""
        self.compression_log.append({
            "source": source,
            "original_chars": original_chars,
            "compressed_chars": compressed_chars,
            "saved_chars": original_chars - compressed_chars,
            "ratio": compressed_chars / max(original_chars, 1),
            "timestamp": time.time(),
        })

    def record_timing(self, name: str, duration: float):
        """Record a timing measurement."""
        self.timings.setdefault(name, []).append(duration)

    def increment(self, name: str, count: int = 1):
        """Increment a counter."""
        self.counters[name] = self.counters.get(name, 0) + count

    def record_store_op(self, op: str, namespace: tuple, key: str, duration: float, **extra):
        """Record a store operation."""
        self.store_ops.append({
            "op": op,
            "namespace": namespace,
            "key": key,
            "duration": duration,
            **extra,
        })

    def record_latent_steps(self, agent: str, n_steps: int, duration: float, kv_bytes_added: int):
        """Record latent KV steps for an agent."""
        self.latent_steps_log.append({
            "agent": agent,
            "n_steps": n_steps,
            "duration": duration,
            "time_per_step": duration / max(n_steps, 1),
            "kv_bytes_added": kv_bytes_added,
            "timestamp": time.time(),
        })

    def record_kv_transfer(self, from_agent: str, to_agent: str, kv_bytes: int, copied_bytes: int = 0):
        """Record KV state transfer between agents."""
        self.latent_kv_bytes_log.append({
            "from_agent": from_agent,
            "to_agent": to_agent,
            "kv_bytes": kv_bytes,
            "copied_bytes": copied_bytes,
            "timestamp": time.time(),
        })

    def report(self) -> str:
        """Generate a formatted performance report."""
        lines = ["=" * 70, "Performance Metrics Report", "=" * 70, ""]

        # Task timings
        lines.append("--- Task Timings ---")
        for name, durations in sorted(self.timings.items()):
            avg = sum(durations) / len(durations)
            lines.append(
                f"  {name}: avg={avg:.4f}s, min={min(durations):.4f}s, "
                f"max={max(durations):.4f}s, count={len(durations)}"
            )
        lines.append("")

        # Counters
        if self.counters:
            lines.append("--- Counters ---")
            for name, count in sorted(self.counters.items()):
                lines.append(f"  {name}: {count}")
            lines.append("")

        # Store operations
        if self.store_ops:
            lines.append("--- Store Operations ---")
            put_ops = [op for op in self.store_ops if op["op"] == "put"]
            get_ops = [op for op in self.store_ops if op["op"] == "get"]
            search_ops = [op for op in self.store_ops if op["op"] == "search"]

            if put_ops:
                avg_put = sum(op["duration"] for op in put_ops) / len(put_ops)
                lines.append(f"  put: {len(put_ops)} ops, avg={avg_put:.6f}s")
            if get_ops:
                avg_get = sum(op["duration"] for op in get_ops) / len(get_ops)
                lines.append(f"  get: {len(get_ops)} ops, avg={avg_get:.6f}s")
            if search_ops:
                avg_search = sum(op["duration"] for op in search_ops) / len(search_ops)
                lines.append(f"  search: {len(search_ops)} ops, avg={avg_search:.6f}s")
                scores = [op.get("score") for op in search_ops if op.get("score") is not None]
                if scores:
                    lines.append(f"  search scores: avg={sum(scores)/len(scores):.4f}, "
                                 f"min={min(scores):.4f}, max={max(scores):.4f}")
            lines.append("")

        # Memory reuse analysis
        reuse_hits = self.counters.get("memory_reuse_hits", 0)
        reuse_attempts = self.counters.get("memory_reuse_attempts", 0)
        if reuse_attempts > 0:
            lines.append("--- Memory Reuse ---")
            lines.append(f"  Reuse attempts: {reuse_attempts}")
            lines.append(f"  Reuse hits: {reuse_hits}")
            lines.append(f"  Hit rate: {reuse_hits / reuse_attempts * 100:.1f}%")
            lines.append("")

        # Communication overhead estimate
        node_timings = {k: v for k, v in self.timings.items() if k.startswith("node_")}
        if node_timings:
            lines.append("--- Communication Overhead Estimate ---")
            total_node_time = sum(sum(v) for v in node_timings.values())
            task_timings = {k: v for k, v in self.timings.items() if k.startswith("task_")}
            if task_timings:
                total_task_time = max(sum(v) for v in task_timings.values())
                overhead = total_task_time - total_node_time
                lines.append(f"  Total node execution: {total_node_time:.4f}s")
                lines.append(f"  Total task time: {total_task_time:.4f}s")
                lines.append(f"  Framework overhead: {overhead:.4f}s "
                             f"({overhead / total_task_time * 100:.1f}%)")
            lines.append("")

        # Structured communication metrics
        if self.message_log:
            lines.append("--- Structured Communication Metrics ---")
            lines.append(f"  Total messages: {len(self.message_log)}")
            total_param_chars = sum(m["param_chars"] for m in self.message_log)
            total_result_chars = sum(m["result_chars"] for m in self.message_log)
            lines.append(f"  Param chars (total): {total_param_chars}")
            lines.append(f"  Result chars (total): {total_result_chars}")
            lines.append(f"  Total payload chars: {total_param_chars + total_result_chars}")
            emb_msgs = [m for m in self.message_log if m["has_embedding"]]
            lines.append(f"  Embedding transfers: {len(emb_msgs)}")
            if emb_msgs:
                lines.append(f"  Embedding dims: {emb_msgs[0]['embedding_dims']}")
            # Per-action breakdown
            actions = {}
            for m in self.message_log:
                a = m["action"]
                actions.setdefault(a, 0)
                actions[a] += 1
            for a, cnt in sorted(actions.items()):
                lines.append(f"  Action '{a}': {cnt} message(s)")
            lines.append("")

        # Context compression metrics
        if self.compression_log:
            lines.append("--- Context Compression ---")
            original = sum(c["original_chars"] for c in self.compression_log)
            compressed = sum(c["compressed_chars"] for c in self.compression_log)
            saved = original - compressed
            ratio = compressed / max(original, 1)
            lines.append(f"  Records: {len(self.compression_log)}")
            lines.append(f"  Original chars: {original}")
            lines.append(f"  Compressed chars: {compressed}")
            lines.append(f"  Saved chars: {saved} ({(1 - ratio) * 100:.1f}%)")
            by_source = {}
            for record in self.compression_log:
                source = record["source"]
                bucket = by_source.setdefault(source, {"original": 0, "compressed": 0, "count": 0})
                bucket["original"] += record["original_chars"]
                bucket["compressed"] += record["compressed_chars"]
                bucket["count"] += 1
            for source, bucket in sorted(by_source.items()):
                source_ratio = bucket["compressed"] / max(bucket["original"], 1)
                lines.append(
                    f"  {source}: {bucket['count']} records, "
                    f"saved={(1 - source_ratio) * 100:.1f}%"
                )
            lines.append("")

        # LLM Token usage
        if self.token_log:
            lines.append("--- LLM Token Usage ---")
            total_input = sum(t["input_tokens"] for t in self.token_log)
            total_output = sum(t["output_tokens"] for t in self.token_log)
            total_all = total_input + total_output
            lines.append(f"  Total calls: {len(self.token_log)}")
            lines.append(f"  Input tokens: {total_input}")
            lines.append(f"  Output tokens: {total_output}")
            lines.append(f"  Total tokens: {total_all}")
            # Per-agent breakdown
            agents = {}
            for t in self.token_log:
                a = t["agent"]
                if a not in agents:
                    agents[a] = {"input": 0, "output": 0, "calls": 0}
                agents[a]["input"] += t["input_tokens"]
                agents[a]["output"] += t["output_tokens"]
                agents[a]["calls"] += 1
            for a, d in sorted(agents.items()):
                lines.append(f"  {a}: {d['calls']} calls, "
                             f"in={d['input']}, out={d['output']}, "
                             f"total={d['input'] + d['output']}")
            lines.append("")

        # Latent KV mode metrics
        if self.latent_steps_log:
            lines.append("--- Latent KV Steps ---")
            total_steps = sum(l["n_steps"] for l in self.latent_steps_log)
            total_duration = sum(l["duration"] for l in self.latent_steps_log)
            total_kv_bytes = sum(l["kv_bytes_added"] for l in self.latent_steps_log)
            lines.append(f"  Total latent steps: {total_steps}")
            lines.append(f"  Total latent forward time: {total_duration:.4f}s")
            lines.append(f"  Avg time per step: {total_duration / max(total_steps, 1) * 1000:.2f}ms")
            lines.append(f"  Total KV bytes added: {total_kv_bytes} ({total_kv_bytes / 1024 / 1024:.2f} MB)")
            # Per-agent breakdown
            by_agent = {}
            for l in self.latent_steps_log:
                a = l["agent"]
                if a not in by_agent:
                    by_agent[a] = {"steps": 0, "duration": 0, "kv_bytes": 0}
                by_agent[a]["steps"] += l["n_steps"]
                by_agent[a]["duration"] += l["duration"]
                by_agent[a]["kv_bytes"] += l["kv_bytes_added"]
            for a, d in sorted(by_agent.items()):
                lines.append(f"  {a}: {d['steps']} steps, {d['duration']:.4f}s, "
                             f"{d['kv_bytes'] / 1024:.1f} KB")
            lines.append("")

        if self.latent_kv_bytes_log:
            lines.append("--- Latent KV Transfers ---")
            total_kv = sum(l["kv_bytes"] for l in self.latent_kv_bytes_log)
            total_copied = sum(l["copied_bytes"] for l in self.latent_kv_bytes_log)
            lines.append(f"  Transfers: {len(self.latent_kv_bytes_log)}")
            lines.append(f"  Total KV bytes passed: {total_kv} ({total_kv / 1024 / 1024:.2f} MB)")
            lines.append(f"  Actual copied bytes: {total_copied} ({total_copied / 1024 / 1024:.2f} MB)")
            lines.append(f"  Copy overhead: {total_copied / max(total_kv, 1) * 100:.1f}%")
            lines.append("")

        lines.append("=" * 70)
        return "\n".join(lines)

    def summary_dict(self) -> dict:
        """Return key metrics as a dict for comparison."""
        task_timings = {k: v for k, v in self.timings.items() if k.startswith("task_")}
        total_task_time = max(sum(v) for v in task_timings.values()) if task_timings else 0
        node_timings = {k: v for k, v in self.timings.items() if k.startswith("node_")}
        total_node_time = sum(sum(v) for v in node_timings.values()) if node_timings else 0
        total_input_tokens = sum(t["input_tokens"] for t in self.token_log)
        total_output_tokens = sum(t["output_tokens"] for t in self.token_log)

        # Latent KV metrics
        total_latent_steps = sum(l["n_steps"] for l in self.latent_steps_log)
        total_latent_duration = sum(l["duration"] for l in self.latent_steps_log)
        total_kv_bytes = sum(l["kv_bytes_added"] for l in self.latent_steps_log)
        total_kv_transferred = sum(l["kv_bytes"] for l in self.latent_kv_bytes_log)
        total_kv_copied = sum(l["copied_bytes"] for l in self.latent_kv_bytes_log)

        return {
            "message_count": len(self.message_log),
            "param_chars": sum(m["param_chars"] for m in self.message_log),
            "result_chars": sum(m["result_chars"] for m in self.message_log),
            "embedding_transfers": sum(1 for m in self.message_log if m["has_embedding"]),
            "context_packets_enabled": self.counters.get("context_packets_enabled", 0),
            "context_packets_disabled": self.counters.get("context_packets_disabled", 0),
            "embedding_received": self.counters.get("embedding_received", 0),
            "context_packet_fallback_documents": self.counters.get(
                "context_packet_fallback_documents", 0
            ),
            "context_original_chars": sum(c["original_chars"] for c in self.compression_log),
            "context_compressed_chars": sum(c["compressed_chars"] for c in self.compression_log),
            "context_saved_chars": sum(c["saved_chars"] for c in self.compression_log),
            "total_task_time": total_task_time,
            "total_node_time": total_node_time,
            "memory_reuse_hits": self.counters.get("memory_reuse_hits", 0),
            "llm_calls": len(self.token_log),
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "total_tokens": total_input_tokens + total_output_tokens,
            # Latent KV specific
            "latent_steps_total": total_latent_steps,
            "latent_forward_time": total_latent_duration,
            "latent_kv_bytes_added": total_kv_bytes,
            "latent_kv_bytes_transferred": total_kv_transferred,
            "latent_kv_bytes_copied": total_kv_copied,
            "avoided_prefill_tokens": self.counters.get("avoided_prefill_tokens", 0),
        }


# Global metrics instance
metrics = Metrics()
