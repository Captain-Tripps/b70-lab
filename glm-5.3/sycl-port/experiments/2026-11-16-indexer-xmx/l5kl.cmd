@echo off
set P=powershell.exe -NoProfile -ExecutionPolicy Bypass -File <work>\experiments\claude-glm-l12-20261115\ab_dsa.ps1
set C=<work>\experiments\claude-glm-l12-20261115\tree4\link\generate.exe
%P% -Case long32k -Exe %C% -Tag k0 -KL -KLN 512
%P% -Case long32k -Exe %C% -Tag k1 -Xmx 1 -KL -KLN 512
%P% -Case long115k -Exe %C% -Tag k0 -KL -KLN 512
%P% -Case long115k -Exe %C% -Tag k1 -Xmx 1 -KL -KLN 512
<venv python> <work>\experiments\claude-glm-l12-20261115\nll_l5.py 5 k0,k1 512
echo L5_KL_DONE
