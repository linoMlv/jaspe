import subprocess
import time
import http.client
from pathlib import Path

from rich.console import Console
from jaspe.ui import run_with_spinner
from jaspe.config import JaspeConfig
from jaspe import registry

console = Console()

ASGI_WRAPPER_TEMPLATE = """\
import sys
import os
import inspect
import asyncio

sys.path.insert(0, "{backend_abs}")

from {module} import {attr} as user_app
from starlette.staticfiles import StaticFiles
from starlette.responses import FileResponse

# --- Factory Pattern support (async, callable, default args) ---
if callable(user_app) and not isinstance(user_app, type):
    try:
        sig = inspect.signature(user_app)
        if all(
            p.default is not inspect.Parameter.empty
            for p in sig.parameters.values()
        ):
            result = user_app()
            if asyncio.iscoroutine(result):
                result = asyncio.get_event_loop().run_until_complete(result)
            user_app = result
    except (ValueError, TypeError):
        pass

# --- Constants injected from jaspe.toml ---
DIST_DIR = "{dist_abs}"
API_PREFIX = "{api_prefix}"
ASSETS_PREFIX = "{assets_prefix}"
ASSETS_DIR = os.path.join(DIST_DIR, "assets")
INDEX_HTML = os.path.join(DIST_DIR, "index.html")
DIST_REALPATH = os.path.realpath(DIST_DIR)

static_app = StaticFiles(directory=ASSETS_DIR) if os.path.isdir(ASSETS_DIR) else None


def _looks_like_file(path: str) -> bool:
    last = path.rsplit("/", 1)[-1]
    return "." in last


class JaspeWrapper:
    \"\"\"
    Wrapper ASGI transparent — ne monte PAS l'app utilisateur.
    Intercepte uniquement les fichiers statiques et le fallback SPA.
    user_app conserve son lifespan, middlewares, exception handlers.
    \"\"\"

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        # 1. Lifespan & WebSocket → forward directly to user_app
        if scope["type"] in ("lifespan", "websocket"):
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # 2. Serve Vite assets directly
        if path.startswith(ASSETS_PREFIX) and static_app:
            scope = dict(scope)
            scope["path"] = path[len(ASSETS_PREFIX):] or "/"
            await static_app(scope, receive, send)
            return

        # 3. API routes → forward to user_app (preserves its middlewares, handlers)
        if path.startswith(API_PREFIX):
            await self.app(scope, receive, send)
            return

        # 4. Root static files (favicon.ico, robots.txt, etc.)
        #    With path traversal protection
        candidate = os.path.realpath(os.path.join(DIST_DIR, path.lstrip("/")))
        if candidate.startswith(DIST_REALPATH + os.sep) and os.path.isfile(candidate):
            response = FileResponse(candidate)
            await response(scope, receive, send)
            return

        # 5. Try user_app first (preserves /docs, /openapi.json, custom routes)
        #    If 404 and not a file-like path → fallback SPA
        status_code = None
        headers_sent = False
        swallow_body = False

        async def capture_send(message):
            nonlocal status_code, headers_sent, swallow_body
            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
                if status_code == 404 and not _looks_like_file(path):
                    swallow_body = True
                    return
                headers_sent = True
                await send(message)
            elif swallow_body and message["type"] == "http.response.body":
                return
            else:
                await send(message)

        try:
            await self.app(scope, receive, capture_send)
        except Exception:
            if not headers_sent and not _looks_like_file(path) and os.path.isfile(INDEX_HTML):
                response = FileResponse(INDEX_HTML)
                await response(scope, receive, send)
                return
            raise

        if status_code == 404 and not _looks_like_file(path) and os.path.isfile(INDEX_HTML):
            response = FileResponse(INDEX_HTML)
            await response(scope, receive, send)


# The ASGI app exposed to uvicorn
jaspe_app = JaspeWrapper(user_app)
"""

