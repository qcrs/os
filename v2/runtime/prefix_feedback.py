from __future__ import annotations

"""Control-plane prefix cache feedback loop.

Compares StateBus's scheduling-side predicted KV prefix cache hit rate
(derived from ``EngineLocalPrefixRegistry`` corpus-group ordering) against
the actual ``gpu_prefix_cache_hit_rate`` exposed by the vLLM ``/metrics``
Prometheus endpoint.

The feedback loop does **not** mutate any external state.  It emits two
signals that callers use to decide whether to reorder their task queue:

* :meth:`PrefixCacheFeedbackLoop.should_reorder` — boolean: prediction error
  exceeds the configured threshold.
* :meth:`PrefixCacheFeedbackLoop.mean_error` — scalar: signed mean difference
  (predicted − observed) over the current sliding window.

Usage example (inside a benchmark runner loop)::

    from v2.runtime.prefix_feedback import PrefixCacheFeedbackLoop
    from v2.runtime.vllm_metrics import fetch_vllm_prefix_cache_metrics

    feedback = PrefixCacheFeedbackLoop(window_size=20, error_threshold=0.15)

    for task in tasks:
        predicted_hit_rate = schedule_hints[task.id].estimated_prefix_cache_hit_rate
        before = fetch_vllm_prefix_cache_metrics(metrics_url)
        run_task(task)
        record_live(feedback, predicted_hit_rate, before=before, metrics_url=metrics_url)
        if feedback.should_reorder():
            tasks = reorder_by_cache_affinity(tasks, feedback.mean_error())
"""

from collections import deque
from dataclasses import dataclass, field
from v2.runtime.vllm_metrics import (
    VllmPrefixCacheCounterDelta,
    VllmPrefixCacheMetrics,
    compute_vllm_prefix_cache_counter_delta,
    fetch_vllm_prefix_cache_metrics,
)


# ---------------------------------------------------------------------------
# Snapshot type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PrefixCacheFeedbackSnapshot:
    """Immutable point-in-time snapshot of the feedback loop state.

    Attributes:
        window_size: configured maximum window length.
        sample_count: number of samples currently in the window.
        mean_predicted: mean predicted hit rate over the window.
        mean_observed: mean observed (vLLM-reported) hit rate over the window.
        mean_error: signed ``mean_predicted − mean_observed``; positive means
            the control plane over-predicted.
        abs_mean_error: absolute value of ``mean_error``.
        should_reorder: whether ``abs_mean_error`` exceeds the threshold.
        error_threshold: the configured threshold for ``should_reorder``.
    """

    window_size: int
    sample_count: int
    mean_predicted: float
    mean_observed: float
    mean_error: float
    abs_mean_error: float
    should_reorder: bool
    error_threshold: float
    unavailable_observation_count: int = 0

    def canonical_payload(self) -> dict[str, object]:
        """Return a JSON-serialisable dict for telemetry / logging."""
        return {
            "window_size": self.window_size,
            "sample_count": self.sample_count,
            "mean_predicted": round(self.mean_predicted, 6),
            "mean_observed": round(self.mean_observed, 6),
            "mean_error": round(self.mean_error, 6),
            "abs_mean_error": round(self.abs_mean_error, 6),
            "should_reorder": self.should_reorder,
            "error_threshold": self.error_threshold,
            "unavailable_observation_count": self.unavailable_observation_count,
        }

    def metrics(self) -> dict[str, float]:
        """Return flat float metrics for smoke.py task_metrics injection."""
        return {
            "prefix_feedback_mean_predicted": self.mean_predicted,
            "prefix_feedback_mean_observed": self.mean_observed,
            "prefix_feedback_mean_error": self.mean_error,
            "prefix_feedback_abs_mean_error": self.abs_mean_error,
            "prefix_feedback_should_reorder": float(self.should_reorder),
            "prefix_feedback_sample_count": float(self.sample_count),
            "prefix_feedback_unavailable_observation_count": float(
                self.unavailable_observation_count
            ),
        }


# ---------------------------------------------------------------------------
# Feedback loop
# ---------------------------------------------------------------------------

