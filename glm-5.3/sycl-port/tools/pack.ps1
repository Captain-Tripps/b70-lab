$src = "<models>\GLM-5.3-Flash-Maya-GGUF\Maya-M"
$d = "<work>\glm-m"; New-Item -ItemType Directory -Force $d | Out-Null
Get-ChildItem $src -Filter *.gguf | ForEach-Object { $t = Join-Path $d $_.Name; if (-not (Test-Path $t)) { cmd /c mklink /H "$t" "$($_.FullName)" | Out-Null } }
Get-ChildItem $d | Select Name,Length | ft -auto | Out-String
$env:STRATA_GGUF_PY = "<llama.cpp-sycl-fork>\gguf-py"
Set-Location <work>\maya
& <work>\venv\Scripts\python.exe tools\iq_pack.py --gguf "$d\GLM-5.3-Flash-Maya-M-IQ2_S-00001-of-00003.gguf" --out "$d\pack" --compat-bf16 *> <work>\pack.log
"PACK EXIT $LASTEXITCODE"
Get-Content <work>\pack.log -Tail 12
