import subprocess
from pathlib import Path

from rich.console import Console

from rich.console import Console
from jaspe.ui import run_with_spinner
from jaspe.config import JaspeConfig

ASGI_WRAPPER_TEMPLATE = """\
import sys
sys.path.insert(0, "{backend_abs}")

from {module} import {attr} as user_app
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

user_app.mount("{assets_prefix}", StaticFiles(directory="{dist_abs}/assets"), name="assets")

@user_app.exception_handler(404)
async def custom_404_handler(request, exc):
    if request.url.path.startswith("{api_prefix}"):
        return JSONResponse({{"detail": "Not Found"}}, status_code=404)
    return FileResponse("{dist_abs}/index.html")
"""

SYSTEMD_TEMPLATE = """\
[Unit]
Description=Jaspe - {app_name}
After=network.target

[Service]
Type=simple
WorkingDirectory={project_path}
{env_lines}
Environment=PYTHONPATH={jaspe_dir}
ExecStart={venv_python} -m uvicorn runner:user_app --host {host} --port {port}
Restart={restart}

[Install]
WantedBy=default.target
"""

CRON_SERVICE_TEMPLATE = """\
[Unit]
Description=Jaspe Cron - {app_name} - {cron_name}
After=network.target

[Service]
Type=oneshot
WorkingDirectory={project_path}
{env_lines}
Environment=PYTHONPATH={jaspe_dir}
ExecStart={venv_python} {cron_command}
"""

CRON_TIMER_TEMPLATE = """\
[Unit]
Description=Jaspe Cron Timer - {app_name} - {cron_name}

[Timer]
OnCalendar={cron_schedule}
Persistent=true

[Install]
WantedBy=timers.target
"""


def run_npm_build(frontend_path: Path, env: dict) -> None:
    run_with_spinner(
        ["npm", "run", "build"],
        "Build du frontend pour la production",
        cwd=str(frontend_path),
        env=env,
    )


def create_hidden_jaspe_dir(project_path: Path) -> Path:
    d = project_path / ".jaspe"
    d.mkdir(exist_ok=True)
    return d


def generate_asgi_wrapper_string(config: JaspeConfig, project_path: Path) -> str:
    module, attr = config.backend.entrypoint.split(":")
    backend_abs = str(project_path / config.config.backend_folder)
    dist_abs = str(project_path / config.config.frontend_folder / config.frontend.dist_folder)
    api_prefix = config.backend.api_prefix.rstrip("/")
    assets_prefix = config.frontend.assets_prefix.rstrip("/")
    return ASGI_WRAPPER_TEMPLATE.format(
        backend_abs=backend_abs,
        module=module,
        attr=attr,
        dist_abs=dist_abs,
        api_prefix=api_prefix,
        assets_prefix=assets_prefix,
    )


def write_runner(project_path: Path, config: JaspeConfig) -> Path:
    jaspe_dir = create_hidden_jaspe_dir(project_path)
    runner = jaspe_dir / "runner.py"
    runner.write_text(
        generate_asgi_wrapper_string(config, project_path), encoding="utf-8"
    )
    return runner


def generate_systemd_service_string(
    config: JaspeConfig,
    project_path: Path,
    env: dict,
    user: str,
) -> str:
    env_lines = "\n".join(
        f"Environment={k}={v}" for k, v in env.items() if k not in ("PATH", "HOME", "USER")
    )
    restart = "always" if config.system.restart_on_crash else "no"
    jaspe_dir = str(project_path / ".jaspe")
    venv_python = str(project_path / config.config.backend_folder / ".venv" / "bin" / "python")
    return SYSTEMD_TEMPLATE.format(
        app_name=config.config.app_name,
        project_path=project_path,
        env_lines=env_lines,
        jaspe_dir=jaspe_dir,
        venv_python=venv_python,
        host=config.config.host,
        port=config.config.app_port,
        restart=restart,
    )


def install_systemd_service(app_name: str, service_content: str) -> None:
    service_name = f"jaspe-{app_name}.service"
    
    # Path inside ~/.config/systemd/user/
    user_systemd_dir = Path("~/.config/systemd/user").expanduser()
    user_systemd_dir.mkdir(parents=True, exist_ok=True)
    
    target_path = user_systemd_dir / service_name
    target_path.write_text(service_content, encoding="utf-8")

    run_with_spinner(["systemctl", "--user", "daemon-reload"], "Rechargement du Daemon SystemD local")
    run_with_spinner(["systemctl", "--user", "enable", service_name], f"Activation permanente du service '{service_name}'")
    run_with_spinner(["systemctl", "--user", "start", service_name], f"Démarrage de l'application '{service_name}'")
    
    # Ensure lingering is enabled for the current user
    import getpass
    user = getpass.getuser()
    subprocess.run(["loginctl", "enable-linger", user], check=False)

    console.print(f"[green]Service systemd '{service_name}' démarré.[/green]")


def install_systemd_crons(config: JaspeConfig, project_path: Path, env: dict) -> None:
    if not config.crons:
        return
        
    env_lines = "\n".join(
        f"Environment={k}={v}" for k, v in env.items() if k not in ("PATH", "HOME", "USER")
    )
    jaspe_dir = str(project_path / ".jaspe")
    venv_python = str(project_path / config.config.backend_folder / ".venv" / "bin" / "python")
    app_name = config.config.app_name
    
    user_systemd_dir = Path("~/.config/systemd/user").expanduser()
    user_systemd_dir.mkdir(parents=True, exist_ok=True)
    
    for cron in config.crons:
        service_name = f"jaspe-{app_name}-{cron.name}.service"
        timer_name = f"jaspe-{app_name}-{cron.name}.timer"
        
        service_content = CRON_SERVICE_TEMPLATE.format(
            app_name=app_name,
            cron_name=cron.name,
            project_path=project_path,
            env_lines=env_lines,
            jaspe_dir=jaspe_dir,
            venv_python=venv_python,
            cron_command=cron.command,
        )
        timer_content = CRON_TIMER_TEMPLATE.format(
            app_name=app_name,
            cron_name=cron.name,
            cron_schedule=cron.schedule,
        )
        
        (user_systemd_dir / service_name).write_text(service_content, encoding="utf-8")
        (user_systemd_dir / timer_name).write_text(timer_content, encoding="utf-8")
        
        run_with_spinner(["systemctl", "--user", "daemon-reload"], "Actualisation du lanceur de tâche SystemD")
        run_with_spinner(["systemctl", "--user", "enable", timer_name], f"Activation du timer autonome '{timer_name}'")
        run_with_spinner(["systemctl", "--user", "start", timer_name], f"Démarrage de l'horloge '{timer_name}'")
        
        console.print(f"[green]✓ Cron Timer '{timer_name}' solidement arrimé en arrière-plan.[/green]")
