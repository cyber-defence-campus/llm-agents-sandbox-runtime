import os

AGENT_SANDBOX_IMAGE = os.getenv("AGENT_SANDBOX_IMAGE", "sandbox:local")
AGENT_NETWORK_NAME = os.getenv("AGENT_NETWORK_NAME", "platform_net")
AGENT_NETWORK_MODE = os.getenv("AGENT_NETWORK_MODE")

# Format: "volume_name_or_path:mount_path:mode"
AGENT_SANDBOX_VOLUMES = os.getenv("AGENT_SANDBOX_VOLUMES", "")
