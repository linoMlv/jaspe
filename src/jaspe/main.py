import os
from pathlib import Path

import typer
from rich.console import Console

from rich.console import Console
from rich.prompt import Confirm

from jaspe import registry, __version__
from jaspe.ui import run_with_spinner
from jaspe.config import load_config
from jaspe.integrity import audit_and_prompt_reload, update_stored_hashes


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
    from jaspe.reload_cmd import run_reload

    target = Path(os.getcwd())
    
    # 🛡️ Protection : Si un projet existe déjà
    if not url and (target / "jaspe.toml").exists():
        console.print("[yellow]⚠️  Un projet Jaspe est déjà présent dans ce dossier.[/yellow]")
        if Confirm.ask("Souhaitez-vous réinitialiser l'environnement (reload) de ce projet à la place ?"):
            cfg = load_config(target / "jaspe.toml")
            # Appel de la logique de reload avec redirection si c'était actif
            was_active = run_reload(cfg, target)
            if was_active:
                console.print("[blue]Relance de l'application en mode production...[/blue]")
                import subprocess
                subprocess.run(["jaspe", "start", "prod"], cwd=str(target))
            return
        else:
            console.print("[red]Opération annulée pour protéger le projet existant.[/red]")
            raise typer.Exit()

    if url:
        repo_name = url.rstrip("/").split("/")[-1].removesuffix(".git")
        final_target = target / repo_name
        init_from_clone(url, final_target)
        # Update hashes after clone
        cfg = load_config(final_target / "jaspe.toml")
        update_stored_hashes(final_target, cfg)
    else:
        init_from_scratch(target)
        # Update hashes after scratch init
        cfg = load_config(target / "jaspe.toml")
        update_stored_hashes(target, cfg)


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

    # 🛡️ Audit d'Intégrité
    audit_and_prompt_reload(target, cfg)

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
        from jaspe.prod_server import start_app_production
        start_app_production(cfg, target, skip_build=skip_build)
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
    from jaspe.prod_server import remove_app_production

    target = resolve_target_dir(app_name)
    cfg = load_config(target / "jaspe.toml")
    remove_app_production(cfg, target)


@app.command()
def update(
    app_name: str = typer.Argument(None, help="Nom de l'application"),
    reload: bool = typer.Option(False, "--reload", help="Réinitialiser l'environnement avant la mise à jour"),
    skip_build: bool = typer.Option(False, "--skip-build", help="Passer l'étape de build du frontend")
):
    """Met à jour une application déployée."""
    from jaspe.updater import run_full_update

    target = resolve_target_dir(app_name)
    cfg = load_config(target / "jaspe.toml")
    
    # 🛡️ Audit d'Intégrité
    audit_and_prompt_reload(target, cfg)
    
    run_full_update(cfg, target, reload=reload, skip_build=skip_build)
    
    # Update hashes after successful update
    update_stored_hashes(target, cfg)


@app.command()
def reload(
    app_name: str = typer.Argument(None, help="Nom de l'application"),
    clean_cache: bool = typer.Option(False, "--clean-cache", help="Vider les caches globaux UV et NPM")
):
    """Réinitialise complètement l'environnement de l'application (Hard-Reset)."""
    from jaspe.reload_cmd import run_reload
    from jaspe.prod_server import remove_app_production, start_app_production

    target = resolve_target_dir(app_name)
    cfg = load_config(target / "jaspe.toml")
    
    # 1. Audit d'état pou savoir s'il faut relancer à la fin
    name = cfg.config.app_name
    service = f"jaspe-{name}.service"
    import subprocess
    res = subprocess.run(["systemctl", "--user", "is-active", service], capture_output=True, text=True)
    was_active = res.stdout.strip() == "active"

    # 2. Reload logic (Confirmation + Filesystem reset & Install)
    # On passe was_active=False à run_reload car on va gérer le stop/start proprement ici via remove/start_production
    success = run_reload(cfg, target, clean_cache=clean_cache, perform_stop=was_active)
    
    if success and was_active:
        console.print("[blue]Relance de l'application en mode production...[/blue]")
        start_app_production(cfg, target, skip_build=False)
        
    # Update hashes after successful reload
    update_stored_hashes(target, cfg)


@app.command()
def deploy(
    app_name: str = typer.Argument(None, help="Nom de l'application"),
    reload: bool = typer.Option(False, "--reload", help="Réinitialiser l'environnement distant lors du déploiement"),
    skip_build: bool = typer.Option(False, "--skip-build", help="Passer l'étape de build du frontend lors du déploiement (utile si déjà buildé localement)")
):
    """Déploie intégralement l'application sur un VPS distant."""
    from jaspe.deployer import run_deploy

    target = resolve_target_dir(app_name)
    cfg = load_config(target / "jaspe.toml")

    # 🛡️ Audit d'Intégrité
    audit_and_prompt_reload(target, cfg)

    if not cfg.deploy.target or not cfg.deploy.path:
        console.print("[red]Erreur : La section [deploy] (target et path) doit être configurée dans jaspe.toml.[/red]")
        raise typer.Exit(1)

    run_deploy(cfg, target, reload=reload, skip_build=skip_build)


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
    
    # Update hashes after adding dependency
    update_stored_hashes(target, cfg)


@app.command("back-add")
def back_add(pkg: str = typer.Argument(..., help="Nom du paquet Python")):
    """Ajoute un paquet Python au backend."""
    from jaspe.deps import add_backend_package

    target = resolve_target_dir()
    cfg = load_config(target / "jaspe.toml")
    backend_path = target / cfg.config.backend_folder
    add_backend_package(pkg, backend_path)
    
    # Update hashes after adding dependency
    update_stored_hashes(target, cfg)


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
