@echo off
REM ==========================================================================
REM  ViMento sync - Windows entry point
REM
REM  Double-click this file, or run:  sync.bat [status^|pull^|push] [--yes]
REM
REM  Everything runs through WSL on purpose. The SSH key for the VPS lives in
REM  the WSL home directory (~/.ssh), not the Windows one - running this from
REM  cmd.exe directly gives "Permission denied (publickey)".
REM ==========================================================================

setlocal
set DISTRO=Ubuntu-24.04
set REPO=/home/idona/MoStar/_apps/ViMento

set CMD=%1
if "%CMD%"=="" set CMD=status

echo.
echo  ViMento sync : %CMD% %2
echo.

wsl.exe -d %DISTRO% -- bash -c "cd %REPO% && chmod +x scripts/sync-vps.sh && ./scripts/sync-vps.sh %CMD% %2"

if errorlevel 1 (
  echo.
  echo  Sync failed. Common causes:
  echo    - WSL distro not running        : wsl -d %DISTRO% -- true
  echo    - SSH key missing in WSL        : wsl -d %DISTRO% -- ls ~/.ssh
  echo    - Repo path moved               : edit REPO at the top of this file
  echo.
)

echo.
echo  Reminder: commit from Windows git, never from inside WSL.
echo  They disagree on core.autocrlf and WSL will produce a ~21,000 line diff.
echo.
pause
endlocal
