"""Read-only canary monitor. Reports alerts; it does not stop or roll back a service."""
import argparse, ctypes, hashlib, json, subprocess, time, urllib.request
from pathlib import Path

class Mem(ctypes.Structure):
    _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong),('total',ctypes.c_ulonglong),('free',ctypes.c_ulonglong),('totalpage',ctypes.c_ulonglong),('freepage',ctypes.c_ulonglong),('totalvirtual',ctypes.c_ulonglong),('freevirtual',ctypes.c_ulonglong),('freeextended',ctypes.c_ulonglong)]

def free_memory():
    m=Mem();m.length=ctypes.sizeof(m)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):raise RuntimeError('cannot sample physical memory')
    return m.free

def get(url):
    with urllib.request.urlopen(url,timeout=5) as r:return json.load(r)

def gpu_snapshot():
    ps="(Get-Counter '\\GPU Adapter Memory(*)\\Dedicated Usage' -ErrorAction Stop).CounterSamples | Select-Object InstanceName,CookedValue | ConvertTo-Json -Compress"
    r=subprocess.run(['powershell.exe','-NoProfile','-Command',ps],capture_output=True,text=True,timeout=20,check=True)
    return json.loads(r.stdout) if r.stdout.strip() else []

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--proxy',required=True);p.add_argument('--model',default='glm-5.3-flash-maya-sycl')
    p.add_argument('--config',type=Path,required=True);p.add_argument('--expected-config-sha256',required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--minutes',type=int,default=70)
    args=p.parse_args()
    if not 1<=args.minutes<=150:p.error('--minutes must be 1–150')
    root=args.proxy.rstrip('/');end=time.monotonic()+args.minutes*60;last_gpu=0;last_events=0
    start_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
    with args.output.open('x',encoding='utf8') as log:
        while time.monotonic()<end:
            t=time.time();alerts=[];row={'time':t}
            try:
                row['host_available_bytes']=free_memory()
                if row['host_available_bytes']<16*1024**3:alerts.append('host available memory below 16 GiB')
                row['config_sha256']=hashlib.sha256(args.config.read_bytes()).hexdigest()
                if row['config_sha256'].lower()!=args.expected_config_sha256.lower():alerts.append('live config hash changed')
                running=get(root+'/running').get('running',[])
                row['models']=[{'model':x.get('model'),'state':x.get('state')} for x in running]
                if len(running)!=1 or running[0].get('model')!=args.model or running[0].get('state')!='ready':alerts.append('expected GLM is not sole ready proxy model')
            except Exception as e:alerts.append('basic monitor failed: '+type(e).__name__)
            now=time.monotonic()
            if now-last_gpu>=30:
                try:row['gpu_dedicated_bytes']=gpu_snapshot()
                except Exception as e:row['gpu_sample_error']=type(e).__name__;alerts.append('GPU memory sampling failed')
                last_gpu=now
            if now-last_events>=30:
                ps=("$start=[DateTime]::Parse('"+start_utc+"').ToLocalTime(); "
                    "$e=Get-WinEvent -FilterHashtable @{LogName='Application';Id=1000;StartTime=$start} -ErrorAction SilentlyContinue | "
                    "Where-Object { $_.Message -match 'Faulting application name: generate\\.exe' } | Select-Object -First 3 TimeCreated,Id,Message; "
                    "$e | ConvertTo-Json -Compress")
                try:
                    r=subprocess.run(['powershell.exe','-NoProfile','-Command',ps],capture_output=True,text=True,timeout=20,check=True)
                    events=json.loads(r.stdout) if r.stdout.strip() else []
                    if isinstance(events,dict):events=[events]
                    if events:row['engine_crash_events']=events;alerts.append('new generate.exe application crash event')
                except Exception as e:row['event_sample_error']=type(e).__name__;alerts.append('Windows event sampling failed')
                last_events=now
            row['alerts']=alerts;log.write(json.dumps(row,ensure_ascii=False)+'\n');log.flush()
            if alerts:
                print('ALERT',json.dumps(alerts),flush=True);return 1
            time.sleep(2)
    print('MONITOR_COMPLETE',flush=True);return 0

if __name__=='__main__':raise SystemExit(main())
