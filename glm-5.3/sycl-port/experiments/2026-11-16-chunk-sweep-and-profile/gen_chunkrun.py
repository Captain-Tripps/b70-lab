E = '<work>/experiments/claude-glm-l12-20261115'.replace('/', chr(92))
BS = chr(92)
# warm-up read first (JIT for new batch shapes), then mirrored order
sizes = [1536, 2048, 3072, 4096]
L = ['@echo off']
L.append('powershell.exe -NoProfile -ExecutionPolicy Bypass -File %s%sab_chunk.ps1 -Case code -Prefill 1536 -Tag warm' % (E, BS))
for c in ('long115k', 'long32k', 'code'):
    for rnd in ('r1', 'r2'):
        seq = sizes if rnd == 'r1' else sizes[::-1]
        for p in seq:
            L.append('powershell.exe -NoProfile -ExecutionPolicy Bypass -File %s%sab_chunk.ps1 -Case %s -Prefill %d -Tag p%d-%s'
                     % (E, BS, c, p, p, rnd))
L.append('echo CHUNK_RUN_DONE')
open('chunkrun.cmd', 'w', newline='\r\n').write('\n'.join(L) + '\n')
