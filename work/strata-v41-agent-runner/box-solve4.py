import json
S = json.load(open(r'C:\b70-work\tensor-summary.json'))
layers = S['per_layer']; ils = sorted(int(k) for k in layers); N = len(ils)
nonlayer = S['total_gib'] - sum(v['total_gib'] for v in layers.values())
CARD_GIB = (32558 - 1500) / 1024.0
for ncm in (18, 22, 24, 26, 28):
    gs = [layers[str(i)]['total_gib'] - (layers[str(i)]['experts_gib'] if i < ncm else 0) for i in ils]
    cum = []; acc = nonlayer
    for s in gs: acc += s; cum.append(acc)
    best = None; bm = 1e9
    for a in range(1, N-2):
        for b in range(a+1, N-1):
            for c in range(b+1, N):
                d = (cum[a-1], cum[b-1]-cum[a-1], cum[c-1]-cum[b-1], cum[N-1]-cum[c-1])
                if max(d) < bm: bm = max(d); best = (a, b, c, d)
    a, b, c, d = best; fr = [a, b-a, c-b, N-c]
    cpu = sum(layers[str(i)]['experts_gib'] for i in range(ncm))
    print('ncmoe %d gpu_total=%.2f cpu=%.2f layers=%s -ts %s cards=%s' % (ncm, cum[-1], cpu, fr,
          ','.join('%g' % round(100.0*x/N, 1) for x in fr), ','.join('%.2f' % x for x in d)))
