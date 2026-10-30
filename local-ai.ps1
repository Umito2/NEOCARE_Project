# Shared helpers for the local, project-owned Ollama runtime.
$ErrorActionPreference = 'Stop'
$NeocareRoot = $PSScriptRoot
$NeocareAiRoot = Join-Path $NeocareRoot '.local-ai'
$NeocareOllamaExe = Join-Path $NeocareAiRoot 'bin\ollama.exe'

function Start-NeocareOllama {
    if (-not (Test-Path -LiteralPath $NeocareOllamaExe)) {
        throw 'Local AI is not installed. Run setup-local-ai.ps1 first.'
    }
    $env:OLLAMA_HOST = '127.0.0.1:11434'
    $env:OLLAMA_BASE_URL = 'http://127.0.0.1:11434'
    $env:OLLAMA_NO_CLOUD = '1'
    $env:OLLAMA_MODELS = Join-Path $NeocareAiRoot 'models'
    $env:OLLAMA_NUM_PARALLEL = '1'
    $env:OLLAMA_MAX_LOADED_MODELS = '1'
    if (-not $env:OLLAMA_MODEL) { $env:OLLAMA_MODEL = 'qwen3.5:4b' }
    $logDir = Join-Path $NeocareAiRoot 'logs'
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null

    $alreadyRunning = $false
    try {
        $null = Invoke-RestMethod -Uri "$env:OLLAMA_BASE_URL/api/version" -TimeoutSec 3
        $alreadyRunning = $true
    } catch { }
    if ($alreadyRunning) {
        $pidFile = Join-Path $NeocareAiRoot 'ollama.pid'
        if (-not (Test-Path -LiteralPath $pidFile)) {
            throw 'Port 11434 is already in use by another Ollama instance. Quit it and retry so NEOCARE can start its local-only runtime.'
        }
        $ownedProcess = Get-Process -Id ([int](Get-Content -LiteralPath $pidFile)) -ErrorAction SilentlyContinue
        if (-not $ownedProcess -or $ownedProcess.Path -ne $NeocareOllamaExe) {
            throw 'Another service is using port 11434. Stop that service before starting NEOCARE local AI.'
        }
        $listener = Get-NetTCPConnection -State Listen -LocalPort 11434 -ErrorAction Stop
        if ($ownedProcess.Id -notin $listener.OwningProcess) {
            throw 'Port 11434 does not belong to the NEOCARE runtime. Stop the other service before retrying.'
        }
        return
    }
    $serverProcess = Start-Process -FilePath $NeocareOllamaExe -ArgumentList 'serve' -WorkingDirectory $NeocareRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir 'ollama.stdout.log') -RedirectStandardError (Join-Path $logDir 'ollama.stderr.log')
    Set-Content -LiteralPath (Join-Path $NeocareAiRoot 'ollama.pid') -Value $serverProcess.Id
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if ($serverProcess.HasExited) { throw 'Ollama did not start. Check .local-ai/logs/ollama.stderr.log.' }
        try {
            $null = Invoke-RestMethod -Uri "$env:OLLAMA_BASE_URL/api/version" -TimeoutSec 2
            return
        } catch { Start-Sleep -Milliseconds 500 }
    }
    throw 'Ollama took too long to start. Check .local-ai/logs/ollama.stderr.log.'
}
