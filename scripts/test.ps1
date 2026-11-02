# scripts/test.ps1: Run pytest test suite
Write-Host "Running Land Exchange Pytest Suite..." -ForegroundColor Cyan
pytest tests/ -v
