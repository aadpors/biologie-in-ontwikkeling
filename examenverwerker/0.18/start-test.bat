@echo off
setlocal

REM ================================================================
REM Start the 0.18 test copy with its own database and exam files.
REM
REM This launcher deliberately sets EXAMENVERWERKER_DATA to a directory
REM inside this version folder. The normal shared data root is not used.
REM The separate test-data directory is ignored by Git and can be safely
REM populated with disposable test imports.
REM
REM start.bat handles Python 3.12, the virtual environment, dependencies,
REM the local web server and browser launch. Its environment inherits the
REM data override set below.
REM ================================================================

set "EXAMENVERWERKER_DATA=%~dp0test-data"
call "%~dp0start.bat"

endlocal
