#!/usr/bin/env python3
"""Read host-side chain evidence; no provider or Runtime calls."""
import argparse
import json
from pathlib import Path


def display(value):
    return 'missing' if value is None else str(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    roots = [args.output] if (args.output / 'ledger.json').is_file() else [args.output / name for name in ('finance', 'service_ops')]
    for root in roots:
        path = root / 'ledger.json'
        if not path.exists():
            print(f'{root.name}: ledger missing/not started')
            continue
        ledger = json.loads(path.read_text())
        print(f'\n{root}: {len(ledger)} planned slots')
        print('task\tstatus\tquality\trequests\ttokens\trepair\te2e_ms\treplays\tcross_agent_reads\treason')
        for row in ledger:
            metrics = row.get('metrics', {})
            events_path = root / 'slots' / row['task_id'] / 'memory-events.jsonl'
            events = [json.loads(line) for line in events_path.read_text().splitlines()] if events_path.exists() else []
            consumes = [e for e in events if e.get('event') == 'consume' and e.get('consume_receipt')]
            replay = sum(e.get('replay_count', 0) for e in consumes) if events else None
            cross = sum(e.get('source_agent') != e.get('consumer_agent') and e.get('artifact_read_bytes', 0) > 0 for e in consumes) if events else None
            reason = row.get('blocked_reason') or row.get('error') or row.get('failure_codes') or row.get('scorer_errors') or ''
            values = [row['task_id'], row['status'], row.get('quality'), metrics.get('provider_request_count'),
                      metrics.get('provider_total_tokens'), row.get('repair'), row.get('e2e_ms'), replay, cross, reason]
            print('\t'.join(display(v) for v in values))
        summary_path = root / 'metrics/summary.json'
        if summary_path.exists():
            summary = json.loads(summary_path.read_text())
            totals = summary['aggregate']
            print(f"passed={totals['passed_count']}/{totals['planned_count']} planned; "
                  f"started={totals['started_count']}, blocked={totals['blocked_count']}, not_started={totals['not_started_count']}; "
                  f"provider_tokens={display(totals['provider_total_tokens'])}")
            print('Memory query/candidate-hit/actual-use:', json.dumps(summary['memory'], ensure_ascii=False))
        for name in ('communication', 'state', 'memory'):
            print(f'{name}: {root / "metrics" / (name + ".json")}')


if __name__ == '__main__':
    main()
