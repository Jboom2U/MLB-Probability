@echo off
cd /d "%~dp0"
echo Running MLB Probability Board (--sample, free preview)...
echo.

where python >nul 2>nul
if %errorlevel%==0 (
    python mlb_odds_board.py --sample
    goto :done
)

where py >nul 2>nul
if %errorlevel%==0 (
    py mlb_odds_board.py --sample
    goto :done
)

echo ERROR: Could not find "python" or "py" on PATH.
echo Install Python from https://python.org and check "Add python.exe to PATH"
echo during setup, then try again.

:done
echo.
echo Press any key to close this window.
pause >nul
