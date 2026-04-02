import os
import subprocess
from pathlib import Path

from rich.console import Console

from rich.console import Console
from jaspe.ui import run_with_spinner
from jaspe.config import JaspeConfig


def _backend_env(backend_path: Path) -> dict:
    env = dict(os.environ)
    env["VIRTUAL_ENV"] = str(backend_path / ".venv")
    env.pop("CONDA_PREFIX", None)
    return env

console = Console()


def fetch_git(project_path: Path) -> None:
    run_with_spinner(["git", "fetch"], "Recherche de mises à jour en cours (Git Fetch)", cwd=str(project_path))


def get_local_commit_hash(project_path: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(project_path),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def get_remote_commit_hash(project_path: Path, branch: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", f"origin/{branch}"],
        cwd=str(project_path),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def check_for_update(config: JaspeConfig, project_path: Path) -> bool:
    fetch_git(project_path)
    local = get_local_commit_hash(project_path)
    remote = get_remote_commit_hash(project_path, config.git.branch)

    if local == remote:
        console.print("[green]L'application est à jour.[/green]")
        return False

    console.print(f"[yellow]Mise à jour disponible ![/yellow]")
    console.print(f"  Local  : {local[:8]}")
    console.print(f"  Remote : {remote[:8]}")
    return True


def run_git_pull(project_path: Path) -> None:
    run_with_spinner(["git", "pull"], "Pull des modifications", cwd=str(project_path))


def run_uv_pip_sync(backend_path: Path) -> None:
    req = backend_path / "requirements.txt"
    if req.exists():
        run_with_spinner(
            ["uv", "pip", "install", "-r", "requirements.txt"],
            "Synchronisation des dépendances Python",
            cwd=str(backend_path),
            env=_backend_env(backend_path),
        )


def run_npm_ci(frontend_path: Path) -> None:
    if (frontend_path / "package-lock.json").exists():
        run_with_spinner(["npm", "ci"], "Installation des dépendances Node", cwd=str(frontend_path))


def run_alembic_upgrade(backend_path: Path, migrations_dir: str) -> None:
    try:
        run_with_spinner(
            ["uv", "run", "alembic", "upgrade", "head"],
            "Exécution des migrations Alembic",
            cwd=str(backend_path),
            env=_backend_env(backend_path),
        )
    except Exception:
        console.print("[red]La migration a échoué ! Arrêt de la mise à jour.[/red]")
        raise RuntimeError("Alembic migration failed")


def run_npm_build(frontend_path: Path) -> None:
    run_with_spinner(["npm", "run", "build"], "Build du frontend", cwd=str(frontend_path))


def run_full_update(config: JaspeConfig, project_path: Path) -> None:
    app_name = config.config.app_name
    service = f"jaspe-{app_name}.service"
    backend_path = project_path / config.config.backend_folder
    frontend_path = project_path / config.config.frontend_folder

    try:
        old_commit = get_local_commit_hash(project_path)
    except Exception:
        old_commit = None

    # 1. Fetch et vérification
    if not check_for_update(config, project_path):
        console.print("[green]Rien à mettre à jour.[/green]")
        return

    # 2. Arrêt du service
    run_with_spinner(["systemctl", "--user", "stop", service], "Arrêt du service de production en cours")

    # 3. Pull
    run_git_pull(project_path)

    # 4. Venv + Dépendances
    from jaspe.env_manager import ensure_python_venv
    ensure_python_venv(config.environment.python_version, backend_path)
    run_uv_pip_sync(backend_path)
    run_npm_ci(frontend_path)

    # 5. Migrations et Build avec Rollback
    try:
        if config.backend.migrations_dir:
            run_alembic_upgrade(backend_path, config.backend.migrations_dir)
        run_npm_build(frontend_path)
    except Exception as e:
        console.print(f"[red]Échec de la mise à jour ({e}). Déclenchement du Rollback...[/red]")
        if old_commit:
            run_with_spinner(["git", "reset", "--hard", old_commit], f"Restauration du commit précédent ({old_commit[:8]})", cwd=str(project_path))
            ensure_python_venv(config.environment.python_version, backend_path)
            run_uv_pip_sync(backend_path)
            run_npm_ci(frontend_path)
            run_npm_build(frontend_path)
        try:
            run_with_spinner(["systemctl", "--user", "start", service], "Redémarrage de la version stable")
        except Exception:
            pass
        return

    # 7. Redémarrage
    run_with_spinner(["systemctl", "--user", "start", service], "Redémarrage du service")

    console.print(f"[green]Application '{app_name}' mise à jour avec succès ![/green]")
