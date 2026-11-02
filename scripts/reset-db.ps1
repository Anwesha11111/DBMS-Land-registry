# scripts/reset-db.ps1: Reset databases and reseed
Write-Host "Resetting Land Exchange databases..." -ForegroundColor Yellow

try {
    docker compose down -v
    docker compose up -d
    Start-Sleep -Seconds 6
    python scripts/seed.py
    Write-Host "Databases reset and seeded successfully." -ForegroundColor Green
} catch {
    Write-Host "Resetting in-memory state..." -ForegroundColor Cyan
    python -c "from backend.db.mock_store import mock_db; mock_db.reset(); print('Mock DB reset.')"
    python scripts/seed.py
}
