"""Summarize canary JSONL without copying prompts or response text."""
import argparse
import collections
import json
import statistics
from pathlib import Path


def rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf8').splitlines()]


def summarize(requests, monitor):
    groups = collections.defaultdict(list)
    hashes = collections.defaultdict(set)
    for r in requests:
        if r['cancelled']:
            continue
        label = r['label'].split(':')[-1]
        groups[label].append(r['ttft_s'])
        hashes[label].add(r['output_sha256'])
    return {
        'requests': len(requests),
        'cancelled': sum(bool(r['cancelled']) for r in requests),
        'engine_pids': sorted({r['engine_pid_at_start'] for r in requests}),
        'host_free_min_gib': min(r['host_available_bytes'] for r in monitor) / 2**30,
        'monitor_minutes': (monitor[-1]['time'] - monitor[0]['time']) / 60,
        'monitor_alerts': sum(bool(r['alerts']) for r in monitor),
        'labels': {k: {'n': len(v), 'median_ttft_s': statistics.median(v),
                       'min_ttft_s': min(v), 'max_ttft_s': max(v),
                       'distinct_hashes': len(hashes[k])}
                   for k, v in sorted(groups.items())},
    }


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('requests')
    p.add_argument('monitor')
    args = p.parse_args()
    print(json.dumps(summarize(rows(args.requests), rows(args.monitor)), indent=2))
