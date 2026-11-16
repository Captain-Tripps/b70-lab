@echo off
rem One-shot setup (see setup.py for the options): loads the compiler environment, then runs setup.py.
rem   VSVARS  path to vcvars64.bat (default: Visual Studio 2026 / 18 Build Tools)
rem   ONEAPI  oneAPI install root (default: C:\Program Files (x86)\Intel\oneAPI); 2026.0 compiler and MKL
rem   PYTHON  a Python 3.10+ (default: python on PATH)
if not defined VSVARS set "VSVARS=C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if not defined ONEAPI set "ONEAPI=C:\Program Files (x86)\Intel\oneAPI"
if not defined PYTHON set "PYTHON=python"
call "%VSVARS%" >nul || exit /b 1
for %%C in (tbb umf dnnl mkl dpl ocloc compiler) do (
  if exist "%ONEAPI%\%%C\latest\env\vars.bat" call "%ONEAPI%\%%C\latest\env\vars.bat" >nul 2>&1
)
"%PYTHON%" "%~dp0setup.py" %*
