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


app = typer.Typer(help="Jaspe — Zero-friction deployment for FastAPI + Vite/React/TS")


@app.callback()
def main(
    version: bool = typer.Option(
        None,
        "--version",
        "-v",
        callback=version_callback,
        is_eager=True,
        help="Show Jaspe version",
    ),
):
    pass
db_app = typer.Typer(help="Database management commands (Alembic)")
app.add_typer(db_app, name="db")
console = Console()


def resolve_target_dir(app_name: str | None = None) -> Path:
    if app_name is None:
        return Path(os.getcwd())
    path = registry.get_app_path(app_name)
    if path is None:
        console.print(f"[red]Application '{app_name}' not found in registry.[/red]")
        raise typer.Exit(1)
    return Path(path)


@app.command()
def init(url: str = typer.Argument(None, help="Git repository URL to clone")):
    """Initialize a new project or clone an existing one."""
    from jaspe.init_cmd import init_from_clone, init_from_scratch
    from jaspe.reload_cmd import run_reload

    target = Path(os.getcwd())
    
    # 🛡️ Protection : Si un projet existe déjà
    if not url and (target / "jaspe.toml").exists():
        console.print("[yellow]⚠️  A Jaspe project is already present in this directory.[/yellow]")
        if Confirm.ask("Would you like to re-initialize (reload) the environment for this project instead?"):
            cfg = load_config(target / "jaspe.toml")
            # Appel de la logique de reload avec redirection si c'était actif
            was_active = run_reload(cfg, target)
            if was_active:
                console.print("[blue]Restarting application in production mode...[/blue]")
                import subprocess
                subprocess.run(["jaspe", "start", "prod"], cwd=str(target))
            return
        else:
            console.print("[red]Operation cancelled to protect existing project.[/red]")
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
    mode: str = typer.Argument(..., help="Launch mode: dev or prod"),
    share: bool = typer.Option(False, "--share", help="Share the development environment via localtunnel"),
    skip_build: bool = typer.Option(False, "--skip-build", help="Skip Vite build step (prod mode)")
):
    """Start the application in dev or prod mode."""
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
        console.print(f"[red]Unknown mode: '{mode}'. Use 'dev' or 'prod'.[/red]")
        raise typer.Exit(1)


@app.command()
def stop(app_name: str = typer.Argument(None, help="Application name")):
    """Stop a running application."""
    import subprocess

    target = resolve_target_dir(app_name)
    cfg = load_config(target / "jaspe.toml")
    name = cfg.config.app_name
    service = f"jaspe-{name}.service"

    run_with_spinner(["systemctl", "--user", "stop", service], "Stopping primary application...")
    for cron in cfg.crons:
        timer_name = f"jaspe-{name}-{cron.name}.timer"
        run_with_spinner(["systemctl", "--user", "stop", timer_name], f"Stopping cron {cron.name}...", check=False)
    registry.add_or_update_app(name, str(target), cfg.config.app_port, "stopped")
    console.print(f"[green]Application '{name}' stopped successfully.[/green]")


@app.command("list")
def list_apps():
    """List all registered applications."""
    from rich.table import Table

    data = registry.read_registry()
    table = Table(title="Jaspe Applications")
    table.add_column("Name", style="cyan")
    table.add_column("Port", style="magenta")
    table.add_column("Path", style="green")
    table.add_column("Status", style="bold")

    for name, info in data["apps"].items():
        table.add_row(name, str(info["port"]), info["path"], info["status"])

    console.print(table)

@app.command()
def remove(app_name: str = typer.Argument(None, help="Application name")):
    """Remove an application from registry and systemd."""
    from jaspe.prod_server import remove_app_production

    target = resolve_target_dir(app_name)
    cfg = load_config(target / "jaspe.toml")
    remove_app_production(cfg, target)


@app.command()
def update(
    app_name: str = typer.Argument(None, help="Application name"),
    reload: bool = typer.Option(False, "--reload", help="Reset environment before update"),
    skip_build: bool = typer.Option(False, "--skip-build", help="Skip frontend build step")
):
    """Update a deployed application."""
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
    app_name: str = typer.Argument(None, help="Application name"),
    clean_cache: bool = typer.Option(False, "--clean-cache", help="Clear global UV and NPM caches")
):
    """Hard-Reset application environment."""
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
        console.print("[blue]Restarting application in production mode...[/blue]")
        start_app_production(cfg, target, skip_build=False)
        
    # Update hashes after successful reload
    update_stored_hashes(target, cfg)


