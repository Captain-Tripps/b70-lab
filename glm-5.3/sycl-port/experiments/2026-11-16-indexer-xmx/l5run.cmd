@echo off
set P=powershell.exe -NoProfile -ExecutionPolicy Bypass -File <work>\experiments\claude-glm-l12-20261115\ab_dsa.ps1
set C=<work>\experiments\claude-glm-l12-20261115\tree4\link\generate.exe
%P% -Case long32k -Exe %C% -Tag c0 -KL
%P% -Case long32k -Exe %C% -Tag c1 -Xmx 1 -KL
%P% -Case code -Exe %C% -Tag c0 -KL
%P% -Case code -Exe %C% -Tag c1 -Xmx 1 -KL
%P% -Case long115k -Exe %C% -Tag c0 -KL
%P% -Case long115k -Exe %C% -Tag c1 -Xmx 1 -KL
%P% -Case long115k -Exe %C% -Tag c1b -Xmx 1
%P% -Case long115k -Exe %C% -Tag c0b
%P% -Case long32k -Exe %C% -Tag c1b -Xmx 1
%P% -Case long32k -Exe %C% -Tag c0b
<venv python> <work>\experiments\claude-glm-l12-20261115\nll_l5.py l5 c0,c1
echo L5_RUN_DONE
