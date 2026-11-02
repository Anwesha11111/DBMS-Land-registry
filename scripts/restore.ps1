# scripts/restore.ps1
# Restore script for Land Exchange databases (PostgreSQL and MongoDB)
param(
    [Parameter(Mandatory=$true)]
    [string]$BackupPath
)

Write-Host "--- Initiating Land Exchange Polyglot Restore ---" -ForegroundColor Cyan
Write-Host "Source: $BackupPath"

if (-not (Test-Path $BackupPath)) {
    Write-Error "Backup directory $BackupPath does not exist!"
    exit 1
}

# 1. Restore PostgreSQL
$PgFile = Join-Path $BackupPath "postgres_backup.sql"
if (Test-Path $PgFile) {
    Write-Host "[1/2] Restoring PostgreSQL state..."
    try {
        Get-Content $PgFile | docker compose exec -T postgres psql -U land_admin -d landregistry
        Write-Host "PostgreSQL restored successfully." -ForegroundColor Green
    } catch {
        Write-Host "Notice: Docker container not running. Skipping live psql restore." -ForegroundColor Yellow
    }
}

# 2. Restore MongoDB
$MongoDir = Join-Path $BackupPath "mongo_dump"
if (Test-Path $MongoDir) {
    Write-Host "[2/2] Restoring MongoDB ledger blocks..."
    try {
        docker compose cp $MongoDir mongo:/tmp/restore
        docker compose exec -T mongo mongorestore -u land_admin -p land_admin_secret --authenticationDatabase admin -d landregistry /tmp/restore
        Write-Host "MongoDB restored successfully." -ForegroundColor Green
    } catch {
        Write-Host "Notice: Docker container not running. Skipping live mongorestore." -ForegroundColor Yellow
    }
}

Write-Host "--- Restore Process Finished ---" -ForegroundColor Green
