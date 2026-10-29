#!/bin/bash
# Served --adapt-every 0 A/B on the lab Strata build: alternate the JSON config per fresh start (no llama-swap reload,
# the JSON is not watched), unload, then swap-check (load + 2 requests, then the same 2 again). Restores the default config.
cd "$(dirname "$0")"
# SWAP_URL = llama-swap base URL; ZPS = a helper that runs a PowerShell snippet on the GPU host
CFG='$env:USERPROFILE\AI\Runtimes\strata\configs\qwen38-flashnext-iq3s-200k.json'
use() {  # use default|adapt0
  if [ "$1" = adapt0 ]; then src="$CFG.adapt0-tested-slower-20261028"; else src="$CFG.pre-adapt0-20261028.bak"; fi
  $ZPS "Copy-Item \"$src\" \"$CFG\" -Force; if (Select-String -Path \"$CFG\" -Pattern 'adapt-every' -Quiet) { 'config=adapt0' } else { 'config=default' }" 2>/dev/null | grep config=
}
for run in adapt0 default adapt0 default adapt0 default; do
  use $run
  curl -s -m 60 $SWAP_URL/unload > /dev/null
  echo "== start $run $(date +%H:%M:%S)"
  timeout 900 python swap-check.py $SWAP_URL qwen3.8-flash-next-strata 2>&1 | grep -o "'predicted_per_second': [0-9.]*"
  timeout 600 python swap-check.py $SWAP_URL qwen3.8-flash-next-strata 2>&1 | grep -o "'predicted_per_second': [0-9.]*"
done
use default
curl -s -m 60 $SWAP_URL/unload > /dev/null
echo "== done, default config restored, Strata unloaded"
