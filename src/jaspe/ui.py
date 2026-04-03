import subprocess
from typing import List, Optional
import typer
from rich.console import Console
from rich.panel import Panel

console = Console()

def run_with_spinner(cmd: List[str] | callable, loading_msg: str, cwd: Optional[str] = None, env: dict = None, check: bool = True) -> str:
    """Runs a command or a callable silently behind a Rich spinner. Returns stdout if success."""
    from typing import Callable
    with console.status(f"[bold cyan]{loading_msg}...[/bold cyan]", spinner="dots"):
        try:
            if isinstance(cmd, (list, tuple)):
                result = subprocess.run(
                    cmd, 
                    cwd=cwd, 
                    env=env,
                    capture_output=True, 
                    text=True, 
                    check=check
                )
                if not check and result.returncode != 0:
                    console.print(f"[yellow]⚠[/yellow] {loading_msg} [dim](Ignored - Exit {result.returncode})[/dim]")
                    return result.stdout
                    
                console.print(f"[green]✓[/green] {loading_msg}")
                return result.stdout
            elif callable(cmd):
                res = cmd()
                if check and res is False:
                    raise Exception(f"Task '{loading_msg}' returned failure.")
                console.print(f"[green]✓[/green] {loading_msg}")
                return str(res)
        except subprocess.CalledProcessError as e:
            console.print(f"[red]✗[/red] [bold red]Error:[/bold red] {loading_msg}")
            error_details = e.stderr.strip() if e.stderr and e.stderr.strip() else e.stdout.strip()
            if not error_details:
                error_details = f"Process exited with error code {e.returncode}."
                
            console.print(Panel(
                error_details, 
                title=f"[bold red]Error Logs ({e.returncode})[/bold red]", 
                border_style="red"
            ))
            raise typer.Exit(code=1)
        except Exception as e:
            console.print(f"[red]✗[/red] [bold red]Error:[/bold red] {loading_msg}")
            console.print(Panel(str(e), title="[bold red]Exception Details[/bold red]", border_style="red"))
            if check:
                raise typer.Exit(code=1)
            return str(e)
