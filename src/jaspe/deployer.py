import subprocess
from pathlib import Path
import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt
import sys

from jaspe.config import JaspeConfig
from jaspe.ui import run_with_spinner

console = Console()

def run_ssh(target: str, command: str, check: bool = True) -> subprocess.CompletedProcess:
    """Helper léger pour des audits SSH masqués derrière run_with_spinner() ou manuels."""
    cmd = ["ssh", "-o", "StrictHostKeyChecking=no", target, f"export PATH=$PATH:$HOME/.local/bin; {command}"]
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def run_ssh_with_spinner(target: str, command: str, loading_msg: str, check: bool = True) -> str:
    """Helper SSH visuel encapsulé dans un spinner."""
    cmd = ["ssh", "-o", "StrictHostKeyChecking=no", target, f"export PATH=$PATH:$HOME/.local/bin; {command}"]
    return run_with_spinner(cmd, loading_msg, check=check)


def dump_toml(d: dict) -> str:
    lines = []
    for section, values in d.items():
        lines.append(f"[{section}]")
        for k, v in values.items():
            if isinstance(v, str):
                lines.append(f'{k} = "{v}"')
            elif isinstance(v, bool):
                lines.append(f"{k} = {'true' if v else 'false'}")
            else:
                lines.append(f"{k} = {v}")
        lines.append("")
    return "\n".join(lines)


