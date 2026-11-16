import os, subprocess, sys, time
root = os.environ['MAYA_WORK'] + r'\experiments\claude-glm-l12-20261115'
arms = [('live-a', 'live', 'default'), ('esimd-a', 'cand', '1'), ('joint', 'cand', '0'), ('esimd-b', 'cand', '1'), ('live-b', 'live', 'default')]
for arm, which, esimd in arms:
    print('ARM', arm, time.strftime('%H:%M:%S'), flush=True)
    r = subprocess.run([sys.executable, root + r'\screen_l12.py', arm, which, esimd])
    print('ARM_EXIT', arm, r.returncode, time.strftime('%H:%M:%S'), flush=True)
    if r.returncode:
        print('STOPPED', flush=True); sys.exit(1)
    time.sleep(20)
print('ALL_DONE', time.strftime('%H:%M:%S'), flush=True)
