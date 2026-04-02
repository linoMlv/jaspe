import os
from pathlib import Path

import typer
from rich.console import Console

from rich.console import Console

from jaspe import registry, __version__
from jaspe.ui import run_with_spinner
from jaspe.config import load_config


def version_callback(value: bool):
    if value:
        print(f"{__version__}")
        raise typer.Exit()


app = typer.Typer(help="Jaspe — Déploiement zero-friction pour FastAPI + Vite/React/TS")


@app.callback()
def main(
    version: bool = typer.Option(
        None,
        "--version",
        "-v",
        callback=version_callback,
        is_eager=True,
        help="Affiche la version de Jaspe",
    ),
):
    pass
db_app = typer.Typer(help="Commandes pour la base de données (Alembic)")
app.add_typer(db_app, name="db")
console = Console()


def resolve_target_dir(app_name: str | None = None) -> Path:
    if app_name is None:
        return Path(os.getcwd())
    path = registry.get_app_path(app_name)
    if path is None:
        console.print(f"[red]Application '{app_name}' introuvable dans le registre.[/red]")
        raise typer.Exit(1)
    return Path(path)


@app.command()
def init(url: str = typer.Argument(None, help="URL du dépôt Git à cloner")):
    """Initialise un nouveau projet ou clone un projet existant."""
    from jaspe.init_cmd import init_from_clone, init_from_scratch

    target = Path(os.getcwd())
    if url:
        repo_name = url.rstrip("/").split("/")[-1].removesuffix(".git")
        init_from_clone(url, target / repo_name)
    else:
        init_from_scratch(target)


@app.command()
def start(
    mode: str = typer.Argument(..., help="Mode de lancement : dev ou prod"),
    share: bool = typer.Option(False, "--share", help="Partager l'environnement de développement sur le web via localtunnel"),
    skip_build: bool = typer.Option(False, "--skip-build", help="Passer l'étape de compilation Vite (mode prod)")
):
    """Lance l'application en mode dev ou prod."""
    from jaspe.dev_server import run_dev
    from jaspe.env_manager import (
        build_env_for_section,
        check_node_version,
        ensure_python_venv,
    )
    from jaspe.prod_server import (
        install_systemd_service,
        install_systemd_crons,
        generate_systemd_service_string,
        run_npm_build,
        write_runner,
        dry_run_asgi,
    )

    target = resolve_target_dir()
    cfg = load_config(target / "jaspe.toml")

    if not check_node_version(cfg.environment.node_version):
        raise typer.Exit(1)

    backend_path = target / cfg.config.backend_folder
    ensure_python_venv(cfg.environment.python_version, backend_path)

    front_env = build_env_for_section("frontend", target / ".env.toml", target)
    back_env = build_env_for_section("backend", target / ".env.toml", target)

    if mode == "dev":
        run_dev(
            target,
            target / cfg.config.frontend_folder,
            backend_path,
            cfg.backend.entrypoint,
            front_env,
            back_env,
            share,
        )
    elif mode == "prod":
        import getpass

        if not skip_build:
            run_npm_build(target / cfg.config.frontend_folder, front_env)
        write_runner(target, cfg)
        dry_run_asgi(target, cfg, back_env)

        user = getpass.getuser()
        service_content = generate_systemd_service_string(
            cfg, target, back_env, user
        )
        install_systemd_service(cfg.config.app_name, service_content)
        install_systemd_crons(cfg, target, back_env)
        registry.add_or_update_app(
            cfg.config.app_name, str(target), cfg.config.app_port, "active"
        )
        console.print(f"[green]Application '{cfg.config.app_name}' déployée en production ![/green]")
    else:
        console.print(f"[red]Mode inconnu : '{mode}'. Utilisez 'dev' ou 'prod'.[/red]")
        raise typer.Exit(1)


@app.command()
def stop(app_name: str = typer.Argument(None, help="Nom de l'application")):
    """Arrête une application en cours d'exécution."""
    import subprocess

    target = resolve_target_dir(app_name)
    cfg = load_config(target / "jaspe.toml")
    name = cfg.config.app_name
    service = f"jaspe-{name}.service"

    run_with_spinner(["systemctl", "--user", "stop", service], "Arrêt de l'application principale")
    for cron in cfg.crons:
        timer_name = f"jaspe-{name}-{cron.name}.timer"
        run_with_spinner(["systemctl", "--user", "stop", timer_name], f"Arrêt du cron {cron.name}", check=False)
    registry.add_or_update_app(name, str(target), cfg.config.app_port, "stopped")
    console.print(f"[green]Application '{name}' arrêtée avec succès.[/green]")


@app.command("list")
def list_apps():
    """Affiche la liste des applications enregistrées."""
    from rich.table import Table

    data = registry.read_registry()
    table = Table(title="Applications Jaspe")
    table.add_column("Nom", style="cyan")
    table.add_column("Port", style="magenta")
    table.add_column("Chemin", style="green")
    table.add_column("Statut", style="bold")

    for name, info in data["apps"].items():
        table.add_row(name, str(info["port"]), info["path"], info["status"])

    console.print(table)


