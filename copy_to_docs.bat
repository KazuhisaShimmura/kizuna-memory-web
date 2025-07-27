@echo off

REM --- Set PowerShell execution policy for this script ---
setlocal
powershell -ExecutionPolicy Bypass -Command ""

REM --- Copy and modify index.html ---
powershell -Command "(Get-Content -Path .\src\templates\index.html -Encoding UTF8) -replace '{{ static_url }}', '' -replace '../static/images/', 'images/' | Set-Content -Path .\docs\index.html -Encoding UTF8"

REM --- Copy and modify storybook_sample.html ---
powershell -Command "(Get-Content -Path .\src\templates\storybook_sample.html -Encoding UTF8) -replace '../static/images/', 'images/' | Set-Content -Path .\docs\storybook_sample.html -Encoding UTF8"

REM --- Copy other HTML files ---
copy .\src\templates\test.html .\docs\test.html
copy .\src\templates\test2.html .\docs\test2.html

REM --- Copy image folder ---
xcopy .\src\static\images .\docs\images /E /I /Y

echo.
echo =====================================
echo  Copied files from src to docs.
echo =====================================