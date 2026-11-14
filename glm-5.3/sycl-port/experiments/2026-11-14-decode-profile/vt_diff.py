"""Per-card, per-kernel GPU time for 1000 decode tokens: the 1300-token VTune capture minus the 300-token one."""
import csv, collections, re, sys
csv.field_size_limit(10**9)


def load(p):
    d = collections.defaultdict(lambda: [0.0, 0])
    with open(p, encoding='utf-8-sig', errors='replace') as f:
        r = csv.reader(f, delimiter='\t')
        head = next(r)
        ia, it, itt, ic = head.index('GPU Adapter'), head.index('Computing Task'), head.index('Computing Task:Total Time'), head.index('Computing Task:Instance Count')
        for row in r:
            if len(row) <= ic or not row[itt]:
                continue
            bdf = row[ia].split(' ')[0]
            name = row[it]
            m = re.match(r'strata::kernels::(\w+)::(\w+)', name)
            short = f'{m.group(1)}::{m.group(2)}' if m else name[:60]
            lam = re.search(r'lambda\(sycl::_V1::nd_item<\(int\)\d>\)#(\d+)', name)
            if lam and m:
                short += f'#{lam.group(1)}'
            d[(bdf, short)][0] += float(row[itt])
            d[(bdf, short)][1] += int(float(row[ic] or 0))
    return d


a = load(sys.argv[1]); b = load(sys.argv[2])
keys = set(a) | set(b)
diff = {k: (b.get(k, [0, 0])[0] - a.get(k, [0, 0])[0], b.get(k, [0, 0])[1] - a.get(k, [0, 0])[1]) for k in keys}
cards = sorted({k[0] for k in keys}, key=lambda s: int(s.split(':')[1]))
for c in cards:
    rows = sorted(((v[0], v[1], k[1]) for k, v in diff.items() if k[0] == c), reverse=True)
    tot = sum(r[0] for r in rows if 'MemoryCopy' not in r[2] and 'MemoryFill' not in r[2])
    cp = sum(r[0] for r in rows if 'MemoryCopy' in r[2] or 'MemoryFill' in r[2])
    print(f'== card bdf {c}: kernels {tot:.2f} s, copies/fills {cp:.2f} s (per token: {tot:.2f} / {cp:.2f} ms)')
    for t, n, name in rows[:12]:
        print(f'   {t:7.3f} s  {n:8d} calls  {1e6 * t / max(n, 1):7.1f} us/call  {name}')
