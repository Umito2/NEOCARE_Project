# Download only official Ollama assets and verify the pinned archive before running it.
param([string]$Model = 'qwen3.5:4b')
. (Join-Path $PSScriptRoot 'local-ai.ps1')
if ($Model -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*(?::[A-Za-z0-9][A-Za-z0-9._-]*)?$' -or $Model.Length -gt 128 -or $Model -match '(?i)cloud') {
    throw 'Choose a locally downloadable model, for example qwen3.5:4b.'
}
$env:OLLAMA_MODEL = $Model
$version = '0.40.11'
$expectedHash = 'bda4a493ba8a7c24d57263cd843cd68cee84f44aed4299eeed532acad7eda12a'
$archive = Join-Path $NeocareAiRoot 'ollama-windows-amd64.zip'
$installedVersionFile = Join-Path $NeocareAiRoot 'runtime-version.txt'
New-Item -ItemType Directory -Path $NeocareAiRoot -Force | Out-Null
if (Test-Path -LiteralPath $installedVersionFile) {
    if ((Get-Content -LiteralPath $installedVersionFile -Raw).Trim() -ne $version) {
        throw 'A different runtime version is already installed. Review its version before replacing it.'
    }
}
if (-not (Test-Path -LiteralPath $NeocareOllamaExe) -or -not (Test-Path -LiteralPath $installedVersionFile)) {
    $archiveVerified = (Test-Path -LiteralPath $archive) -and ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -eq $expectedHash)
    if (-not $archiveVerified) {
        Write-Host "Downloading Ollama $version (about 1.6 GB)..."
        & curl.exe --fail --location --retry 3 --connect-timeout 30 --speed-time 60 --speed-limit 1024 --continue-at - --output $archive "https://github.com/ollama/ollama/releases/download/v$version/ollama-windows-amd64.zip"
        if ($LASTEXITCODE -ne 0) { throw 'Ollama download failed. Run this script again to resume.' }
    }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) {
        throw 'The Ollama archive checksum is incorrect. Delete .local-ai/ollama-windows-amd64.zip and retry.'
    }
    Write-Host 'Verified archive. Extracting the local runtime...'
    Expand-Archive -LiteralPath $archive -DestinationPath (Join-Path $NeocareAiRoot 'bin') -Force
    Set-Content -LiteralPath $installedVersionFile -Value $version
    # Only this exact verified download is removed; the runtime and models remain.
    Remove-Item -LiteralPath $archive
}
Start-NeocareOllama
Write-Host "Downloading local model $Model (qwen3.5:4b is about 4 GB)..."
for ($attempt = 1; $attempt -le 3; $attempt++) {
    & $NeocareOllamaExe pull $Model
    if ($LASTEXITCODE -eq 0) { break }
    if ($attempt -eq 3) { throw 'Model download failed. Run this script again to resume.' }
    Write-Host 'Model download interrupted. Retrying from the saved progress...'
    Start-Sleep -Seconds 2
}
Write-Host 'Local AI is ready. Start the app with start-neocare.ps1.'
