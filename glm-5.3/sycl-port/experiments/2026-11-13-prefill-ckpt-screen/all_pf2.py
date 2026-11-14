import os, subprocess, sys, time
root = os.path.dirname(os.path.abspath(__file__))
arms = [('c0-r2', '0', 'default'), ('s13-24-35', 'default', '13,24,35'), ('s14-24-35', 'default', '14,24,35'),
        ('c16k-b', 'default', 'default')]
for arm, ckpt, split in arms:
    print('ARM', arm, time.strftime('%H:%M:%S'), flush=True)
    r = subprocess.run([sys.executable, root + r'\screen_pf.py', arm, ckpt, split])
    print('ARM_EXIT', arm, r.returncode, time.strftime('%H:%M:%S'), flush=True)
    time.sleep(20)
print('ALL_DONE', time.strftime('%H:%M:%S'), flush=True)