@dataclass
class PrefixCacheFeedbackLoop:
    """Sliding-window calibration loop: predicted vs. observed prefix cache hit rate.

    Args:
        window_size: maximum number of recent (predicted, observed) pairs to
            retain.  Older samples are discarded automatically.
        error_threshold: ``abs(mean_predicted − mean_observed)`` value above
            which :meth:`should_reorder` returns ``True``.
    """

    window_size: int = 20
    error_threshold: float = 0.15

    _predicted_window: deque[float] = field(
        default_factory=lambda: deque(maxlen=20), repr=False
    )
    _observed_window: deque[float] = field(
        default_factory=lambda: deque(maxlen=20), repr=False
    )
    _unavailable_observation_count: int = field(default=0, repr=False)

    def __post_init__(self) -> None:
        # Re-create deques with the configured maxlen (field default is 20).
        self._predicted_window = deque(maxlen=self.window_size)
        self._observed_window = deque(maxlen=self.window_size)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def record(
        self,
        predicted_hit_rate: float,
        observed: VllmPrefixCacheMetrics,
    ) -> None:
        """Append one (predicted, observed) pair to the sliding window.

        Args:
            predicted_hit_rate: the hit rate estimated by the StateBus
                control plane for the just-completed task batch
                (typically ``NeuralPrefixReuseEstimate.estimated_prefix_cache_hit_rate``).
            observed: live metrics fetched from the vLLM ``/metrics``
                endpoint via :func:`~v2.runtime.vllm_metrics.fetch_vllm_prefix_cache_metrics`.
        """
        self._predicted_window.append(float(predicted_hit_rate))
        self._observed_window.append(float(observed.hit_rate))

    def record_observation(
        self,
        predicted_hit_rate: float,
        observation: VllmPrefixCacheCounterDelta,
    ) -> None:
        """Record a task-local counter delta, or an explicit unavailable sample."""
        if not observation.valid or observation.observed_hit_rate is None:
            self.record_unavailable()
            return
        self._predicted_window.append(float(predicted_hit_rate))
        self._observed_window.append(float(observation.observed_hit_rate))

    def reset(self) -> None:
        """Clear all samples from the sliding window."""
        self._predicted_window.clear()
        self._observed_window.clear()
        self._unavailable_observation_count = 0

    def record_unavailable(self) -> None:
        """Record a failed or schema-incompatible metrics observation."""
        self._unavailable_observation_count += 1

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def sample_count(self) -> int:
        """Number of samples currently in the window."""
        return len(self._predicted_window)

    def mean_error(self) -> float:
        """Signed mean of ``predicted − observed`` over the current window.

        Returns 0.0 when the window is empty.  A positive value means the
        control plane over-predicted (tasks were scheduled expecting more
        reuse than the GPU actually delivered).
        """
        if not self._predicted_window:
            return 0.0
        n = len(self._predicted_window)
        return (sum(self._predicted_window) - sum(self._observed_window)) / n

    def should_reorder(self) -> bool:
        """Return True when the absolute mean error exceeds the threshold.

        Callers should use this as a signal to re-sort the upcoming task
        queue by ``corpus_prefix_hash`` affinity groups, giving the GPU
        prefix cache a better chance to warm up before the next batch.
        """
        return abs(self.mean_error()) > self.error_threshold

    def snapshot(self) -> PrefixCacheFeedbackSnapshot:
        """Return an immutable snapshot of the current loop state."""
        n = len(self._predicted_window)
        mean_pred = sum(self._predicted_window) / n if n else 0.0
        mean_obs = sum(self._observed_window) / n if n else 0.0
        error = mean_pred - mean_obs
        return PrefixCacheFeedbackSnapshot(
            window_size=self.window_size,
            sample_count=n,
            mean_predicted=mean_pred,
            mean_observed=mean_obs,
            mean_error=error,
            abs_mean_error=abs(error),
            should_reorder=abs(error) > self.error_threshold,
            error_threshold=self.error_threshold,
            unavailable_observation_count=self._unavailable_observation_count,
        )


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def make_feedback_loop(
    *,
    window_size: int = 20,
    error_threshold: float = 0.15,
) -> PrefixCacheFeedbackLoop:
    """Create a :class:`PrefixCacheFeedbackLoop` with the given parameters.

    Thin factory kept separate so callers can swap implementations in tests
    without reaching into the dataclass constructor.
    """
    return PrefixCacheFeedbackLoop(
        window_size=window_size,
        error_threshold=error_threshold,
    )


# ---------------------------------------------------------------------------
# Probe helper (optional live fetch)
# ---------------------------------------------------------------------------

def record_live(
    loop: PrefixCacheFeedbackLoop,
    predicted_hit_rate: float,
    *,
    before: VllmPrefixCacheMetrics,
    metrics_url: str = "http://127.0.0.1:8000/metrics",
    timeout_s: float = 2.0,
) -> PrefixCacheFeedbackSnapshot:
    """Fetch post-task metrics and record the task-local counter delta.

    Network failures and responses without prefix-cache metrics are counted as
    unavailable observations and are not added to the calibration window. The
    caller must capture ``before`` immediately before the task so cumulative
    vLLM service counters are never treated as task-local observations.

    Args:
        loop: the feedback loop to update in-place.
        predicted_hit_rate: control-plane estimate for the current task.
        before: vLLM prefix-cache metrics captured immediately before the task.
        metrics_url: Prometheus text endpoint URL.
        timeout_s: per-request timeout in seconds.

    Returns:
        :class:`PrefixCacheFeedbackSnapshot` after the new observation.
    """
    try:
        after = fetch_vllm_prefix_cache_metrics(
            metrics_url=metrics_url, timeout_s=timeout_s
        )
    except Exception:
        loop.record_unavailable()
        return loop.snapshot()
    loop.record_observation(
        predicted_hit_rate,
        compute_vllm_prefix_cache_counter_delta(before, after),
    )
    return loop.snapshot()
