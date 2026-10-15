# ============================================================
# EarthScape Climate - Safe Restart Helper
# Kills ANY old server process still holding port 5000, then
# starts the app with the latest code.
#
# Usage (from the project folder):
#     powershell -ExecutionPolicy Bypass -File .\restart_server.ps1
# or right-click -> Run with PowerShell.
# ============================================================

Write-Host ""
Write-Host "Checking for old server processes on port 5000..." -ForegroundColor Cyan

$connections = Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue
if ($connections) {
    foreach ($conn in $connections) {
        $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        Write-Host ("  Killing old process: {0} (PID {1})" -f $proc.ProcessName, $conn.OwningProcess) -ForegroundColor Yellow
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
    Write-Host "Old server process(es) stopped." -ForegroundColor Green
} else {
    Write-Host "  Port 5000 is free - no old server running." -ForegroundColor Green
}

Write-Host ""
Write-Host "Starting EarthScape Climate with the LATEST code..." -ForegroundColor Cyan
Write-Host "You should see: 'Jinja num filter registered: True'" -ForegroundColor DarkGray
Write-Host "Press Ctrl+C in this window to stop the server." -ForegroundColor DarkGray
Write-Host ""

python app.py
