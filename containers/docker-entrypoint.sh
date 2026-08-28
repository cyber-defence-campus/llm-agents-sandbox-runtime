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

as_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    else
        sudo -n "$@"
    fi
}

if [ -n "${AGENT_RESTRICTED_CIDR:-}" ] && [ -n "${AGENT_ALLOWED_ADDRESS:-}" ]; then
    # The operator is on the lab wire for the initial RCE, but it must not be
    # able to use that shell as a free lateral-movement carrier. Replace the
    # connected segment route with a blackhole and put back one host route for
    # the granted entry address. This happens before the tool server starts;
    # its process tree receives a bounding set without NET_ADMIN below, so a
    # terminal command cannot remove the boundary.
    route_dev="$(as_root ip -o -4 route show "${AGENT_RESTRICTED_CIDR}" \
        | awk 'NR == 1 { for (i = 1; i <= NF; i++) if ($i == "dev") { print $(i + 1); exit } }')"
    if [ -z "$route_dev" ]; then
        echo "ERROR: no interface carries ${AGENT_RESTRICTED_CIDR}" >&2
        exit 1
    fi
    as_root ip route del "${AGENT_RESTRICTED_CIDR}" dev "$route_dev"
    as_root ip route add blackhole "${AGENT_RESTRICTED_CIDR}"
    as_root ip route add "${AGENT_ALLOWED_ADDRESS}/32" dev "$route_dev" scope link
    echo "Operator egress restricted to ${AGENT_ALLOWED_ADDRESS} on ${AGENT_RESTRICTED_CIDR}"
fi

if [ -n "${AGENT_EGRESS_CIDR:-}" ]; then
    # Keep the operator's platform interface for the incoming tool-server
    # connection, but deny new outbound connections on it. Established and
    # related traffic must remain allowed so the control request can receive
    # its response. The lab CIDR is the only new destination permitted; the
    # tool server loses NET_ADMIN below, so a shell cannot remove these rules.
    as_root iptables -F OUTPUT
    as_root iptables -A OUTPUT -o lo -j ACCEPT
    as_root iptables -A OUTPUT -d "${AGENT_EGRESS_CIDR}" -j ACCEPT
    as_root iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
    as_root iptables -A OUTPUT -j REJECT
    echo "Operator new egress restricted to ${AGENT_EGRESS_CIDR}"
fi

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
    tool_python="$(command -v python)"
    tool_pythonpath="${PYTHONPATH:-}:/llm-agents-orchestrator/src:/app/rt-automation-tactics"
    if [ "${AGENT_DROP_NET_ADMIN:-0}" = "1" ]; then
        if [ "$(id -u)" -eq 0 ]; then
            exec setpriv --no-new-privs \
                --bounding-set=-net_admin \
                --inh-caps=-net_admin \
                --ambient-caps=-net_admin \
                "$tool_python" -m agent_framework.runtime.tool_server \
                --token="${TOOL_SERVER_TOKEN}" \
                --host="0.0.0.0" \
                --port="${TOOL_SERVER_PORT}"
        else
            # The pentest image deliberately runs as pentester. Let sudo do
            # only this one privilege transition, then make setpriv remove
            # NET_ADMIN before the server creates its tmux shell.
            exec sudo -n env \
                "AGENT_SANDBOX_MODE=${AGENT_SANDBOX_MODE:-true}" \
                "PYTHONPATH=${tool_pythonpath}" \
                setpriv --no-new-privs \
                --bounding-set=-net_admin \
                --inh-caps=-net_admin \
                --ambient-caps=-net_admin \
                "$tool_python" -m agent_framework.runtime.tool_server \
                --token="${TOOL_SERVER_TOKEN}" \
                --host="0.0.0.0" \
                --port="${TOOL_SERVER_PORT}"
        fi
    else
        exec python -m agent_framework.runtime.tool_server \
            --token="${TOOL_SERVER_TOKEN}" \
            --host="0.0.0.0" \
            --port="${TOOL_SERVER_PORT}"
    fi
else
    echo "✅ Container ready. Waiting for commands."
    exec "$@"
fi
