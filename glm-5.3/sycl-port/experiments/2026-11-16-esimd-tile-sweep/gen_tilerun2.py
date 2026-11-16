E = '<work>/experiments/claude-glm-l12-20261115'.replace('/', chr(92))
BS = chr(92)
order = [('tile-m32-n64', 'm32n64'), ('tree4', 'live'), ('tile-m32-n48', 'm32n48')]
L = ['@echo off']
for c in ('long115k', 'long32k', 'code'):
    for rnd in ('r2', 'r3'):
        seq = order if rnd == 'r2' else order[::-1]
        for t, g in seq:
            x = E + BS + t + BS + 'link' + BS + 'generate.exe'
            L.append('powershell.exe -NoProfile -ExecutionPolicy Bypass -File %s%sab_tile.ps1 -Case %s -Exe %s -Tag %s-%s'
                     % (E, BS, c, x, g, rnd))
L.append('echo TILE_RUN2_DONE')
open('tilerun2.cmd', 'w', newline='\r\n').write('\n'.join(L) + '\n')
