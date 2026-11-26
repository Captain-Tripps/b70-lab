@echo off
rem Build and run from a oneAPI command prompt (setvars.bat), with the MSVC build tools on the path (vcvars64.bat).
icpx -fsycl -O2 -std=c++20 lballoc.cpp -o lballoc.exe || exit /b 1
icpx -fsycl -O2 -std=c++20 ctxx.cpp -o ctxx.exe || exit /b 1
set ONEAPI_DEVICE_SELECTOR=level_zero:*
echo == threads in one process, one shared context
for %%T in (1 2 4) do lballoc.exe %%T 20000 0 0 0 0
echo == threads in one process, a context each
for %%T in (1 2 4) do lballoc.exe %%T 20000 0 0 0 1
echo == 4 processes at once, 1 thread each, own GPU
start /b lballoc.exe 1 20000 0 0 1 > p1.txt
start /b lballoc.exe 1 20000 0 0 2 > p2.txt
start /b lballoc.exe 1 20000 0 0 3 > p3.txt
lballoc.exe 1 20000 0 0 0 > p0.txt
powershell -NoProfile -Command "Start-Sleep 5"
type p0.txt p1.txt p2.txt p3.txt
echo == live allocations, 1 thread
for %%K in (0 100 1000 4000) do lballoc.exe 1 3000 %%K 0 0 0
echo == which memory a kernel in a per-card context may use
ctxx.exe
