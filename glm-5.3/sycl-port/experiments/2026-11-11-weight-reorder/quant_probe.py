from pathlib import Path
import sys,collections
sys.path.insert(0,r'<work>\maya\tools')
from gguf_reader import GGUFFile
p=Path(r'<models>\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-Q6_K_XL.gguf'); files=[('qwen',[p]),('glm',sorted(Path(r'<work>\glm-m').glob('GLM-5.3-Flash-Maya-M-IQ2_S-*.gguf')))]
for name,paths in files:
 counts=collections.Counter();bytes_=collections.Counter()
 for path in paths:
  for t in GGUFFile(path).tensors:counts[t.type_name]+=1;bytes_[t.type_name]+=t.expected_bytes() or 0
 print(name,'files',len(paths),'counts',dict(counts),'iq4_bytes',{k:bytes_[k] for k in ('IQ4_NL','IQ4_XS')})