@app.command()
def remove(app_name: str = typer.Argument(None, help="Nom de l'application")):
    """Supprime une application du registre et de systemd."""
    import subprocess

    target = resolve_target_dir(app_name)
    cfg = load_config(target / "jaspe.toml")
    name = cfg.config.app_name
    service = f"jaspe-{name}.service"

    run_with_spinner(["systemctl", "--user", "stop", service], "Arrêt du service", check=False)
    run_with_spinner(["systemctl", "--user", "disable", service], "Désactivation du service", check=False)
    
    user_systemd_dir = Path("~/.config/systemd/user").expanduser()
    service_file = user_systemd_dir / service
    if service_file.exists():
        service_file.unlink()
        
    for cron in cfg.crons:
        timer_name = f"jaspe-{name}-{cron.name}.timer"
        service_cron = f"jaspe-{name}-{cron.name}.service"
        run_with_spinner(["systemctl", "--user", "stop", timer_name], f"Arrêt du timer {cron.name}", check=False)
        run_with_spinner(["systemctl", "--user", "disable", timer_name], f"Désactivation du timer {cron.name}", check=False)
        t_path = user_systemd_dir / timer_name
        s_path = user_systemd_dir / service_cron
        if t_path.exists(): t_path.unlink()
        if s_path.exists(): s_path.unlink()
        
    run_with_spinner(["systemctl", "--user", "daemon-reload"], "Nettoyage du cache SystemD local", check=False)
        
    registry.remove_app(name)
    console.print(f"[green]Application '{name}' supprimée du registre.[/green]")


@app.command()
def update(app_name: str = typer.Argument(None, help="Nom de l'application")):
    """Met à jour une application déployée."""
    from jaspe.updater import run_full_update

    target = resolve_target_dir(app_name)
    cfg = load_config(target / "jaspe.toml")
    run_full_update(cfg, target)


@app.command()
def deploy():
    """Déploie intégralement l'application sur un VPS distant."""
    from jaspe.deployer import run_deploy

    target = resolve_target_dir()
    cfg = load_config(target / "jaspe.toml")

    if not cfg.deploy.target or not cfg.deploy.path:
        console.print("[red]Erreur : La section [deploy] (target et path) doit être configurée dans jaspe.toml.[/red]")
        raise typer.Exit(1)

    run_deploy(cfg, target)


@app.command("check-update")
def check_update(app_name: str = typer.Argument(None, help="Nom de l'application")):
    """Vérifie si une mise à jour est disponible."""
    from jaspe.updater import check_for_update

    target = resolve_target_dir(app_name)
    cfg = load_config(target / "jaspe.toml")
    check_for_update(cfg, target)


@app.command("front-add")
def front_add(
    pkg: str = typer.Argument(..., help="Nom du paquet npm"),
    dev: bool = typer.Option(False, "--dev", "-D", help="Ajouter comme dépendance de dev")
):
    """Ajoute un paquet npm au frontend."""
    from jaspe.deps import install_npm_exact

    target = resolve_target_dir()
    cfg = load_config(target / "jaspe.toml")
    frontend_path = target / cfg.config.frontend_folder
    install_npm_exact(pkg, frontend_path, dev=dev)


@app.command("back-add")
def back_add(pkg: str = typer.Argument(..., help="Nom du paquet Python")):
    """Ajoute un paquet Python au backend."""
    from jaspe.deps import add_backend_package

    target = resolve_target_dir()
    cfg = load_config(target / "jaspe.toml")
    backend_path = target / cfg.config.backend_folder
    add_backend_package(pkg, backend_path)


@db_app.command("make")
def db_make(message: str = typer.Argument(..., help="Message pour la migration")):
    """Génère une nouvelle migration (Alembic)."""
    import subprocess
    target = resolve_target_dir()
    cfg = load_config(target / "jaspe.toml")
    backend_path = target / cfg.config.backend_folder
    venv_python = backend_path / ".venv" / "bin" / "python"
    
    run_with_spinner([str(venv_python), "-m", "alembic", "revision", "--autogenerate", "-m", message], f"Création de la migration '{message}'", cwd=str(backend_path))
    console.print("[green]Migration générée avec succès ![/green]")


@db_app.command("reset")
def db_reset():
    """Vider complètement et rejouer toutes les migrations locales."""
    import subprocess
    confirm = typer.confirm("Êtes-vous sûr de vouloir tout effacer et rejouer les migrations en partant de 0 ?")
    if not confirm:
        return
        
    target = resolve_target_dir()
    cfg = load_config(target / "jaspe.toml")
    backend_path = target / cfg.config.backend_folder
    venv_python = backend_path / ".venv" / "bin" / "python"
    
    run_with_spinner([str(venv_python), "-m", "alembic", "downgrade", "base"], "Vidage de la base de données (downgrade base)", cwd=str(backend_path), check=False)
    run_with_spinner([str(venv_python), "-m", "alembic", "upgrade", "head"], "Reconstruction (upgrade head)", cwd=str(backend_path))
    console.print("[green]Reset de la base de données terminé.[/green]")


@app.command("logs")
def logs_cmd(
    app_name: str = typer.Argument(None, help="Nom de l'application (optionnel si dans le dossier)"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Suivre les logs en continu"),
    cron: str = typer.Option(None, "--cron", help="Afficher les logs d'un cron spécifique (optionnel)")
):
    """Lit les journaux de production via systemd/journalctl."""
    import subprocess
    if app_name is None:
        try:
            target = resolve_target_dir()
            cfg = load_config(target / "jaspe.toml")
            app_name = cfg.config.app_name
        except Exception:
            console.print("[red]Le nom de l'application doit être fourni si vous n'êtes pas dans le dossier du projet.[/red]")
            raise typer.Exit(1)
            
    if cron:
        service = f"jaspe-{app_name}-{cron}.service"
    else:
        service = f"jaspe-{app_name}.service"
        
    cmd = ["journalctl", "--user", "--no-pager", "-u", service]
    if follow:
        cmd.append("-f")
        
    console.print(f"[blue]Logs pour {service}...[/blue]")
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        pass
