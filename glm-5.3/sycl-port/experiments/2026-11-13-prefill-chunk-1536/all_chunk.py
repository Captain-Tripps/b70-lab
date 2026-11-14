import os
WORK = os.environ["MAYA_WORK"]   # the engine checkout
import subprocess, sys, time
root = WORK + r'\experiments\claude-glm-chunk-screen-20261113'
arms = [('p768-a', '768'), ('p1024', '1024'), ('p1536', '1536'), ('p2048', '2048'), ('p768-b', '768')]
for arm, chunk in arms:
    print('ARM', arm, time.strftime('%H:%M:%S'), flush=True)
    r = subprocess.run([sys.executable, root + r'\screen_chunk.py', arm, 'default', 'default', chunk])
    print('ARM_EXIT', arm, r.returncode, time.strftime('%H:%M:%S'), flush=True)
    time.sleep(20)
print('ALL_DONE', time.strftime('%H:%M:%S'), flush=True)
