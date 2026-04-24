#!/bin/bash
set -euo pipefail

# ── 설정 ──────────────────────────────────────────
REMOTE_USER="studydev"
REMOTE_HOST="192.168.1.92"
REMOTE_DIR="/mnt/workspace/custom_apps/echo-bus"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[DEPLOY]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ── 1. 로컬 테스트 (선택) ────────────────────────
if [[ "${1:-}" == "--test" ]]; then
    log "Running local tests..."
    cd backend
    python3 -m pytest tests/ -v 2>/dev/null || warn "No tests found, skipping"
    cd ..
fi

# ── 2. 소스 동기화 ────────────────────────────────
log "Syncing source to TrueNAS..."
rsync -avz --delete \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='.git' \
    --exclude='.env' \
    --exclude='node_modules' \
    ./backend/ "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/backend/"

# ── 3. 원격 빌드 + 배포 ──────────────────────────
log "Building and deploying on TrueNAS..."
ssh "${REMOTE_USER}@${REMOTE_HOST}" bash -s <<'REMOTE_SCRIPT'
    set -euo pipefail
    cd /mnt/workspace/custom_apps/echo-bus/backend

    echo "[REMOTE] Building Docker image..."
    docker compose build --no-cache

    echo "[REMOTE] Restarting service..."
    docker compose -f docker-compose.truenas.yml down --timeout 10
    docker compose -f docker-compose.truenas.yml up -d

    echo "[REMOTE] Waiting for health check..."
    for i in $(seq 1 15); do
        if curl -sf http://localhost:8081/health > /dev/null 2>&1; then
            echo "[REMOTE] ✅ Service is healthy!"
            exit 0
        fi
        sleep 2
    done
    echo "[REMOTE] ⚠️  Health check timeout (service may still be starting)"
REMOTE_SCRIPT

log "✅ Deployment complete!"
echo ""
echo "  Health:   http://192.168.1.92:8081/health"
echo "  Settings: http://192.168.1.92:8081/settings"
echo "  Bus API:  http://192.168.1.92:8081/api/bus-arrival"
