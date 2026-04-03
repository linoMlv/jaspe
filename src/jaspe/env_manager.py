import os
import re
import subprocess
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from rich.console import Console

console = Console()


def _parse_version(version_str: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", version_str)
    return tuple(int(n) for n in nums)


def _check_version(actual: str, required: str) -> bool:
    match = re.match(r"(>=|>|==|<=|<)?\s*(.+)", required)
    if not match:
        return True
    op = match.group(1) or ">="
    req = _parse_version(match.group(2))
    act = _parse_version(actual)
    if op == ">=":
        return act >= req
    if op == ">":
        return act > req
    if op == "==":
        return act == req
    if op == "<=":
        return act <= req
    if op == "<":
        return act < req
    return True


def check_node_version(required_version: str) -> bool:
    try:
        result = subprocess.run(
            ["node", "-v"], capture_output=True, text=True, check=True
        )
        actual = result.stdout.strip().lstrip("v")
        ok = _check_version(actual, required_version)
        if not ok:
            console.print(
                f"[red]Node.js version {actual} does not satisfy constraint {required_version}.[/red]"
            )
        return ok
    except FileNotFoundError:
        console.print("[red]Node.js is not installed.[/red]")
        return False


def _extract_min_python_version(required: str) -> str:
    """Extrait la version minimale depuis une contrainte (ex: '>=3.11' -> '3.11')."""
    match = re.match(r"(>=|>|==|<=|<)?\s*(.+)", required)
    if not match:
        return "3.11"
    return match.group(2).strip()


def ensure_python_venv(required_version: str, backend_path: Path) -> None:
    """Cree ou verifie le venv uv avec la bonne version Python."""
    venv_path = backend_path / ".venv"
    target_version = _extract_min_python_version(required_version)

    venv_python = venv_path / "bin" / "python"
    if venv_python.exists():
        result = subprocess.run(
            [str(venv_python), "--version"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            actual = result.stdout.strip().removeprefix("Python ")
            if _check_version(actual, required_version):
                console.print(f"[green]Python {actual} venv verified.[/green]")
                return
            console.print(
                f"[yellow]Existing venv uses Python {actual}. "
                f"Recreating with Python {target_version}...[/yellow]"
            )

    console.print(
        f"[blue]Creating venv with Python {target_version} via uv...[/blue]"
    )
    subprocess.run(
        ["uv", "venv", "--python", target_version, "--clear"],
        cwd=str(backend_path),
        check=True,
    )
    console.print(f"[green]Python {target_version} venv ready.[/green]")


def read_env_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    try:
        return tomllib.loads(raw)
    except tomllib.TOMLDecodeError as e:
        from rich.panel import Panel
        import sys
        console.print(Panel(str(e), title="[bold red]Syntax error in .env.toml[/bold red]", border_style="red"))
        sys.exit(1)


def read_local_env_file(path: Path) -> dict:
    if not path.exists():
        return {}
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip("\"'")
    return env


def merge_environments(
    os_env: dict, local_env: dict, toml_env: dict
) -> dict:
    merged = {}
    merged.update(local_env)
    merged.update(toml_env)
    merged.update(os_env)
    return merged


def build_env_for_section(
    section: str, env_toml_path: Path, project_path: Path
) -> dict:
    os_env = dict(os.environ)
    toml_data = read_env_toml(env_toml_path)
    toml_section = toml_data.get(section, {})

    section_folder = "frontend" if section == "frontend" else "backend"
    local_env_file = project_path / section_folder / ".env"
    local_env = read_local_env_file(local_env_file)

    merged = merge_environments(os_env, local_env, toml_section)

    if section == "backend":
        merged["VIRTUAL_ENV"] = str(project_path / section_folder / ".venv")

    return merged
