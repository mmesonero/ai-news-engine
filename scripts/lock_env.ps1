# Lock .env so only the current Windows user can read it.
# Run once, after creating .env. Re-run if you change Windows users.

$envFile = Join-Path $PSScriptRoot "..\.env"
if (-not (Test-Path $envFile)) {
    Write-Host ".env not found at $envFile" -ForegroundColor Red
    Write-Host "Create it first:  copy .env.example .env" -ForegroundColor Yellow
    exit 1
}

Write-Host "Locking permissions on .env ..." -ForegroundColor Cyan
icacls $envFile /inheritance:r /grant:r "$($env:USERNAME):F" | Out-Null
Write-Host "Done. Only $($env:USERNAME) can read .env now." -ForegroundColor Green
icacls $envFile
