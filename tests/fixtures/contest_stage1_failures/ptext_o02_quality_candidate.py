import json
import pathlib
from collections import defaultdict

input_data = json.loads(pathlib.Path('inputs/task.json').read_text())
groups = defaultdict(lambda: defaultdict(lambda: {
    'request_count': 0,
    'failed_request_count': 0,
    'latency_sum_ms': 0,
    'slo_error_rate': None,
    'event_locator': None,
}))
for row in input_data:
    site_id = row['site_id']
    is_current = row['is_current']
    groups[site_id][is_current]['request_count'] += row['request_count']
    groups[site_id][is_current]['failed_request_count'] += row['failed_request_count']
    groups[site_id][is_current]['latency_sum_ms'] += row['latency_sum_ms']
    if is_current:
        groups[site_id][is_current]['slo_error_rate'] = row['slo_error_rate']
        groups[site_id][is_current]['event_locator'] = row['event_locator']

has_previous = any(not row['is_current'] for row in input_data)
result = []
for site_id in sorted(groups.keys()):
    current = groups[site_id][True]
    request_count = current['request_count']
    failed_request_count = current['failed_request_count']
    latency_sum_ms = current['latency_sum_ms']
    slo_error_rate = current['slo_error_rate']
    error_rate_pct = round(100 * failed_request_count / request_count, 4)
    mean_latency_ms = round(latency_sum_ms / request_count, 4)
    exceeds_slo = failed_request_count / request_count > slo_error_rate
    if not has_previous:
        risk_change = 'initial'
    else:
        prior = groups[site_id][False]
        prior_request_count = prior['request_count']
        prior_failed_request_count = prior['failed_request_count']
        prior_slo_error_rate = prior['slo_error_rate']
        if prior_request_count == 0 or prior_slo_error_rate is None:
            risk_change = 'initial'
        else:
            prior_exceeds_slo = prior_failed_request_count / prior_request_count > prior_slo_error_rate
            if exceeds_slo and not prior_exceeds_slo:
                risk_change = 'new'
            elif not exceeds_slo and prior_exceeds_slo:
                risk_change = 'resolved'
            elif exceeds_slo and prior_exceeds_slo:
                risk_change = 'still_risk'
            else:
                risk_change = 'still_clear'
    result.append({
        'site_id': site_id,
        'request_count': request_count,
        'failed_request_count': failed_request_count,
        'error_rate_pct': error_rate_pct,
        'mean_latency_ms': mean_latency_ms,
        'exceeds_slo': exceeds_slo,
        'risk_change': risk_change,
        'event_locator': current['event_locator'],
    })
pathlib.Path('outputs/result.json').write_text(json.dumps(result))
