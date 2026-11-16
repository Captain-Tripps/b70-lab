"""Per-card, per-kernel GPU time of one VTune gpu-offload capture (prompt read, 1 new token).
usage: vt_tasks.py <tasks.tsv> [top]"""
import csv, collections, re, sys
csv.field_size_limit(10**9)


def short(name):
    m = re.match(r'strata::kernels::(\w+)::(\w+)', name)
    s = f'{m.group(1)}::{m.group(2)}' if m else name
    lam = re.search(r'lambda\(sycl::_V1::nd_item<\(int\)\d>\)#(\d+)', name)
    if lam and m:
        s += f'#{lam.group(1)}'
    if not m:
        # template-heavy names (ggml / grouped GEMM): keep the function, drop template arguments
        s = re.sub(r'<[^<>]*>', '', re.sub(r'<[^<>]*>', '', re.sub(r'<[^<>]*>', '', s)))
        s = s[:90]
    return s


d = collections.defaultdict(lambda: [0.0, 0])
with open(sys.argv[1], encoding='utf-8-sig', errors='replace') as f:
    r = csv.reader(f, delimiter='\t')
    head = next(r)
    ia, it, itt, ic = (head.index('GPU Adapter'), head.index('Computing Task'), head.index('Computing Task:Total Time'),
                       head.index('Computing Task:Instance Count'))
    for row in r:
        if len(row) <= ic or not row[itt]:
            continue
        k = (row[ia].split(' ')[0], short(row[it]))
        d[k][0] += float(row[itt]); d[k][1] += int(float(row[ic] or 0))
top = int(sys.argv[2]) if len(sys.argv) > 2 else 15
cards = sorted({k[0] for k in d}, key=lambda s: int(s.split(':')[1]) if ':' in s else 0)
for c in cards:
    rows = sorted(((v[0], v[1], k[1]) for k, v in d.items() if k[0] == c), reverse=True)
    cp = sum(t for t, n, s in rows if 'MemoryCopy' in s or 'MemoryFill' in s)
    tot = sum(t for t, n, s in rows) - cp
    print(f'== card bdf {c}: kernels {tot:.2f} s, copies/fills {cp:.2f} s')
    for t, n, s in rows[:top]:
        print(f'   {t:7.3f} s {100 * t / max(tot, 1e-9):5.1f}%  {n:7d} calls  {1e6 * t / max(n, 1):9.1f} us/call  {s}')
