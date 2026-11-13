$ErrorActionPreference = 'Stop'
$root = 'D:\maya-sycl\experiments\codex-glm-turn-trace-20261113'
$live = 'D:\maya-sycl\maya'
$py = 'D:\AI\Training\zeus-lora\.venv\Scripts\python.exe'
$overlay = Join-Path $root 'overlay'
if (Test-Path $overlay) { throw 'overlay exists' }
New-Item -ItemType Directory -Path $overlay | Out-Null
Copy-Item (Join-Path $live 'VERSION') $overlay
Copy-Item (Join-Path $live 'serve') $overlay -Recurse
Copy-Item (Join-Path $live 'tools') $overlay -Recurse
Get-ChildItem $overlay -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
& $py (Join-Path $root 'patch_trace.py') (Join-Path $overlay 'serve\server.py')
if ($LASTEXITCODE -ne 0) { throw 'patch failed' }
& $py -m py_compile (Join-Path $overlay 'serve\server.py')
if ($LASTEXITCODE -ne 0) { throw 'compile failed' }
"live server  " + (Get-FileHash (Join-Path $live 'serve\server.py')).Hash
"overlay      " + (Get-FileHash (Join-Path $overlay 'serve\server.py')).Hash
