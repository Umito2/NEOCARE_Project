param([string]$PythonPath = '', [switch]$Background)
. (Join-Path $PSScriptRoot 'local-ai.ps1')
Start-NeocareOllama
$availableModels = Invoke-RestMethod -Uri "$env:OLLAMA_BASE_URL/api/tags" -TimeoutSec 5
if ($env:OLLAMA_MODEL -notin $availableModels.models.name) {
    throw "Model $env:OLLAMA_MODEL is missing. Run setup-local-ai.ps1 first."
}
if (-not $PythonPath) {
    $candidates = @(
        (Join-Path $NeocareRoot '.venv\Scripts\python.exe'),
        (Join-Path $NeocareRoot 'venv\Scripts\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Python\pythoncore-3.14-64\python.exe')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { $PythonPath = $candidate; break }
    }
    if (-not $PythonPath) {
        $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($pythonCommand) { $PythonPath = $pythonCommand.Source }
    }
}
if (-not $PythonPath -or -not (Test-Path -LiteralPath $PythonPath)) {
    throw 'Python was not found. Run start-neocare.ps1 -PythonPath C:\path\to\python.exe.'
}
if ($Background) {
    $windowlessPython = Join-Path (Split-Path -Parent $PythonPath) 'pythonw.exe'
    if (Test-Path -LiteralPath $windowlessPython) { $PythonPath = $windowlessPython }
    $logDir = Join-Path $NeocareAiRoot 'logs'
    $pidFile = Join-Path $NeocareAiRoot 'neocare.pid'
    if (Test-Path -LiteralPath $pidFile) {
        $existingProcess = Get-Process -Id ([int](Get-Content -LiteralPath $pidFile)) -ErrorAction SilentlyContinue
        if ($existingProcess -and $existingProcess.Path -eq $PythonPath) {
            $listener = Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue
            if ($existingProcess.Id -in $listener.OwningProcess) {
                $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 5
                if ($health.status -eq 'ok') {
                    Write-Host 'NEOCARE is already running: http://127.0.0.1:8000/'
                    return
                }
            }
        }
    }
    $webProcess = Start-Process -FilePath $PythonPath -ArgumentList @('-m', 'uvicorn', 'api:app', '--host', '127.0.0.1', '--port', '8000', '--no-access-log') -WorkingDirectory $NeocareRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir 'neocare.stdout.log') -RedirectStandardError (Join-Path $logDir 'neocare.stderr.log')
    Set-Content -LiteralPath $pidFile -Value $webProcess.Id
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        $webProcess.Refresh()
        if ($webProcess.HasExited) { throw 'NEOCARE did not start. Check .local-ai/logs/neocare.stderr.log.' }
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 2
            $listener = Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction Stop
            if ($health.status -eq 'ok' -and $webProcess.Id -in $listener.OwningProcess) {
                Write-Host 'NEOCARE is running in the background: http://127.0.0.1:8000/'
                Write-Host 'You can close this terminal. Logs are in .local-ai/logs.'
                return
            }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    throw 'NEOCARE did not become ready. Check .local-ai/logs/neocare.stderr.log.'
}
Write-Host 'NEOCARE: http://127.0.0.1:8000 - keep this terminal open. Press Ctrl+C to stop the web app.'
Write-Host "Local AI: $env:OLLAMA_MODEL. Ollama remains running in the background for later use."
Push-Location -LiteralPath $NeocareRoot
try {
    & $PythonPath -m uvicorn api:app --host 127.0.0.1 --port 8000 --no-access-log
} finally { Pop-Location }
