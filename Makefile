.PHONY: help run stop logs clean

help:
	@echo "Sandbox Runtime - Standalone Development Commands"
	@echo ""
	@echo "Running:"
	@echo "  run    - Build and start sandbox service"
	@echo "  stop   - Stop sandbox service"
	@echo "  logs   - Follow logs"
	@echo ""
	@echo "Maintenance:"
	@echo "  clean  - Remove stopped containers and cache"

run:
	@echo "🚀 Starting Sandbox Runtime..."
	@mkdir -p logs
	docker compose up --build -d

stop:
	@echo "🛑 Stopping Sandbox Runtime..."
	docker compose down --remove-orphans
	@echo "🧹 Removing orphaned sandbox containers..."
	docker ps -a --filter "name=platform-" --format "{{.ID}}" | xargs -r docker rm -f

logs:
	docker compose logs -f --tail=100

clean:
	@echo "🧹 Cleaning up..."
	docker compose down --remove-orphans -v
	@echo "🧹 Removing orphaned sandbox containers..."
	docker ps -a --filter "name=platform-" --format "{{.ID}}" | xargs -r docker rm -f
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
