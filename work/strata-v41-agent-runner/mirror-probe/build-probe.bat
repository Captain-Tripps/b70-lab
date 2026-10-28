@echo off
call "C:\Program Files (x86)\Intel\oneAPI\setvars.bat" --force >nul 2>&1
cd /d C:\b70-work\probe
icx -fsycl -O2 mirror_probe.cpp -I"C:\Program Files\LevelZeroSDK\1.32.0\include" "C:\Program Files\LevelZeroSDK\1.32.0\lib\ze_loader.lib" psapi.lib -o mirror_probe.exe > build.log 2>&1
echo build exit %ERRORLEVEL% >> build.log
