from pathlib import Path
import hashlib
root=Path(r'<work>\experiments\codex-sub768-diagnosis-20261110'); root.mkdir(parents=True,exist_ok=True)
ids=Path(r'<work>\long32k.txt').read_text().strip().split(',')[:832]
data=','.join(ids).encode(); (root/'first832.txt').write_bytes(data)
print('tokens',len(ids),'sha256',hashlib.sha256(data).hexdigest())
