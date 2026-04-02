import subprocess
from typing import List, Optional
import typer
from rich.console import Console
from rich.panel import Panel

console = Console()

def run_with_spinner(cmd: List[str], loading_msg: str, cwd: Optional[str] = None, env: dict = None, check: bool = True) -> str:
    """Runs a command silently behind a Rich spinner. Returns stdout if success."""
    with console.status(f"[bold cyan]{loading_msg}...[/bold cyan]", spinner="dots"):
        try:
            result = subprocess.run(
                cmd, 
                cwd=cwd, 
                env=env,
                capture_output=True, 
                text=True, 
                check=check
            )
            if not check and result.returncode != 0:
                console.print(f"[yellow]⚠[/yellow] {loading_msg} [dim](Ignoré - Exit {result.returncode})[/dim]")
                return result.stdout
                
            console.print(f"[green]✓[/green] {loading_msg}")
            return result.stdout
        except subprocess.CalledProcessError as e:
            console.print(f"[red]✗[/red] [bold red]Échec :[/bold red] {loading_msg}")
            error_details = e.stderr.strip() if e.stderr and e.stderr.strip() else e.stdout.strip()
            if not error_details:
                error_details = f"Le programme s'est terminé avec le code d'erreur {e.returncode}."
                
            console.print(Panel(
                error_details, 
                title=f"[bold red]Logs de l'erreur ({e.returncode})[/bold red]", 
                border_style="red"
            ))
            raise typer.Exit(code=1)