SYSTEMD_TEMPLATE = """\
[Unit]
Description=Jaspe - {app_name}
After=network.target

[Service]
Type=simple
WorkingDirectory={project_path}
EnvironmentFile={env_file_path}
Environment=PYTHONPATH={jaspe_dir}
ExecStart={venv_python} -m uvicorn runner:jaspe_app --host {host} --port {port}
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
EnvironmentFile={env_file_path}
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
        "Building frontend for production...",
        cwd=str(frontend_path),
        env=env,
    )


def create_hidden_jaspe_dir(project_path: Path) -> Path:
    d = project_path / ".jaspe"
    d.mkdir(exist_ok=True)
    return d


def write_env_file(project_path: Path, env: dict) -> Path:
    """Écrit les variables d'environnement dans un fichier dédié pour EnvironmentFile= systemd.

    Ce format ne souffre pas des problèmes d'échappement de Environment=
    (virgules interprétées comme séparateurs, $ comme expansion de variable).
    """
    jaspe_dir = create_hidden_jaspe_dir(project_path)
    env_file = jaspe_dir / "env"
    skip = {"PATH", "HOME", "USER"}
    lines = []
    for k, v in env.items():
        if k not in skip:
            val = str(v).replace("\\", "\\\\").replace("\n", "\\n").replace("$", "\\$")
            lines.append(f"{k}={val}")
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return env_file


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
    env_file = write_env_file(project_path, env)
    restart = "always" if config.system.restart_on_crash else "no"
    jaspe_dir = str(project_path / ".jaspe")
    venv_python = str(project_path / config.config.backend_folder / ".venv" / "bin" / "python")
    return SYSTEMD_TEMPLATE.format(
        app_name=config.config.app_name,
        project_path=project_path,
        env_file_path=env_file,
        jaspe_dir=jaspe_dir,
        venv_python=venv_python,
        host=config.config.host,
        port=config.config.app_port,
        restart=restart,
    )


def dry_run_asgi(project_path: Path, config: JaspeConfig, env: dict) -> None:
    jaspe_dir = str(project_path / ".jaspe")
    venv_python = str(project_path / config.config.backend_folder / ".venv" / "bin" / "python")
    run_with_spinner(
        [venv_python, "-c", "import runner"],
        "Performing application health check (Dry-Run)...",
        cwd=jaspe_dir,
        env=env,
    )


def install_systemd_service(app_name: str, service_content: str) -> None:
    service_name = f"jaspe-{app_name}.service"

    # Path inside ~/.config/systemd/user/
    user_systemd_dir = Path("~/.config/systemd/user").expanduser()
    user_systemd_dir.mkdir(parents=True, exist_ok=True)

    target_path = user_systemd_dir / service_name
    target_path.write_text(service_content, encoding="utf-8")

    run_with_spinner(["systemctl", "--user", "daemon-reload"], "Reloading local SystemD daemon...")
    run_with_spinner(["systemctl", "--user", "enable", service_name], f"Enabling service '{service_name}'...")
    run_with_spinner(["systemctl", "--user", "start", service_name], f"Starting application '{service_name}'...")

    # Ensure lingering is enabled for the current user
    import getpass
    user = getpass.getuser()
    subprocess.run(["loginctl", "enable-linger", user], check=False)

    console.print(f"[green]SystemD service '{service_name}' started.[/green]")


def wait_for_health_check(host: str, port: int, timeout: int = 10) -> bool:
    """Attente active du démarrage de l'application (Health Check)."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            conn = http.client.HTTPConnection(host, port, timeout=2)
            conn.request("GET", "/")
            response = conn.getresponse()
            # On considère que toute réponse (même 404/401) signifie que le serveur écoute
            if response.status:
                conn.close()
                return True
        except (ConnectionRefusedError, http.client.HTTPException, Exception):
            pass
        time.sleep(1)
    return False


