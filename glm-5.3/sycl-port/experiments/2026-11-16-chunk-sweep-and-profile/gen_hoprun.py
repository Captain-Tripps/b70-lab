E = '<work>/experiments/claude-glm-l12-20261115'.replace('/', chr(92))
BS = chr(92)
LIVE = '<work>/rt-glm-esimd-iq2s-dsaxmx-tile64-20261116/generate.exe'.replace('/', chr(92))
HOP = E + BS + 'hop-probe' + BS + 'link' + BS + 'generate.exe'
runs = [('code', HOP, '', 'warm')]
for c in ('long115k', 'long32k'):
    runs += [(c, LIVE, '', 'live-r1'), (c, HOP, '', 'probe-r1'), (c, HOP, 'VEC', 'vec-r1'),
             (c, HOP, 'TIME', 'time'), (c, HOP, 'TIME,VEC', 'timevec'),
             (c, HOP, 'VEC', 'vec-r2'), (c, HOP, '', 'probe-r2'), (c, LIVE, '', 'live-r2')]
L = ['@echo off']
for c, x, h, t in runs:
    L.append('powershell.exe -NoProfile -ExecutionPolicy Bypass -File %s%sab_hop.ps1 -Case %s -Exe %s%s -Tag %s'
             % (E, BS, c, x, (' -Hop ' + h) if h else '', t))
L.append('echo HOP_RUN_DONE')
open('hoprun.cmd', 'w', newline='\r\n').write('\n'.join(L) + '\n')
