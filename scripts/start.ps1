# scripts/start.ps1: Launch Land Exchange environment on Windows
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Starting Land Exchange Local Services..." -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

# Check if Docker is available
try {
    docker compose up -d
    Write-Host "Docker containers (PostGIS 16 + MongoDB 7) started." -ForegroundColor Green
} catch {
    Write-Host "Notice: Docker not available; fallback to mock database if needed." -ForegroundColor Yellow
}

# Start Flask Backend
Write-Host "Starting Flask consensus engine on port 5000..." -ForegroundColor Green
python backend/app.py
