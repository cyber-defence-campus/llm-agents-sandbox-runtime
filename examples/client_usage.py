import asyncio
import uuid
from sandbox_runtime import SandboxClient


async def main():
    # Initialize client (defaults to http://localhost:8000)
    client = SandboxClient()

    session_id = f"example-{uuid.uuid4().hex[:8]}"
    print(f"--- Using SandboxClient for {session_id} ---")

    # 1. Ensure/Create Sandbox
    print("Creating sandbox...")
    try:
        info = await client.ensure_sandbox(session_id)
        print(f"Sandbox ready: {info.get('container_id')}")
    except Exception as e:
        print(f"Error creating sandbox: {e}")
        return

    # 2. Execute Tool
    print("Executing 'run_shell_command' tool...")
    result = await client.execute_tool(
        session_id=session_id,
        agent_id="example-agent",
        tool_name="run_shell_command",
        kwargs={"command": "echo 'Hello from inside the sandbox!'"},
    )
    print(f"Result: {result}")

    # 3. Destroy Sandbox
    print("Cleaning up...")
    await client.destroy_sandbox(session_id)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
