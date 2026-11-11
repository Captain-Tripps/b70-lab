import json
from pathlib import Path
root=Path(r'<work>\experiments\codex-promptmemo-20261110')
c=json.loads(Path(r'<work>\experiments\codex-20261110\baseline2.json').read_text(encoding='utf8'))
c['log']=str(root/'engine.log')
(root/'server.json').write_text(json.dumps(c,indent=2),encoding='utf8')
(root/'mode.txt').write_text('0',encoding='ascii')
