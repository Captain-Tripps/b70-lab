from pathlib import Path
import struct,collections
import numpy as np
root=Path(r'<work>\experiments\codex-sub768-routing-20261110')
def read(path):
 data=path.read_bytes(); p=0; out=collections.defaultdict(list)
 while p<len(data):
  if p+8>len(data): raise ValueError('truncated header')
  layer,k=struct.unpack_from('<ii',data,p); p+=8
  if not (0<=layer<50 and 0<k<=32 and p+8*k<=len(data)): raise ValueError(f'bad record at {p-8}: {layer},{k}')
  ids=struct.unpack_from('<'+'i'*k,data,p); p+=4*k
  weights=struct.unpack_from('<'+'f'*k,data,p); p+=4*k
  out[layer].append((ids,weights))
 return out
a=read(root/'baseline-routing.bin'); b=read(root/'sub768-routing.bin')
assert a.keys()==b.keys()
print('layer counts:',[(k,len(v)) for k,v in sorted(a.items())])
for lo,hi,label in [(0,768,'prefill'),(768,832,'forced_decode')]:
 changes=[]; reorder=0; maxdw=0.; n=0
 for layer in sorted(a):
  assert len(a[layer])==len(b[layer])
  for pos in range(lo,min(hi,len(a[layer]))):
   x,xw=a[layer][pos];y,yw=b[layer][pos]; n+=1
   if x!=y:
    if set(x)!=set(y): changes.append((layer,pos,x,y))
    else: reorder+=1
   maxdw=max(maxdw,max(abs(u-v) for u,v in zip(xw,yw)))
 print(label,'records',n,'expert_set_changes',len(changes),'order_only_changes',reorder,'max_weight_index_diff',maxdw)
 for row in changes[:12]: print('changed',row)
