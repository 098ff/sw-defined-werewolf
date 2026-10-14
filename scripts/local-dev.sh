#!/usr/bin/env bash
set -e

# ==============================================================================
# Local Development Helper (Docker Compose)
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR/.."
COMPOSE_FILE="$ROOT_DIR/docker-compose.dev.yml"

CMD="${1:-up}"

case "$CMD" in
    up)
        echo "Starting Werewolf 5-service stack + Redis locally..."
        docker compose -f "$COMPOSE_FILE" up --build -d
        echo ""
        echo "Stack running! Access the game at: http://localhost:8080"
        echo "View logs with: ./scripts/local-dev.sh logs"
        ;;
    down)
        echo "Stopping local Werewolf stack..."
        docker compose -f "$COMPOSE_FILE" down
        ;;
    logs)
        docker compose -f "$COMPOSE_FILE" logs -f
        ;;
    restart)
        docker compose -f "$COMPOSE_FILE" restart
        ;;
    *)
        echo "Usage: $0 {up|down|logs|restart}"
        exit 1
        ;;
esac
