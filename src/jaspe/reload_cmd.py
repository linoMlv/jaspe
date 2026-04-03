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

def run_reload(cfg: JaspeConfig, target: Path, clean_cache: bool = False) -> bool:
    name = cfg.config.app_name
    service = f"jaspe-{name}.service"
    
    # 1. Audit d'état
    # On utilise systemctl --user is-active pour savoir si le service tourne
    res = subprocess.run(["systemctl", "--user", "is-active", service], capture_output=True, text=True)
    was_active = res.stdout.strip() == "active"
    
    # 2. Confirmation
    if not Confirm.ask(f"[bold yellow]⚠️  Attention : Cette opération va supprimer et reconstruire l'environnement de '{name}'. Continuer ?[/]"):
        raise typer.Exit()

    # 3. Arrêt si besoin
    if was_active:
        run_with_spinner(["systemctl", "--user", "stop", service], f"Arrêt de l'application '{name}'")
        for cron in cfg.crons:
            timer_name = f"jaspe-{name}-{cron.name}.timer"
            run_with_spinner(["systemctl", "--user", "stop", timer_name], f"Arrêt du cron {cron.name}", check=False)
        registry.add_or_update_app(name, str(target), cfg.config.app_port, "reloading")

    # 4. Nettoyage Backend
    backend_path = target / cfg.config.backend_folder
    venv_path = backend_path / ".venv"
    
    if venv_path.exists():
        run_with_spinner(["rm", "-rf", str(venv_path)], "Suppression de l'ancien Venv Python")

    if clean_cache:
        run_with_spinner(["uv", "cache", "clean"], "Nettoyage du cache UV global")

    # 5. Nettoyage Frontend
    frontend_path = target / cfg.config.frontend_folder
    node_modules = frontend_path / "node_modules"
    dist_folder = frontend_path / cfg.frontend.dist_folder
    
    if node_modules.exists():
        run_with_spinner(["rm", "-rf", str(node_modules)], "Suppression des modules Node")
    
    if dist_folder.exists():
        run_with_spinner(["rm", "-rf", str(dist_folder)], "Vidage du dossier de build (dist)")
        
    if clean_cache:
         run_with_spinner(["npm", "cache", "clean", "--force"], "Nettoyage du cache NPM global")

    # 6. Reconstruction Backend
    # ensure_python_venv va recréer le dossier s'il manque
    ensure_python_venv(cfg.environment.python_version, backend_path)
    
    # Installation deps
    run_with_spinner(
        ["uv", "pip", "install", "-r", "requirements.txt"], 
        "Réinstallation fraîche des dépendances Python", 
        cwd=str(backend_path),
        env=_backend_env(backend_path)
    )

    # 7. Reconstruction Frontend
    run_with_spinner(["npm", "install"], "Réinstallation fraîche des modules Node", cwd=str(frontend_path))

    console.print(f"\n[bold green]✓[/bold green] Réinitialisation de l'application '{name}' terminée.")
    return was_active
