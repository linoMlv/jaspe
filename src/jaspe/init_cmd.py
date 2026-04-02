import os
import subprocess
from pathlib import Path

from rich.console import Console

from jaspe.config import check_if_toml_exists, load_config
from jaspe.env_manager import _extract_min_python_version
from jaspe.ui import run_with_spinner


def _backend_env(backend_dir: Path) -> dict:
    env = dict(os.environ)
    env["VIRTUAL_ENV"] = str(backend_dir / ".venv")
    env.pop("CONDA_PREFIX", None)
    return env

console = Console()

DEFAULT_JASPE_TOML = """\
[config]
app_name = "{app_name}"
app_port = 8000
host = "127.0.0.1"
backend_folder = "backend"
frontend_folder = "frontend"

[git]
repo_url = ""
branch = "main"

[system]
autostart = true
restart_on_crash = true

[environment]
python_version = ">=3.11"
node_version = ">=20.0"

[backend]
entrypoint = "main:app"
migrations_dir = ""
api_prefix = "/api"

[frontend]
build_command = "npm run build"
dist_folder = "dist"
assets_prefix = "/assets"
"""

EMPTY_ENV_TOML = """\
[frontend]
# VITE_API_URL = "/api"

[backend]
# DATABASE_URL = "postgresql://user:pass@localhost/db"
# SECRET_KEY = "super_secret"
"""

DEFAULT_FASTAPI_MAIN = """\
from fastapi import FastAPI

app = FastAPI()


@app.get("/api/health")
async def health():
    return {"status": "ok"}
"""


def run_git_clone(url: str, target_dir: Path) -> None:
    run_with_spinner(["git", "clone", url, str(target_dir)], f"Clonage de {url}")


def create_directory(base: Path, name: str) -> Path:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def generate_default_jaspe_toml(target: Path, app_name: str) -> None:
    (target / "jaspe.toml").write_text(
        DEFAULT_JASPE_TOML.format(app_name=app_name), encoding="utf-8"
    )


def generate_empty_env_toml(target: Path) -> None:
    (target / ".env.toml").write_text(EMPTY_ENV_TOML, encoding="utf-8")


def run_uv_init(backend_dir: Path, python_version: str = "3.11") -> None:
    run_with_spinner(
        ["uv", "venv", "--python", python_version],
        f"Création du venv Python {python_version} avec uv",
        cwd=str(backend_dir),
    )

GITHUB_ACTIONS_TEMPLATE = """\
name: Deploy Jaspe App

on:
  push:
    branches: [ "main" ]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Déploiement via SSH sur VPS Jaspe
        uses: appleboy/ssh-action@v1.0.3
        with:
          host: ${{{{ secrets.VPS_HOST }}}}
          username: ${{{{ secrets.VPS_USER }}}}
          key: ${{{{ secrets.VPS_SSH_KEY }}}}
          script: |
            export PATH=$PATH:$HOME/.local/bin
            
            # Vérifie si le projet racine jaspe.toml est déjà initialisé
            if [ ! -f "{deploy_path}/jaspe.toml" ]; then
              jaspe init ${{{{ github.event.repository.clone_url }}}} {deploy_path}
              cd {deploy_path}
              jaspe start prod
            else
              cd {deploy_path}
              jaspe update
            fi
"""

def generate_github_actions_ci(target_dir: Path, app_name: str) -> None:
    workflows_dir = target_dir / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    deploy_yml = workflows_dir / "jaspe-deploy.yml"
    deploy_path = f"/var/www/{app_name}"
    deploy_yml.write_text(GITHUB_ACTIONS_TEMPLATE.format(deploy_path=deploy_path), encoding="utf-8")


def run_npm_init_vite(target_dir: Path, frontend_name: str = "frontend") -> None:
    run_with_spinner(
        ["npm", "create", "-y", "vite@latest", frontend_name, "--", "--template", "react-ts", "--no-interactive"],
        "Initialisation du frontend avec Vite (React-TS)",
        cwd=str(target_dir),
    )
    # Pre-install dependencies to make it fully ready to use
    run_with_spinner(["npm", "install"], "Installation silencieuse des dépendances Node.js initiales", cwd=str(target_dir / frontend_name))


def generate_default_fastapi_main(backend_dir: Path) -> None:
    (backend_dir / "main.py").write_text(DEFAULT_FASTAPI_MAIN, encoding="utf-8")


def init_from_scratch(target: Path) -> None:
    app_name = target.name
    console.print(f"[green]Création du projet '{app_name}'...[/green]")

    # Créer les dossiers
    backend_dir = create_directory(target, "backend")
    # Le frontend est créé par npm create vite

    # Fichiers de config Jaspe
    generate_default_jaspe_toml(target, app_name)
    generate_empty_env_toml(target)

    # Initialiser git
    subprocess.run(["git", "init"], cwd=str(target), check=True)

    # Backend : venv avec la bonne version Python + fichier main par défaut
    cfg = load_config(target / "jaspe.toml")
    py_version = _extract_min_python_version(cfg.environment.python_version)
    run_uv_init(backend_dir, py_version)
    generate_default_fastapi_main(backend_dir)
    
    # Intégration Continue (CI/CD Scaffold)
    generate_github_actions_ci(target, app_name)
    
    # Ensure venv is populated
    from jaspe.updater import run_uv_pip_sync
    run_uv_pip_sync(backend_dir)

    # Frontend : npm create vite
    run_npm_init_vite(target, "frontend")

    console.print(f"[green]Projet '{app_name}' initialisé avec succès ![/green]")


def init_from_clone(url: str, target: Path) -> None:
    run_git_clone(url, target)

    toml_path = target / "jaspe.toml"
    if not check_if_toml_exists(toml_path):
        console.print("[red]Erreur : jaspe.toml introuvable dans le dépôt cloné.[/red]")
        return

    cfg = load_config(toml_path)
    backend_dir = target / cfg.config.backend_folder
    frontend_dir = target / cfg.config.frontend_folder

    # Créer le venv avec la bonne version Python
    py_version = _extract_min_python_version(cfg.environment.python_version)
    run_uv_init(backend_dir, py_version)

    # Bootstrap des dépendances
    if (backend_dir / "requirements.txt").exists():
        run_with_spinner(
            ["uv", "pip", "install", "-r", "requirements.txt"],
            "Installation des dépendances Python depuis requirements.txt",
            cwd=str(backend_dir),
            env=_backend_env(backend_dir),
        )

    if (frontend_dir / "package.json").exists():
        run_with_spinner(["npm", "ci"], "Installation des dépendances Node (npm ci)", cwd=str(frontend_dir))

    # Créer un .env.toml vide si absent
    env_toml = target / ".env.toml"
    if not env_toml.exists():
        generate_empty_env_toml(target)
        console.print(
            "[yellow]Un fichier .env.toml vide a été créé. Pensez à le remplir.[/yellow]"
        )

    console.print("[green]Projet cloné et initialisé avec succès ![/green]")
