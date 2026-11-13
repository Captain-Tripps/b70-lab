import subprocess, sys, time
root = r'D:\maya-sycl\experiments\codex-glm-ckpt-keep-20261113'
for arm in ('off', 'on'):
    print('ARM', arm, time.strftime('%H:%M:%S'), flush=True)
    r = subprocess.run([sys.executable, root + r'\run_screen.py', arm, arm])
    print('ARM_EXIT', arm, r.returncode, flush=True)
    if r.returncode:
        sys.exit(r.returncode)
    time.sleep(20)
print('BOTH_DONE', time.strftime('%H:%M:%S'), flush=True)
