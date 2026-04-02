import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


@dataclass
class ConfigSection:
    app_name: str = "mon_projet"
    app_port: int = 8000
    host: str = "127.0.0.1"
    backend_folder: str = "backend"
    frontend_folder: str = "frontend"


@dataclass
class GitSection:
    repo_url: str = ""
    branch: str = "main"


@dataclass
class SystemSection:
    autostart: bool = True
    restart_on_crash: bool = True


@dataclass
class EnvironmentSection:
    python_version: str = ">=3.11"
    node_version: str = ">=20.0"


@dataclass
class BackendSection:
    entrypoint: str = "main:app"
    migrations_dir: str = ""
    api_prefix: str = "/api"


@dataclass
class FrontendSection:
    build_command: str = "npm run build"
    dist_folder: str = "dist"
    assets_prefix: str = "/assets"


@dataclass
class FrontendSection:
    build_command: str = "npm run build"
    dist_folder: str = "dist"
    assets_prefix: str = "/assets"


@dataclass
class DeploySection:
    target: str = ""
    path: str = ""
    sync_env: bool = False
    build_locally: bool = False

@dataclass
class CronSection:
    name: str = ""
    schedule: str = "*-*-* 00:00:00"
    command: str = ""


@dataclass
class JaspeConfig:
    config: ConfigSection = field(default_factory=ConfigSection)
    git: GitSection = field(default_factory=GitSection)
    system: SystemSection = field(default_factory=SystemSection)
    environment: EnvironmentSection = field(default_factory=EnvironmentSection)
    backend: BackendSection = field(default_factory=BackendSection)
    frontend: FrontendSection = field(default_factory=FrontendSection)
    deploy: DeploySection = field(default_factory=DeploySection)
    crons: list[CronSection] = field(default_factory=list)


def check_if_toml_exists(path: Path) -> bool:
    return path.is_file()


def read_toml_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_toml_to_dict(toml_string: str) -> dict:
    return tomllib.loads(toml_string)


def map_dict_to_jaspe_config(data: dict) -> JaspeConfig:
    cron_data = data.get("cron", [])
    crons = [CronSection(**c) for c in cron_data] if isinstance(cron_data, list) else []

    return JaspeConfig(
        config=ConfigSection(**data.get("config", {})),
        git=GitSection(**data.get("git", {})),
        system=SystemSection(**data.get("system", {})),
        environment=EnvironmentSection(**data.get("environment", {})),
        backend=BackendSection(**data.get("backend", {})),
        frontend=FrontendSection(**data.get("frontend", {})),
        deploy=DeploySection(**data.get("deploy", {})),
        crons=crons,
    )


def load_config(path: Path) -> JaspeConfig:
    import sys
    from rich.console import Console
    from rich.panel import Panel
    c = Console()
    
    if not path.is_file():
        c.print("[red]Fichier jaspe.toml introuvable. Êtes-vous dans un projet Jaspe ?[/red]")
        sys.exit(1)
        
    raw = read_toml_file(path)
    try:
        data = parse_toml_to_dict(raw)
    except tomllib.TOMLDecodeError as e:
        c.print(Panel(str(e), title="[bold red]Erreur de syntaxe dans jaspe.toml[/bold red]", border_style="red"))
        sys.exit(1)
        
    return map_dict_to_jaspe_config(data)