@app.command()
def deploy(
    app_name: str = typer.Argument(None, help="Application name"),
    reload: bool = typer.Option(False, "--reload", help="Reset remote environment during deployment"),
    skip_build: bool = typer.Option(False, "--skip-build", help="Skip frontend build (e.g. if already built locally)")
):
    """Deploy application to a remote VPS."""
    from jaspe.deployer import run_deploy

    target = resolve_target_dir(app_name)
    cfg = load_config(target / "jaspe.toml")

    # 🛡️ Audit d'Intégrité
    audit_and_prompt_reload(target, cfg)

    if not cfg.deploy.target or not cfg.deploy.path:
        console.print("[red]Error: [deploy] section (target and path) must be configured in jaspe.toml.[/red]")
        raise typer.Exit(1)

    run_deploy(cfg, target, reload=reload, skip_build=skip_build)


@app.command("check-update")
def check_update(app_name: str = typer.Argument(None, help="Application name")):
    """Check if an update is available."""
    from jaspe.updater import check_for_update

    target = resolve_target_dir(app_name)
    cfg = load_config(target / "jaspe.toml")
    check_for_update(cfg, target)


@app.command("front-add")
def front_add(
    pkg: str = typer.Argument(..., help="NPM package name"),
    dev: bool = typer.Option(False, "--dev", "-D", help="Add as dev dependency")
):
    """Add an NPM package to the frontend."""
    from jaspe.deps import install_npm_exact

    target = resolve_target_dir()
    cfg = load_config(target / "jaspe.toml")
    frontend_path = target / cfg.config.frontend_folder
    install_npm_exact(pkg, frontend_path, dev=dev)
    
    # Update hashes after adding dependency
    update_stored_hashes(target, cfg)


@app.command("back-add")
def back_add(pkg: str = typer.Argument(..., help="Python package name")):
    """Add a Python package to the backend."""
    from jaspe.deps import add_backend_package

    target = resolve_target_dir()
    cfg = load_config(target / "jaspe.toml")
    backend_path = target / cfg.config.backend_folder
    add_backend_package(pkg, backend_path)
    
    # Update hashes after adding dependency
    update_stored_hashes(target, cfg)


@db_app.command("make")
def db_make(message: str = typer.Argument(..., help="Migration message")):
    """Generate a new migration (Alembic)."""
    import subprocess
    target = resolve_target_dir()
    cfg = load_config(target / "jaspe.toml")
    backend_path = target / cfg.config.backend_folder
    venv_python = backend_path / ".venv" / "bin" / "python"
    
    run_with_spinner([str(venv_python), "-m", "alembic", "revision", "--autogenerate", "-m", message], f"Creating migration '{message}'...", cwd=str(backend_path))
    console.print("[green]Migration generated successfully.[/green]")


@db_app.command("reset")
def db_reset():
    """Clear and replay all migrations from scratch."""
    import subprocess
    confirm = typer.confirm("Are you sure you want to clear and re-run all migrations? This data will be lost.")
    if not confirm:
        return
        
    target = resolve_target_dir()
    cfg = load_config(target / "jaspe.toml")
    backend_path = target / cfg.config.backend_folder
    venv_python = backend_path / ".venv" / "bin" / "python"
    
    run_with_spinner([str(venv_python), "-m", "alembic", "downgrade", "base"], "Downgrading database to base...", cwd=str(backend_path), check=False)
    run_with_spinner([str(venv_python), "-m", "alembic", "upgrade", "head"], "Upgrading database to head...", cwd=str(backend_path))
    console.print("[green]Database reset completed successfully.[/green]")


@app.command("logs")
def logs_cmd(
    app_name: str = typer.Argument(None, help="Application name (optional if in project dir)"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow logs (real-time)"),
    cron: str = typer.Option(None, "--cron", help="Show logs for a specific cron job (optional)")
):
    """View production logs via systemd/journalctl."""
    import subprocess
    if app_name is None:
        try:
            target = resolve_target_dir()
            cfg = load_config(target / "jaspe.toml")
            app_name = cfg.config.app_name
        except Exception:
            console.print("[red]Application name must be provided if not in project directory.[/red]")
            raise typer.Exit(1)
            
    if cron:
        service = f"jaspe-{app_name}-{cron}.service"
    else:
        service = f"jaspe-{app_name}.service"
        
    cmd = ["journalctl", "--user", "--no-pager", "-u", service]
    if follow:
        cmd.append("-f")
        
    console.print(f"[blue]Displaying logs for {service}...[/blue]")
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    app()
