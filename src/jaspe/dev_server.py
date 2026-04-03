import subprocess
import threading
from queue import Empty, Queue
from pathlib import Path

from rich.console import Console

console = Console()


def start_vite_process(frontend_path: Path, env: dict) -> subprocess.Popen:
    return subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=str(frontend_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        text=True,
    )


def start_uvicorn_process(
    backend_path: Path, entrypoint: str, env: dict
) -> subprocess.Popen:
    venv_python = str(backend_path / ".venv" / "bin" / "python")
    return subprocess.Popen(
        [venv_python, "-m", "uvicorn", entrypoint, "--reload"],
        cwd=str(backend_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        text=True,
    )


def enqueue_output(
    process: subprocess.Popen, prefix: str, queue: Queue
) -> None:
    for line in iter(process.stdout.readline, ""):
        queue.put((prefix, line.rstrip("\n")))
    process.stdout.close()


def get_mtimes(target: Path) -> dict:
    mtimes = {}
    for filename in ("jaspe.toml", ".env.toml"):
        p = target / filename
        mtimes[filename] = p.stat().st_mtime if p.exists() else 0
    return mtimes


def run_dev(
    target: Path,
    frontend_path: Path,
    backend_path: Path,
    entrypoint: str,
    front_env: dict,
    back_env: dict,
    share: bool = False,
) -> None:
    from jaspe.env_manager import build_env_for_section

    last_mtimes = get_mtimes(target)

    while True:
        log_queue: Queue = Queue()

        vite_proc = start_vite_process(frontend_path, front_env)
        uvicorn_proc = start_uvicorn_process(backend_path, entrypoint, back_env)

        tunnel_proc = None
        if share:
            front_port = front_env.get("PORT", "5173")
            console.print(f"[magenta]Launching localtunnel on port {front_port}...[/magenta]")
            tunnel_proc = subprocess.Popen(
                ["npx", "--yes", "localtunnel", "--port", str(front_port)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            tunnel_thread = threading.Thread(
                target=enqueue_output, args=(tunnel_proc, "TUN  ", log_queue), daemon=True
            )
            tunnel_thread.start()

        vite_thread = threading.Thread(
            target=enqueue_output, args=(vite_proc, "FRONT", log_queue), daemon=True
        )
        uvicorn_thread = threading.Thread(
            target=enqueue_output, args=(uvicorn_proc, "BACK ", log_queue), daemon=True
        )

        vite_thread.start()
        uvicorn_thread.start()

        restarting = False
        try:
            while True:
                # Watch Config Files
                current_mtimes = get_mtimes(target)
                if current_mtimes != last_mtimes:
                    console.print("\n[yellow]Configuration changed. Restarting...[/yellow]")
                    last_mtimes = current_mtimes
                    restarting = True
                    break

                try:
                    prefix, line = log_queue.get(timeout=0.2)
                except Empty:
                    if vite_proc.poll() is not None and uvicorn_proc.poll() is not None:
                        break
                    continue
                
                if prefix == "FRONT":
                    console.print(f"[blue]\\[FRONT][/blue] {line}")
                elif prefix == "TUN  ":
                    console.print(f"[magenta]\\[TUN  ][/magenta] {line}")
                else:
                    console.print(f"[green]\\[BACK ][/green] {line}")
        except KeyboardInterrupt:
            console.print("\n[yellow]Stopping servers...[/yellow]")
            restarting = False
        finally:
            if tunnel_proc:
                tunnel_proc.terminate()
            vite_proc.terminate()
            uvicorn_proc.terminate()
            vite_proc.wait()
            uvicorn_proc.wait()
        
        if not restarting:
            break
            
        # Re-build env arguments before next loop restart
        front_env = build_env_for_section("frontend", target / ".env.toml", target)
        back_env = build_env_for_section("backend", target / ".env.toml", target)
