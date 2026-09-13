# Starts backend (FastAPI/uvicorn) + frontend (vite) for local dev.
# Backend runs in the background and logs to backend.log (created if missing,
# appended to on every subsequent run). Frontend runs in the foreground.
#
# Ports are deliberately NOT 8000/5173 — those belong to another project on this
# machine. If you change them here, also update:
#   - frontend/vite.config.js  (proxy target -> backend port)
#   - backend/app/api/main.py  (CORS allow_origins -> frontend port)

$ScriptDir    = $PSScriptRoot
$BackendDir   = Join-Path $ScriptDir "backend"
$FrontendDir  = Join-Path $ScriptDir "frontend"
$LogFile      = Join-Path $ScriptDir "backend.log"
$BackendPort  = 8100
$FrontendPort = 5273
$PythonExe    = Join-Path $BackendDir "venv\Scripts\python.exe"

# Kill whatever is already listening on our ports (stale uvicorn/vite from a
# previous run) so every start.ps1 run boots clean. Targeted by port only —
# never a broad kill by process name, which would also take out unrelated
# node/python processes (e.g. an editor's MCP servers).
function Kill-Port {
    param([int]$Port)
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        $procId = $c.OwningProcess
        Write-Host "Killing stale process on port $Port (PID $procId)..."
        taskkill /F /T /PID $procId 2>$null | Out-Null
    }
}

if (-not (Test-Path $PythonExe)) {
    Write-Host "No virtualenv found at $PythonExe"
    Write-Host "Create it with:  python -m venv backend\venv"
    exit 1
}

Write-Host "Checking for stale processes on ports $BackendPort/$FrontendPort..."
Kill-Port -Port $BackendPort
Kill-Port -Port $FrontendPort

# Create backend.log if it doesn't exist yet; never truncate an existing one.
if (-not (Test-Path $LogFile)) {
    New-Item -ItemType File -Path $LogFile | Out-Null
}
Add-Content -Path $LogFile -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ==== start.ps1: launching backend ===="

Write-Host "Installing backend dependencies..."
& $PythonExe -m pip install -q -r (Join-Path $BackendDir "requirements.txt")

if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
    Write-Host "Installing frontend dependencies (first run)..."
    Push-Location $FrontendDir
    npm install
    Pop-Location
}

Write-Host "Starting backend..."
# WATCHFILES_FORCE_POLLING works around --reload's unreliable file watcher on Z:\ mapped drives.
$backendCmd = "set WATCHFILES_FORCE_POLLING=true && `"$PythonExe`" -m uvicorn app.api.main:app --reload --reload-dir app --host 0.0.0.0 --port $BackendPort >> `"$LogFile`" 2>&1"
$backendProc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $backendCmd -WorkingDirectory $BackendDir -WindowStyle Hidden -PassThru

Start-Sleep -Seconds 2
if ($backendProc.HasExited) {
    Write-Host "Backend failed to start - check $LogFile for details."
    exit 1
}

Write-Host ""
Write-Host "  Backend:  http://localhost:$BackendPort  (docs: http://localhost:$BackendPort/docs)"
Write-Host "  Frontend: http://localhost:$FrontendPort  (starting below)"
Write-Host ""
Write-Host "  Backend logs: $LogFile  (tail with: Get-Content backend.log -Wait -Tail 20)"
Write-Host "  Press Ctrl+C to stop both servers."
Write-Host ""

try {
    Push-Location $FrontendDir
    npm run dev -- --port $FrontendPort --strictPort
}
finally {
    Pop-Location
    if (-not $backendProc.HasExited) {
        Write-Host ""
        Write-Host "Stopping backend (PID $($backendProc.Id))..."
        taskkill /F /T /PID $backendProc.Id 2>$null | Out-Null
    }
}
