from pathlib import Path
import struct,collections
root=Path(r'<work>\experiments\codex-sub768-routing-20261110')
def load(p):
 d=p.read_bytes(); off=0; out=collections.defaultdict(list)
 while off<len(d):
  layer,k=struct.unpack_from('<ii',d,off); off+=8
  if not(0<=layer<50 and 0<k<=32 and off+8*k<=len(d)): raise ValueError('bad record')
  ids=struct.unpack_from('<'+'i'*k,d,off); off+=8*k
  out[layer].append(ids)
 return out
a=load(root/'baseline-routing.bin');b=load(root/'sub768-routing.bin');assert a.keys()==b.keys()
for layer in sorted(a):
 assert len(a[layer])==len(b[layer])==832
 x=a[layer];y=b[layer]; pre=sum(set(x[i])!=set(y[i]) for i in range(768)); dec=sum(set(x[i])!=set(y[i]) for i in range(768,832))
 print(f'layer={layer} prefill_set_changes={pre}/768 decode_set_changes={dec}/64')
