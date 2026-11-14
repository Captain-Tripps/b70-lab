import os, subprocess, sys, time
root = os.path.dirname(os.path.abspath(__file__))
arms = [('c16k-a', 'default', 'default'), ('c32k', '32768', 'default'), ('c64k', '65536', 'default'),
        ('c0', '0', 'default'), ('s13-24-35', 'default', '13,24,35'), ('s14-24-35', 'default', '14,24,35'),
        ('c16k-b', 'default', 'default')]
for arm, ckpt, split in arms:
    print('ARM', arm, time.strftime('%H:%M:%S'), flush=True)
    r = subprocess.run([sys.executable, root + r'\screen_pf.py', arm, ckpt, split])
    print('ARM_EXIT', arm, r.returncode, time.strftime('%H:%M:%S'), flush=True)
    if r.returncode and not arm.startswith('s'):
        sys.exit(r.returncode)   # a split arm that does not fit is a result; anything else stops the screen
    time.sleep(20)
print('ALL_DONE', time.strftime('%H:%M:%S'), flush=True)
