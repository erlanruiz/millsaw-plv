@echo off
REM ===========================================================================
REM Mill Saw FTP server - Windows 7/8/10/11 installer.
REM
REM Copy the ENTIRE saw_listener\ folder to the saw PC, then right-click
REM this .bat and choose "Run as administrator".
REM
REM This installer:
REM   1. Verifies Python is installed
REM   2. Verifies mill_saw_ftp.py is alongside this .bat
REM   3. pip-installs pyftpdlib
REM   4. Copies mill_saw_ftp.py + writes ftp_server.ini in C:\MillSawFTP
REM   5. Creates C:\iLENIA\Cn\Troptim\PLV
REM   6. Registers HKCU Run-key so it auto-starts at every user login
REM   7. Opens TCP ports 2121 and 50000-50050 in Windows Firewall
REM   8. Starts the FTP server now
REM ===========================================================================

setlocal EnableDelayedExpansion

set "INSTALL_DIR=C:\MillSawFTP"
set "PORT=2121"
set "PMIN=50000"
set "PMAX=50050"
set "RUN_NAME=MillSawFTP"

echo.
echo === Mill Saw FTP server installer ===
echo Source folder    : %~dp0
echo Install directory: %INSTALL_DIR%
echo FTP port         : %PORT%   (passive %PMIN%-%PMAX%)
echo.

REM --- 0. Pre-flight: mill_saw_ftp.py must be alongside this .bat -----------
if not exist "%~dp0mill_saw_ftp.py" (
    echo.
    echo ============================================================
    echo  ERROR: mill_saw_ftp.py was NOT found in this folder:
    echo    %~dp0
    echo.
    echo  You must copy the ENTIRE "saw_listener" folder to this PC,
    echo  not just install_ftp_listener.bat by itself.
    echo.
    echo  Required files, all in the same folder:
    echo     install_ftp_listener.bat   ^(this script^)
    echo     mill_saw_ftp.py            ^(the FTP server itself^)
    echo ============================================================
    echo.
    pause
    exit /b 10
)
echo [1/8] Found mill_saw_ftp.py - OK

REM --- 1. Locate Python ------------------------------------------------------
where pythonw.exe >nul 2>&1
if %ERRORLEVEL% NEQ 0 goto :no_python
for /f "delims=" %%P in ('where pythonw.exe') do (
    set "PYW=%%P"
    goto :have_pyw
)
:no_python
echo.
echo ERROR: pythonw.exe not found on PATH.
echo Install Python 3.8 (Windows 7) or 3.10+ (newer Windows) from
echo https://www.python.org/downloads/ and tick "Add Python to PATH".
echo.
pause
exit /b 1

:have_pyw
for /f "delims=" %%P in ('where python.exe') do (
    set "PY=%%P"
    goto :have_py
)
:have_py
echo [2/8] Python found    - !PY!
echo                       - !PYW!

REM --- 2. Install pyftpdlib --------------------------------------------------
echo.
echo [3/8] Installing pyftpdlib (one-time, ~30 sec)...
"!PY!" -m pip install --upgrade pyftpdlib
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: pyftpdlib install failed.
    echo Check your network/proxy and try again.
    pause
    exit /b 2
)

REM --- 3. Copy listener + write default config -------------------------------
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
copy /Y "%~dp0mill_saw_ftp.py" "%INSTALL_DIR%\mill_saw_ftp.py"
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: could not copy mill_saw_ftp.py to %INSTALL_DIR%
    pause
    exit /b 4
)
echo [4/8] Copied mill_saw_ftp.py to %INSTALL_DIR%

if not exist "%INSTALL_DIR%\ftp_server.ini" (
    > "%INSTALL_DIR%\ftp_server.ini" (
        echo [server]
        echo port = %PORT%
        echo bind = 0.0.0.0
        echo passive_ports_min = %PMIN%
        echo passive_ports_max = %PMAX%
        echo.
        echo [storage]
        echo drop_folder = C:\iLENIA\Cn\Troptim\PLV
        echo.
        echo [user]
        echo username = millsaw
        echo password = changeme
        echo.
        echo [security]
        echo ; Empty = allow any source IP. Edit to restrict.
        echo allowed_ips =
        echo.
        echo [logging]
        echo max_size_kb = 1024
        echo backups = 3
    )
    echo [5/8] Wrote default ftp_server.ini
) else (
    echo [5/8] Existing ftp_server.ini found - keeping it
)

REM --- 4. Drop folder --------------------------------------------------------
if not exist "C:\iLENIA\Cn\Troptim\PLV" mkdir "C:\iLENIA\Cn\Troptim\PLV"
echo [6/8] Drop folder ready: C:\iLENIA\Cn\Troptim\PLV

REM --- 5. Auto-start at login -----------------------------------------------
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" ^
    /v "%RUN_NAME%" ^
    /t REG_SZ ^
    /d "\"!PYW!\" \"%INSTALL_DIR%\mill_saw_ftp.py\"" ^
    /f >nul
echo [7/8] Registered auto-start at user login

REM --- 6. Firewall rules (need admin) ---------------------------------------
netsh advfirewall firewall delete rule name="MillSaw FTP control" >nul 2>&1
netsh advfirewall firewall delete rule name="MillSaw FTP passive" >nul 2>&1
netsh advfirewall firewall add rule name="MillSaw FTP control" ^
    dir=in action=allow protocol=TCP localport=%PORT% >nul
set "FW_CTRL=%ERRORLEVEL%"
netsh advfirewall firewall add rule name="MillSaw FTP passive" ^
    dir=in action=allow protocol=TCP localport=%PMIN%-%PMAX% >nul
set "FW_PASS=%ERRORLEVEL%"
if not "%FW_CTRL%"=="0" goto :fw_warn
if not "%FW_PASS%"=="0" goto :fw_warn
echo [8/8] Firewall rules added: TCP %PORT% and %PMIN%-%PMAX%
goto :start_now
:fw_warn
echo [8/8] WARNING: Firewall rules NOT added.
echo       Right-click this script and "Run as administrator" to add them,
echo       OR open ports %PORT%/TCP and %PMIN%-%PMAX%/TCP manually.

:start_now
echo.
echo Starting the FTP server now (background)...
start "" "!PYW!" "%INSTALL_DIR%\mill_saw_ftp.py"

echo.
echo =====================================================================
echo  Install complete.
echo =====================================================================
echo  Will auto-start at every user login.
echo.
echo  IMPORTANT NEXT STEPS:
echo    1. Edit  %INSTALL_DIR%\ftp_server.ini  - change the password.
echo    2. (Optional) fill in [security] allowed_ips with your IT IP.
echo    3. Log out / log back in to apply password change, OR kill
echo       pythonw.exe in Task Manager and re-run mill_saw_ftp.py.
echo.
echo  Logs : %INSTALL_DIR%\ftp_server.log
echo  Drop : C:\iLENIA\Cn\Troptim\PLV
echo =====================================================================
echo.
pause
endlocal
