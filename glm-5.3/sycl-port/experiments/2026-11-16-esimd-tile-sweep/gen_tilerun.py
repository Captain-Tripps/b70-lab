E = '<work>/experiments/claude-glm-l12-20261115'.replace('/', chr(92))
BS = chr(92)
vs = [('tree4', 'live'), ('tile-m32-n64', 'm32n64'), ('tile-m16-n64', 'm16n64'), ('tile-m32-n48', 'm32n48'),
      ('tile-m16-n32', 'm16n32'), ('tile-m32-n64s', 'm32n64s'), ('tile-m16-n64s', 'm16n64s'), ('tree4', 'liveb')]
L = ['@echo off']
for c in ('long115k', 'long32k'):
    for t, g in vs:
        x = E + BS + t + BS + 'link' + BS + 'generate.exe'
        L.append('if exist %s powershell.exe -NoProfile -ExecutionPolicy Bypass -File %s%sab_tile.ps1 -Case %s -Exe %s -Tag %s'
                 % (x, E, BS, c, x, g))
L.append('echo TILE_RUN_DONE')
open('tilerun.cmd', 'w', newline='\r\n').write('\n'.join(L) + '\n')
