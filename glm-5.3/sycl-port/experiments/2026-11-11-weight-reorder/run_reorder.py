import os,subprocess,sys,pathlib,numpy as np
root=pathlib.Path(r'<work>\experiments\codex-iq2-reorder-20261111'); exe=root/'tree/link/xmx_iq2_reorder.exe'
preflight=r'''$r=Invoke-RestMethod http://100.89.126.50:8080/running -TimeoutSec 5;if (@($r.running).Count -gt 0) {throw 'swap in use'};if (Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(generate|llama-server)\.exe$' }) {throw 'GPU model in use'};$g=@((Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage').CounterSamples | Where-Object { $_.InstanceName -notmatch '0x000159ed' } | ForEach-Object {$_.CookedValue/1GB});if ($g.Count -lt 4 -or ($g | Measure-Object -Maximum).Maximum -gt 1.2) {throw 'GPU not clear'}'''
base={k:v for k,v in os.environ.items() if not k.upper().startswith(('MAYA_','STRATA_','SYCL_','ZE_','ZES_','UR_','ONEAPI_DEVICE_SELECTOR'))}
base['ONEAPI_DEVICE_SELECTOR']='level_zero:0';base['ZES_ENABLE_SYSMAN']='1'
base['PATH']=r'<work>\rt-live;C:\Windows\System32;C:\Windows;C:\Program Files (x86)\Intel\oneAPI\mkl\2026.0\bin;C:\Program Files (x86)\Intel\oneAPI\compiler\2026.0\bin'
for i,kind in enumerate(('original','reordered','reordered','original')):
 subprocess.run(['powershell.exe','-NoProfile','-Command',preflight],check=True,timeout=60)
 env=base.copy()
 if kind=='reordered':env['MAYA_FG_REORDER_IQ2']='1'
 with (root/f'{i}-{kind}.log').open('wb') as out:
  run=subprocess.run([str(exe),str(root/f'{i}-{kind}.bin')],env=env,stdout=out,stderr=subprocess.STDOUT,timeout=300)
 if run.returncode:sys.exit(f'{kind} failed with {run.returncode}')
 print(i,kind,'complete',flush=True)
a=np.fromfile(root/'0-original.bin',dtype=np.float32)
for i,kind in ((1,'reordered'),(2,'reordered'),(3,'original')):
 b=np.fromfile(root/f'{i}-{kind}.bin',dtype=np.float32)
 if a.shape!=b.shape or not np.isfinite(a).all() or not np.isfinite(b).all():sys.exit('shape/nonfinite')
 print('compare',i,kind,'values',a.size,'bit_differences',np.count_nonzero(a.view(np.uint32)!=b.view(np.uint32)),'max_abs',np.max(np.abs(a-b)),flush=True)
