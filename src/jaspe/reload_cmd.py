import os
import subprocess
from pathlib import Path
from rich.console import Console
from rich.prompt import Confirm
import typer

from jaspe.config import JaspeConfig
from jaspe.ui import run_with_spinner
from jaspe.env_manager import ensure_python_venv
from jaspe import registry

console = Console()

def _backend_env(backend_path: Path) -> dict:
    env = dict(os.environ)
    env["VIRTUAL_ENV"] = str(backend_path / ".venv")
    env.pop("CONDA_PREFIX", None)
    return env

def run_reload(cfg: JaspeConfig, target: Path, clean_cache: bool = False, perform_stop: bool = False) -> bool:
    name = cfg.config.app_name
    
    # 1. Confirmation
    if not Confirm.ask(f"[bold yellow]⚠️  Warning: This operation will delete and rebuild the environment for '{name}'. Proceed?[/]"):
        return False

    if perform_stop:
        registry.add_or_update_app(name, str(target), cfg.config.app_port, "reloading")

    # 2. Nettoyage Backend
    backend_path = target / cfg.config.backend_folder
    venv_path = backend_path / ".venv"
    
    if venv_path.exists():
        run_with_spinner(["rm", "-rf", str(venv_path)], "Removing old Python Venv...")

    if clean_cache:
        run_with_spinner(["uv", "cache", "clean"], "Cleaning global UV cache...")

    # 5. Nettoyage Frontend
    frontend_path = target / cfg.config.frontend_folder
    node_modules = frontend_path / "node_modules"
    dist_folder = frontend_path / cfg.frontend.dist_folder
    
    if node_modules.exists():
        run_with_spinner(["rm", "-rf", str(node_modules)], "Removing Node modules...")
    
    if dist_folder.exists():
        run_with_spinner(["rm", "-rf", str(dist_folder)], "Cleaning build folder (dist)...")
        
    if clean_cache:
         run_with_spinner(["npm", "cache", "clean", "--force"], "Cleaning global NPM cache...")

    # 6. Reconstruction Backend
    # ensure_python_venv va recréer le dossier s'il manque
    ensure_python_venv(cfg.environment.python_version, backend_path)
    
    # Dependencies installation
    run_with_spinner(
        ["uv", "pip", "install", "-r", "requirements.txt"], 
        "Freshly reinstalling Python dependencies...", 
        cwd=str(backend_path),
        env=_backend_env(backend_path)
    )

    # 7. Frontend Reconstruction
    run_with_spinner(["npm", "install"], "Freshly reinstalling Node modules...", cwd=str(frontend_path))

    console.print(f"\n[bold green]✓[/bold green] Application '{name}' reset successfully.")
    return True
