import asyncio
import uuid
from sandbox_runtime import SandboxClient


async def main():
    client = SandboxClient()

    session_id = f"example-{uuid.uuid4().hex[:8]}"
    print(f"--- Using SandboxClient for {session_id} ---")

    print("Creating sandbox...")
    try:
        info = await client.ensure_sandbox(session_id)
        print(f"Sandbox ready: {info.get('container_id')}")
    except Exception as e:
        print(f"Error creating sandbox: {e}")
        return

    print("Executing 'run_shell_command' tool...")
    result = await client.execute_tool(
        session_id=session_id,
        agent_id="example-agent",
        tool_name="run_shell_command",
        kwargs={"command": "echo 'Hello from inside the sandbox!'"},
    )
    print(f"Result: {result}")

    print("Cleaning up...")
    await client.destroy_sandbox(session_id)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
