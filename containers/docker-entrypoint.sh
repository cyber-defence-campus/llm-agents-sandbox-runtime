#!/bin/bash
set -e

if [ -z "$CAIDO_PORT" ]; then
    echo "CAIDO_PORT not set; skipping Caido/proxy setup (proxy is commented out)."
else
    echo "CAIDO_PORT set to $CAIDO_PORT (proxy setup is currently commented out)."
fi

echo "Container initialization complete - agents will start their own tool servers as needed"
echo "✅ Shared container ready for multi-agent use"

cd /workspace

# Debug logging for environment variables
echo "DEBUG: TOOL_SERVER_PORT=${TOOL_SERVER_PORT:-<unset>}"
echo "DEBUG: TOOL_SERVER_TOKEN length=${#TOOL_SERVER_TOKEN}"

if [ -n "$TOOL_SERVER_PORT" ] && [ -n "$TOOL_SERVER_TOKEN" ]; then
    if [ -f /app/venv/bin/activate ]; then
        # shellcheck disable=SC1091
        source /app/venv/bin/activate
    else
        echo "Virtual environment activation script not found at /app/venv/bin/activate; continuing without venv."
    fi

    if [ -f /etc/profile.d/proxy.sh ]; then
        # shellcheck disable=SC1091
        source /etc/profile.d/proxy.sh
    else
        echo "Proxy profile /etc/profile.d/proxy.sh not found; skipping proxy source."
    fi
    
    # Re-check after sourcing scripts to ensure variables weren't modified
    if [ -z "$TOOL_SERVER_TOKEN" ]; then
        echo "ERROR: TOOL_SERVER_TOKEN became empty after sourcing scripts!"
        exit 1
    fi
    
    echo "Starting tool server on port $TOOL_SERVER_PORT..."
    exec python -m agent_framework.runtime.tool_server \
        --token="${TOOL_SERVER_TOKEN}" \
        --host="0.0.0.0" \
        --port="${TOOL_SERVER_PORT}"
else
    echo "✅ Container ready. Waiting for commands."
    exec "$@"
fi
