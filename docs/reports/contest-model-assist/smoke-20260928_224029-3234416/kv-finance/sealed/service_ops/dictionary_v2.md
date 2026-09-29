# Public definitions v2

completed_request_count includes requests that ultimately failed. error_rate_pct=100*sum(final_failed_request_count)/sum(completed_request_count); mean_latency_ms=sum(request_latency_sum_ms)/sum(completed_request_count), both rounded to four decimals. failed_attempt_count is diagnostic and must not be used as the error numerator. Risk uses the UNROUNDED ratio final_failed/completed > slo_error_rate.
