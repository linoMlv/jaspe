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
    run_with_spinner(["git", "fetch"], "Checking for updates (Git Fetch)...", cwd=str(project_path))


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
        console.print("[green]Application is up to date.[/green]")
        return False

    console.print(f"[yellow]Update available![/yellow]")
    console.print(f"  Local  : {local[:8]}")
    console.print(f"  Remote : {remote[:8]}")
    return True


def run_git_pull(project_path: Path) -> None:
    run_with_spinner(["git", "pull"], "Pulling changes...", cwd=str(project_path))


def run_uv_pip_sync(backend_path: Path) -> None:
    req = backend_path / "requirements.txt"
    if req.exists():
        run_with_spinner(
            ["uv", "pip", "install", "-r", "requirements.txt"],
            "Synchronizing Python dependencies...",
            cwd=str(backend_path),
            env=_backend_env(backend_path),
        )


def run_npm_ci(frontend_path: Path) -> None:
    if (frontend_path / "package-lock.json").exists():
        run_with_spinner(["npm", "ci"], "Installing Node.js dependencies...", cwd=str(frontend_path))


def run_alembic_upgrade(backend_path: Path, migrations_dir: str) -> None:
    try:
        run_with_spinner(
            ["uv", "run", "alembic", "upgrade", "head"],
            "Running Alembic migrations...",
            cwd=str(backend_path),
            env=_backend_env(backend_path),
        )
    except Exception:
        console.print("[red]Migration failed! Stopping update.[/red]")
        raise RuntimeError("Alembic migration failed")


def run_npm_build(frontend_path: Path) -> None:
    run_with_spinner(["npm", "run", "build"], "Building frontend...", cwd=str(frontend_path))


def run_full_update(config: JaspeConfig, project_path: Path, reload: bool = False, skip_build: bool = False) -> None:
    app_name = config.config.app_name
    service = f"jaspe-{app_name}.service"
    backend_path = project_path / config.config.backend_folder
    frontend_path = project_path / config.config.frontend_folder

    try:
        old_commit = get_local_commit_hash(project_path)
    except Exception:
        old_commit = None

    # 1. Fetch and Verify
    if not check_for_update(config, project_path):
        console.print("[green]Nothing to update.[/green]")
        return

    # 2. Stop Service
    run_with_spinner(["systemctl", "--user", "stop", service], "Stopping production service...")

    # 3. Pull
    run_git_pull(project_path)

    if reload:
        # Nettoyage profond des environnements
        venv_path = backend_path / ".venv"
        node_modules = frontend_path / "node_modules"
        if venv_path.exists():
            run_with_spinner(["rm", "-rf", str(venv_path)], "Removing Venv (Reload)...")
        if node_modules.exists():
            run_with_spinner(["rm", "-rf", str(node_modules)], "Removing Node modules (Reload)...")

    # 4. Venv + Dépendances
    from jaspe.env_manager import ensure_python_venv
    ensure_python_venv(config.environment.python_version, backend_path)
    run_uv_pip_sync(backend_path)
    run_npm_ci(frontend_path)

    # 5. Migrations et Build avec Rollback
    try:
        if config.backend.migrations_dir:
            run_alembic_upgrade(backend_path, config.backend.migrations_dir)
        
        if not skip_build:
            run_npm_build(frontend_path)
    except Exception as e:
        console.print(f"[red]Update failed ({e}). Triggering Rollback...[/red]")
        if old_commit:
            run_with_spinner(["git", "reset", "--hard", old_commit], f"Restoring previous commit ({old_commit[:8]})...", cwd=str(project_path))
            ensure_python_venv(config.environment.python_version, backend_path)
            run_uv_pip_sync(backend_path)
            run_npm_ci(frontend_path)
            run_npm_build(frontend_path)
        try:
            run_with_spinner(["systemctl", "--user", "start", service], "Restarting stable version...")
        except Exception:
            pass
        return

    # 7. Restart
    run_with_spinner(["systemctl", "--user", "start", service], "Restarting service...")

    console.print(f"[green]Application '{app_name}' updated successfully.[/green]")
