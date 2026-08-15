#!/usr/bin/env python3
import asyncio
import json
import os
import sys
import uuid
from typing import Any, Dict

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.json import JSON

from sandbox_runtime.client import SandboxClient

BASE_URL = os.getenv("SANDBOX_RUNTIME_URL", "http://localhost:8000")
console = Console()
client = SandboxClient(BASE_URL)


def clear_screen():
    console.clear()


async def list_sandboxes_view():
    clear_screen()
    console.print(Panel("[bold blue]Active Sandboxes[/bold blue]", expand=False))

    try:
        response = await client.list_sandboxes()
        sandboxes = response.get("sandboxes", [])
    except Exception as e:
        console.print(f"[bold red]Error listing sandboxes:[/bold red] {e}")
        Prompt.ask("Press Enter to return")
        return

    if not sandboxes:
        console.print("[yellow]No active sandboxes found.[/yellow]")
        Prompt.ask("Press Enter to return")
        return

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=4)
    table.add_column("Session ID", style="cyan")
    table.add_column("Container ID")
    table.add_column("Port")

    for idx, sb in enumerate(sandboxes):
        table.add_row(
            str(idx + 1),
            sb.get("session_id"),
            (sb.get("container_id") or "")[:12],
            str(sb.get("tool_server_port")),
        )

    console.print(table)
    console.print("\n")

    choice = Prompt.ask("Select sandbox # (or 'q' to return)")
    if choice.lower() == "q":
        return

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(sandboxes):
            session_id = sandboxes[idx]["session_id"]
            await view_sandbox_details(session_id, sandboxes[idx])
        else:
            console.print("[red]Invalid selection.[/red]")
            asyncio.sleep(1)
    except ValueError:
        pass


async def interactive_shell_view(session_id: str):
    clear_screen()
    console.print(
        Panel(
            f"[bold green]Interactive Shell in {session_id}[/bold green]", expand=False
        )
    )
    console.print("[dim]Type 'exit' or 'quit' to return.[/dim]\n")

    while True:
        command = Prompt.ask(f"[cyan]{session_id}[/cyan] $")
        if command.lower() in ("exit", "quit"):
            break

        if not command.strip():
            continue

        with console.status("[dim]Running...[/dim]"):
            try:
                result = await client.execute_tool(
                    session_id=session_id,
                    agent_id="cli-user",
                    tool_name="run_shell_command",
                    kwargs={"command": command},
                )

                if "error" in result and result["error"]:
                    console.print(f"[red]Error: {result['error']}[/red]")
                else:
                    output = result.get("result", {}).get("content", "")
                    console.print(output)
            except Exception as e:
                console.print(f"[bold red]Error executing command:[/bold red] {e}")


async def view_sandbox_details(session_id: str, details: Dict[str, Any]):
    while True:
        clear_screen()
        console.print(
            Panel(f"[bold blue]Sandbox: {session_id}[/bold blue]", expand=False)
        )

        console.print(f"Container ID: [green]{details.get('container_id')}[/green]")
        console.print(f"API URL: [green]{details.get('api_url')}[/green]")

        console.print("\n[bold]Options:[/bold]")
        console.print("1. Interactive Shell (Recommended)")
        console.print("2. Execute Raw Tool (Advanced)")
        console.print("3. Inject File")
        console.print("4. Destroy Sandbox")
        console.print("5. Back")

        choice = Prompt.ask("Select option", choices=["1", "2", "3", "4", "5"])

        if choice == "1":
            await interactive_shell_view(session_id)
        elif choice == "2":
            await execute_tool_view(session_id)
        elif choice == "3":
            await inject_file_view(session_id)
        elif choice == "4":
            if Confirm.ask(f"Are you sure you want to destroy sandbox {session_id}?"):
                try:
                    await client.destroy_sandbox(session_id)
                    console.print("[bold red]Destruction initiated.[/bold red]")
                    await asyncio.sleep(1)
                    return
                except Exception as e:
                    console.print(f"[red]Error destroying sandbox: {e}[/red]")
                    Prompt.ask("Press Enter to continue")
        elif choice == "5":
            return


async def inject_file_view(session_id: str):
    clear_screen()
    console.print(
        Panel(f"[bold green]Inject File into {session_id}[/bold green]", expand=False)
    )

    src_path = Prompt.ask("Source Path (Host)")
    dest_path = Prompt.ask(
        "Destination Path (Sandbox)",
        default=f"/workspace/{os.path.basename(src_path) if src_path else 'file'}",
    )

    if not src_path or not os.path.exists(src_path):
        console.print(f"[red]Source path does not exist: {src_path}[/red]")
        Prompt.ask("Press Enter to continue")
        return

    with console.status("[bold green]Injecting...[/bold green]"):
        try:
            result = await client.inject_file(
                session_id=session_id, src_path=src_path, dest_path=dest_path
            )
            console.print(
                f"[bold green]Success![/bold green] {result.get('message', 'File injected.')}"
            )
        except Exception as e:
            console.print(f"[bold red]Error injecting file:[/bold red] {e}")

    Prompt.ask("Press Enter to return")


async def execute_tool_view(session_id: str):
    clear_screen()
    console.print(
        Panel(f"[bold green]Execute Tool in {session_id}[/bold green]", expand=False)
    )

    tool_name = Prompt.ask("Tool Name", default="run_shell_command")
    kwargs_str = Prompt.ask("Arguments (JSON)", default='{"command": "whoami"}')

    try:
        kwargs = json.loads(kwargs_str)
    except json.JSONDecodeError:
        console.print("[red]Invalid JSON arguments.[/red]")
        Prompt.ask("Press Enter to continue")
        return

    with console.status("[bold green]Executing...[/bold green]"):
        try:
            result = await client.execute_tool(
                session_id=session_id,
                agent_id="cli-user",
                tool_name=tool_name,
                kwargs=kwargs,
            )
            console.print(Panel(JSON(json.dumps(result)), title="Execution Result"))
        except Exception as e:
            console.print(f"[bold red]Error executing tool:[/bold red] {e}")

    Prompt.ask("Press Enter to return")


async def create_sandbox_view():
    clear_screen()
    console.print(Panel("[bold green]Create New Sandbox[/bold green]", expand=False))

    default_session_id = f"manual-{uuid.uuid4().hex[:6]}"
    session_id = Prompt.ask("Session ID", default=default_session_id)

    with console.status("[bold green]Creating sandbox...[/bold green]"):
        try:
            result = await client.ensure_sandbox(session_id)
            if "error" in result:
                console.print(f"[red]Error: {result['error']}[/red]")
            else:
                console.print(
                    f"[bold green]Success![/bold green] Sandbox created for {session_id}"
                )
        except Exception as e:
            console.print(f"[bold red]Error creating sandbox:[/bold red] {e}")

    Prompt.ask("Press Enter to return")


async def main_menu():
    try:
        while True:
            clear_screen()
            console.print(
                Panel("[bold magenta]Sandbox Runtime CLI[/bold magenta]", expand=False)
            )
            console.print("1. List Active Sandboxes")
            console.print("2. Create New Sandbox")
            console.print("3. Exit")
            console.print("\n")

            choice = Prompt.ask("Choose an option", choices=["1", "2", "3"])

            if choice == "1":
                await list_sandboxes_view()
            elif choice == "2":
                await create_sandbox_view()
            elif choice == "3":
                console.print("Goodbye!")
                break
    except KeyboardInterrupt:
        console.print("\n[yellow]Exiting...[/yellow]")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main_menu())
