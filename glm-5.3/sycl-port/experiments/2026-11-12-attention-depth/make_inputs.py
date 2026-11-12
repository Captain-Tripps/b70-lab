"""Make fixed token-prefix fixtures on Zeus; the source text stays on Zeus."""
from pathlib import Path
import hashlib
import sys

work = Path(r'D:\maya-sycl')
dest = work / 'experiments' / 'codex-glm-attention-depth-20261112'
dest.mkdir(exist_ok=False)
sys.path.insert(0, str(work / 'maya' / 'tools'))
from strata_tokenizer import Tokenizer

tokenizer = Tokenizer.from_dir(str(work / 'glm-m' / 'pack' / 'tokenizer'))
ids = tokenizer.encode((work / 'long_body.txt').read_text(encoding='utf8'))
print('available_tokens', len(ids), flush=True)
if len(ids) < 100000:
    raise RuntimeError('fixture too short')
for n in (2048, 32768, 100000):
    data = ','.join(map(str, ids[:n])).encode('ascii')
    (dest / ('input-' + str(n) + '.txt')).write_bytes(data)
    print(n, hashlib.sha256(data).hexdigest(), flush=True)
