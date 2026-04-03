import os
import re
import subprocess
from pathlib import Path

from rich.console import Console
from jaspe.ui import run_with_spinner

console = Console()


def _backend_env(backend_path: Path) -> dict:
    """Retourne un env avec VIRTUAL_ENV pointant vers le venv du backend."""
    env = dict(os.environ)
    env["VIRTUAL_ENV"] = str(backend_path / ".venv")
    env.pop("CONDA_PREFIX", None)
    return env


def install_npm_exact(pkg_name: str, frontend_path: Path, dev: bool = False) -> None:
    mode_text = "(dev) " if dev else ""
    save_flag = "--save-dev" if dev else "--save-prod"
    run_with_spinner(
        ["npm", "install", pkg_name, save_flag, "--save-exact"],
        f"Installing npm package '{pkg_name}' {mode_text}(exact version)...",
        cwd=str(frontend_path),
    )


def install_uv_pkg(pkg_name: str, backend_path: Path) -> None:
    run_with_spinner(
        ["uv", "pip", "install", pkg_name],
        f"Installing Python package '{pkg_name}' via uv...",
        cwd=str(backend_path),
        env=_backend_env(backend_path),
    )


def get_uv_pkg_version(pkg_name: str, backend_path: Path) -> str | None:
    result = subprocess.run(
        ["uv", "pip", "show", pkg_name],
        cwd=str(backend_path),
        env=_backend_env(backend_path),
        capture_output=True,
        text=True,
    )
    match = re.search(r"^Version:\s*(.+)$", result.stdout, re.MULTILINE)
    return match.group(1).strip() if match else None


def update_requirements_txt(pkg_name: str, version: str, backend_path: Path) -> None:
    req_file = backend_path / "requirements.txt"
    lines: list[str] = []
    found = False

    if req_file.exists():
        lines = req_file.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if line.strip().startswith(pkg_name):
                lines[i] = f"{pkg_name}=={version}"
                found = True
                break

    if not found:
        lines.append(f"{pkg_name}=={version}")

    req_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def add_backend_package(pkg_name: str, backend_path: Path) -> None:
    install_uv_pkg(pkg_name, backend_path)
    version = get_uv_pkg_version(pkg_name, backend_path)
    if version:
        update_requirements_txt(pkg_name, version, backend_path)
        console.print(f"[green]'{pkg_name}=={version}' added to requirements.txt[/green]")
    else:
        console.print(f"[red]Failed to retrieve version for '{pkg_name}'.[/red]")