def run_deploy(cfg: JaspeConfig, target: Path, reload: bool = False, skip_build: bool = False, health_check: bool = True):
    host_target = cfg.deploy.target
    remote_path = cfg.deploy.path
    
    console.print(f"[bold blue]Deployment target:[/] [cyan]{host_target}:{remote_path}[/cyan]")
    
    # 🔍 Audit d'IP Publique
    res_ip = run_ssh(host_target, "curl -s https://api.ipify.org || curl -s icanhazip.com", check=False)
    public_ip = res_ip.stdout.strip() if res_ip.returncode == 0 else "Unknown"
    if public_ip != "Unknown":
        console.print(f"[bold blue]Public IP:[/] [cyan]{public_ip}[/cyan]")
    
    # Phase 1: Server Audit
    console.print("\n[bold yellow]--- Phase 1: Server Audit ---[/bold yellow]")
    res_uv = run_ssh(host_target, "command -v uv", check=False)
    if res_uv.returncode != 0:
        console.print("[red]❌ 'uv' is not installed on the remote machine.[/red]")
        if Confirm.ask("Would you like to install it automatically via curl?"):
            run_ssh_with_spinner(host_target, "curl -LsSf https://astral.sh/uv/install.sh | sh", "Installing uv (astral.sh)...")
            run_ssh_with_spinner(host_target, "source $HOME/.local/bin/env", "Activating uv...")
        else:
            raise typer.Exit(1)
    else:
        console.print("[green]✔ 'uv' is installed.[/green]")
        
    res_jaspe = run_ssh(host_target, "command -v jaspe", check=False)
    if res_jaspe.returncode != 0:
        console.print("[red]❌ 'jaspe' is not installed on the remote machine.[/red]")
        if Confirm.ask("Would you like to install jaspe automatically on the server?"):
            run_ssh_with_spinner(host_target, "export PATH=$PATH:$HOME/.local/bin; curl -fsSL https://raw.githubusercontent.com/linoMlv/jaspe/refs/heads/master/install.sh | bash", "Installing jaspe (install.sh)...")
            run_ssh_with_spinner(host_target, "source $HOME/.local/bin/env", "Activating jaspe...")
        else:
            raise typer.Exit(1)
    else:
        console.print("[green]✔ 'jaspe' is installed.[/green]")
        # Audit de mise à jour (Git)
        check_git_cmd = (
            "if [ -d $HOME/.jaspe-cli ]; then "
            "cd $HOME/.jaspe-cli && git fetch --quiet && "
            "LOCAL=$(git rev-parse HEAD) && REMOTE=$(git rev-parse @{u}) && "
            "if [ \"$LOCAL\" != \"$REMOTE\" ]; then echo 'UPDATE_AVAILABLE'; fi; "
            "fi"
        )
        res_git = run_ssh(host_target, check_git_cmd, check=False)
        if "UPDATE_AVAILABLE" in res_git.stdout:
            console.print("[yellow]⚠️ An update for the Jaspe CLI tool is available on the server.[/yellow]")
            if Confirm.ask("Would you like to update Jaspe on the server now?"):
                run_ssh_with_spinner(host_target, "export PATH=$PATH:$HOME/.local/bin; curl -fsSL https://raw.githubusercontent.com/linoMlv/jaspe/refs/heads/master/install.sh | bash", "Updating Jaspe tool (install.sh)...")
                run_ssh_with_spinner(host_target, "source $HOME/.local/bin/env", "Re-activating after update...")
        
    if not cfg.deploy.build_locally:
        res_node = run_ssh(host_target, "command -v node", check=False)
        if res_node.returncode != 0:
            console.print("[red]❌ 'node' is not installed on the server and build_locally is set to False.[/red]")
            console.print("=> Install Node.js (via nvm, fnm, or apt) on the target before retrying.")
            raise typer.Exit(1)
        console.print("[green]✔ 'node' is installed.[/green]")

    # Phase 2: Upload & Installation
    console.print("\n[bold yellow]--- Phase 2: Upload & Installation ---[/bold yellow]")
    res_dir = run_ssh(host_target, f"test -d {remote_path}", check=False)
    exists = (res_dir.returncode == 0)
    
    repo_url = cfg.git.repo_url if cfg.git else ""
    
    if not exists:
        console.print("[blue]Target directory not found, creating structure...[/blue]")
        if repo_url and not cfg.deploy.build_locally:
            run_ssh_with_spinner(host_target, f"jaspe init '{repo_url}' '{remote_path}'", "Interactive remote cloning (jaspe init)...")
        else:
            run_ssh_with_spinner(host_target, f"mkdir -p {remote_path}", "Creating target directory...")
            if cfg.deploy.build_locally and not skip_build:
                front_path = target / cfg.config.frontend_folder
                run_with_spinner(["npm", "run", "build"], "Local build of React/Vite frontend...", cwd=str(front_path))
                
            cmd_rsync = ["rsync", "-avz"]
            
            if cfg.deploy.build_locally:
                # Inclure le dossier dist avant d'appliquer les filtres gitignore
                dist_rel = f"{cfg.config.frontend_folder}/{cfg.frontend.dist_folder}"
                cmd_rsync.extend(["--include", f"{dist_rel}/***", "--exclude", f"{cfg.config.frontend_folder}/*"])

            cmd_rsync.extend([
                "--filter=:- .gitignore", "--exclude", ".git", "--exclude", "node_modules", 
                "--exclude", ".venv", "--exclude", "__pycache__", 
                str(target) + "/", f"{host_target}:{remote_path}/"
            ])
            run_with_spinner(cmd_rsync, "Rsync Transfer (Initial) to server...")
            run_ssh_with_spinner(host_target, f"cd {remote_path}/{cfg.config.backend_folder} && ( [ -d .venv ] || uv venv ) && uv pip install -r requirements.txt", "Installing remote Python dependencies...")
            if not cfg.deploy.build_locally:
                run_ssh_with_spinner(host_target, f"cd {remote_path}/{cfg.config.frontend_folder} && npm install", "Installing remote Node.js dependencies...")
    else:
        console.print("[blue]Application already exists on the server.[/blue]")
        reload_flag = " --reload" if reload else ""
        skip_build_flag = " --skip-build" if skip_build else ""
        if not cfg.deploy.build_locally and repo_url:
            run_ssh_with_spinner(host_target, f"cd {remote_path} && jaspe update{reload_flag}{skip_build_flag}", "Intelligent Update (jaspe update) on server...")
        else:
            if cfg.deploy.build_locally and not skip_build:
                front_path = target / cfg.config.frontend_folder
                run_with_spinner(["npm", "run", "build"], "Local build of React/Vite frontend...", cwd=str(front_path))
                
            cmd_rsync = ["rsync", "-avz", "--delete"]
            
            if cfg.deploy.build_locally:
                # Inclure le dossier dist avant d'appliquer les filtres gitignore
                dist_rel = f"{cfg.config.frontend_folder}/{cfg.frontend.dist_folder}"
                cmd_rsync.extend(["--include", f"{dist_rel}/***", "--exclude", f"{cfg.config.frontend_folder}/*"])

            cmd_rsync.extend([
                "--filter=:- .gitignore", "--exclude", ".git", "--exclude", "node_modules", 
                "--exclude", ".venv", "--exclude", "__pycache__", 
                str(target) + "/", f"{host_target}:{remote_path}/"
            ])
            run_with_spinner(cmd_rsync, "Rsync Transfer (Patch Update) to server...")
            
            if reload:
                run_ssh_with_spinner(host_target, f"rm -rf {remote_path}/{cfg.config.backend_folder}/.venv", "Cleaning remote Venv (Reload)...")
                
            run_ssh_with_spinner(host_target, f"cd {remote_path}/{cfg.config.backend_folder} && ( [ -d .venv ] || uv venv ) && uv pip install -r requirements.txt", "Updating remote Python dependencies...")
            if not cfg.deploy.build_locally:
                run_ssh_with_spinner(host_target, f"cd {remote_path}/{cfg.config.frontend_folder} && npm install", "Updating remote Node.js dependencies...")

    # Phase 3: Secrets Synchronization
    console.print("\n[bold yellow]--- Phase 3: Secrets Synchronization ---[/bold yellow]")
    if cfg.deploy.sync_env:
        env_file = target / ".env.toml"
        if env_file.exists():
            res_env = run_ssh(host_target, f"test -f {remote_path}/.env.toml", check=False)
            if res_env.returncode == 0:
                console.print("[bold red]⚠️  Warning: .env.toml already exists on the remote server.[/bold red]")
                console.print(" [1] Overwrite: Replace server file with local version")
                console.print(" [2] Skip: Keep remote version (do nothing)")
                console.print(" [3] Merge (Local Priority): Merge both, preferring local values")
                console.print(" [4] Merge (Server Priority): Merge both, preferring server values")
                
                choice = Prompt.ask("Your choice", choices=["1", "2", "3", "4"], default="3")
                
                if choice == "2":
                    console.print("[dim]Remote file preserved. Skipping.[/dim]")
                elif choice == "1":
                    run_with_spinner(["scp", str(env_file), f"{host_target}:{remote_path}/.env.toml"], "SCP Transfer: .env.toml (Overwrite)...")
                    console.print("[green]Secrets updated successfully.[/green]")
                else:
                    remote_env_raw = run_ssh(host_target, f"cat {remote_path}/.env.toml", check=True).stdout
                    if sys.version_info >= (3, 11):
                        import tomllib
                    else:
                        import tomli as tomllib
                        
                    local_env = tomllib.loads(env_file.read_text(encoding="utf-8"))
                    remote_env = tomllib.loads(remote_env_raw)
                    
                    merged = {}
                    all_sections = set(local_env.keys()).union(remote_env.keys())
                    for sec in all_sections:
                        merged[sec] = {}
                        local_sec = local_env.get(sec, {})
                        remote_sec = remote_env.get(sec, {})
                        
                        all_keys = set(local_sec.keys()).union(remote_sec.keys())
                        for k in all_keys:
                            if choice == "3": # Priority Local
                                merged[sec][k] = local_sec[k] if k in local_sec else remote_sec[k]
                            else: # Priority Remote
                                merged[sec][k] = remote_sec[k] if k in remote_sec else local_sec[k]
                                
                    merged_content = dump_toml(merged)
                    tmp_file = target / ".env.toml.merge"
                    tmp_file.write_text(merged_content, encoding="utf-8")
                    run_with_spinner(["scp", str(tmp_file), f"{host_target}:{remote_path}/.env.toml"], "SCP Transfer: .env.toml (Smart Merge)...")
                    tmp_file.unlink()
                    console.print("[green]Secrets merged and deployed successfully.[/green]")
            else:
                run_with_spinner(["scp", str(env_file), f"{host_target}:{remote_path}/.env.toml"], "SCP Transfer: .env.toml...")
                console.print("[green]Secrets updated successfully.[/green]")
        else:
            console.print("[dim]No .env.toml detected. Skipping.[/dim]")
    else:
        console.print("[dim]sync_env=false. Skipping.[/dim]")
            
    # Phase 4: Ignition
    console.print("\n[bold yellow]--- Phase 4: Launching / Switching ---[/bold yellow]")
    skip_flag = " --skip-build" if (cfg.deploy.build_locally or skip_build) else ""
    hc_flag = "" if health_check else " --no-health-check"
    run_ssh_with_spinner(host_target, f"cd {remote_path} && jaspe start prod{skip_flag}{hc_flag}", "Final ignition (jaspe start prod)...")
    
    url_ip = public_ip if public_ip != "Unknown" else cfg.config.host
    url = f"http://{url_ip}:{cfg.config.app_port}"
    console.print(f"\n[bold green]🚀 Mission Accomplished! Application is running in Remote Production.[/]")
    console.print(f"[blue]Public Link: {url}[/blue]")
