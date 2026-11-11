from pathlib import Path
import sys, hashlib
sys.path.insert(0, r'<work>\maya\tools')
from strata_tokenizer import Tokenizer
out=Path(r'<work>\experiments\codex-sub768-validation-20261110'); out.mkdir(parents=True,exist_ok=True)
tok=Tokenizer.from_dir(r'<work>\glm-m\pack\tokenizer')
code=Path(r'<work>\maya\tools\strata_tokenizer.py').read_text(encoding='utf8')
text='\n'.join(f'Record {i:04}: The station inventory holds {i%37+4} copper valves and {i%29+8} steel fittings. The inspector signed the report on day {i%28+1} and the next review is in {i%12+1} months.' for i in range(300))
for name,src in [('code',code),('records',text)]:
 ids=tok.encode(src)
 if len(ids)<8192: ids=(ids*((8192//len(ids))+1))
 ids=ids[:8192]
 data=','.join(map(str,ids)).encode('ascii')
 (out/(name+'.txt')).write_bytes(data)
 print(name,len(ids),hashlib.sha256(data).hexdigest(),flush=True)
