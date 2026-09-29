# Public definitions

Request counts include failed requests. error_rate_pct=100*sum(failed_request_count)/sum(request_count); mean_latency_ms=sum(latency_sum_ms)/sum(request_count), both rounded to four decimals. Risk uses the UNROUNDED ratio failed/request > slo_error_rate. Read each site's threshold from slo.csv. Never average hourly rates.