def install_systemd_crons(config: JaspeConfig, project_path: Path, env: dict) -> None:
    if not config.crons:
        return

    env_file = write_env_file(project_path, env)
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
            env_file_path=env_file,
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

    run_with_spinner(["systemctl", "--user", "daemon-reload"], "Updating SystemD task scheduler...")
    for cron in config.crons:
        timer_name = f"jaspe-{app_name}-{cron.name}.timer"
        run_with_spinner(["systemctl", "--user", "enable", timer_name], f"Enabling autonomous timer '{timer_name}'...")
        run_with_spinner(["systemctl", "--user", "start", timer_name], f"Starting clock for '{timer_name}'...")

    console.print(f"[green]✓ Cron Timer '{timer_name}' scheduled in background.[/green]")


def remove_app_production(cfg: JaspeConfig, target: Path) -> None:
    """Arrête et supprime tous les composants de production (SystemD + Registre)."""
    name = cfg.config.app_name
    service = f"jaspe-{name}.service"
    user_systemd_dir = Path("~/.config/systemd/user").expanduser()

    # 1. Stop primary service
    run_with_spinner(["systemctl", "--user", "stop", service], f"Stopping service '{service}'...", check=False)
    run_with_spinner(["systemctl", "--user", "disable", service], f"Disabling service '{service}'...", check=False)

    service_file = user_systemd_dir / service
    if service_file.exists():
        service_file.unlink()

    # 2. Stop crons
    for cron in cfg.crons:
        timer_name = f"jaspe-{name}-{cron.name}.timer"
        service_cron = f"jaspe-{name}-{cron.name}.service"
        run_with_spinner(["systemctl", "--user", "stop", timer_name], f"Stopping timer {cron.name}...", check=False)
        run_with_spinner(["systemctl", "--user", "disable", timer_name], f"Disabling timer {cron.name}...", check=False)
        t_path = user_systemd_dir / timer_name
        s_path = user_systemd_dir / service_cron
        if t_path.exists(): t_path.unlink()
        if s_path.exists(): s_path.unlink()

    # 3. Cleanup SystemD
    run_with_spinner(["systemctl", "--user", "daemon-reload"], "Cleaning local SystemD cache...", check=False)

    # 4. Registry
    registry.remove_app(name)
    console.print(f"[green]Application '{name}' removed from production.[/green]")


def start_app_production(cfg: JaspeConfig, target: Path, skip_build: bool = False, health_check: bool = True) -> None:
    """Orchestre le build et le lancement en production."""
    from jaspe.env_manager import build_env_for_section
    import getpass

    front_env = build_env_for_section("frontend", target / ".env.toml", target)
    back_env = build_env_for_section("backend", target / ".env.toml", target)

    if not skip_build:
        run_npm_build(target / cfg.config.frontend_folder, front_env)

    write_runner(target, cfg)
    dry_run_asgi(target, cfg, back_env)

    user = getpass.getuser()
    service_content = generate_systemd_service_string(cfg, target, back_env, user)
    install_systemd_service(cfg.config.app_name, service_content)
    install_systemd_crons(cfg, target, back_env)

    # Registry entry
    cron_names = [c.name for c in cfg.crons]
    registry.add_or_update_app(cfg.config.app_name, str(target), cfg.config.app_port, "active", cron_names=cron_names)

    if health_check:
        run_with_spinner(lambda: wait_for_health_check(cfg.config.host, cfg.config.app_port), f"Waiting for application to respond on port {cfg.config.app_port}...")
        if not wait_for_health_check(cfg.config.host, cfg.config.app_port, timeout=1):
            console.print(f"\n[bold red]❌ Health Check Failed: Application is not responding on http://{cfg.config.host}:{cfg.config.app_port}[/]")
            console.print("[yellow]Automatically stopping the broken application to prevent zombie process...[/]")
            remove_app_production(cfg, target)
            raise Exception("Application failed to start properly (Health Check timeout).")

    url = f"http://{cfg.config.host}:{cfg.config.app_port}"
    console.print(f"\n[bold green]🚀 Application '{cfg.config.app_name}' successfully launched in production![/]")
    console.print(f"[blue]Link: {url}[/blue]")
