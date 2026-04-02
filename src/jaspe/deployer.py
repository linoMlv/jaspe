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


def run_deploy(cfg: JaspeConfig, target: Path):
    host_target = cfg.deploy.target
    remote_path = cfg.deploy.path
    
    console.print(f"[bold blue]Déploiement cible :[/] [cyan]{host_target}:{remote_path}[/cyan]")
    
    # Phase 1: Audit du VPS distant
    console.print("\n[bold yellow]--- Phase 1 : Audit du Serveur ---[/bold yellow]")
    res_uv = run_ssh(host_target, "command -v uv", check=False)
    if res_uv.returncode != 0:
        console.print("[red]❌ 'uv' n'est pas installé sur la machine distante.[/red]")
        if Confirm.ask("Voulez-vous l'installer automatiquement via curl ?"):
            run_ssh_with_spinner(host_target, "curl -LsSf https://astral.sh/uv/install.sh | sh", "Installation de uv (astral.sh)")
            run_ssh_with_spinner(host_target, "source $HOME/.local/bin/env", "Activation de uv")
        else:
            raise typer.Exit(1)
    else:
        console.print("[green]✔ 'uv' est installé.[/green]")
        
    res_jaspe = run_ssh(host_target, "command -v jaspe", check=False)
    if res_jaspe.returncode != 0:
        console.print("[red]❌ 'jaspe' n'est pas installé sur la machine distante.[/red]")
        if Confirm.ask("Voulez-vous installer jaspe automatiquement sur le serveur ?"):
            run_ssh_with_spinner(host_target, "export PATH=$PATH:$HOME/.local/bin; curl -fsSL https://raw.githubusercontent.com/linoMlv/jaspe/refs/heads/master/install.sh | bash", "Installation de jaspe (install.sh)")
            run_ssh_with_spinner(host_target, "source $HOME/.local/bin/env", "Activation de jaspe")
        else:
            raise typer.Exit(1)
    else:
        console.print("[green]✔ 'jaspe' est installé.[/green]")
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
            console.print("[yellow]⚠️ Une mise à jour de l'outil Jaspe est disponible sur le serveur.[/yellow]")
            if Confirm.ask("Voulez-vous mettre à jour Jaspe sur le serveur maintenant ?"):
                run_ssh_with_spinner(host_target, "export PATH=$PATH:$HOME/.local/bin; curl -fsSL https://raw.githubusercontent.com/linoMlv/jaspe/refs/heads/master/install.sh | bash", "Mise à jour de l'outil Jaspe (install.sh)")
                run_ssh_with_spinner(host_target, "source $HOME/.local/bin/env", "Réactivation après mise à jour")
        
    if not cfg.deploy.build_locally:
        res_node = run_ssh(host_target, "command -v node", check=False)
        if res_node.returncode != 0:
            console.print("[red]❌ 'node' n'est pas installé sur le serveur et build_locally est à False.[/red]")
            console.print("=> Installez Node (via nvm, fnm, ou apt) sur la cible avant de réessayer.")
            raise typer.Exit(1)
        console.print("[green]✔ 'node' est installé.[/green]")

    # Phase 2: Clone vs Rsync vs Update
    console.print("\n[bold yellow]--- Phase 2 : Envoi & Installation ---[/bold yellow]")
    res_dir = run_ssh(host_target, f"test -d {remote_path}", check=False)
    exists = (res_dir.returncode == 0)
    
    repo_url = cfg.git.repo_url if cfg.git else ""
    
    if not exists:
        console.print("[blue]Nouvelle application, création d'une arborescence...[/blue]")
        if repo_url and not cfg.deploy.build_locally:
            run_ssh_with_spinner(host_target, f"jaspe init '{repo_url}' '{remote_path}'", "Clonage distant interactif (jaspe init)")
        else:
            run_ssh_with_spinner(host_target, f"mkdir -p {remote_path}", "Création du dossier hôte")
            if cfg.deploy.build_locally:
                front_path = target / cfg.config.frontend_folder
                run_with_spinner(["npm", "run", "build"], "Build local du frontend React/Vite", cwd=str(front_path))
                
            cmd_rsync = [
                "rsync", "-avz", "--filter=:- .gitignore", "--exclude", ".git", "--exclude", "node_modules", 
                "--exclude", ".venv", "--exclude", "__pycache__", 
                str(target) + "/", f"{host_target}:{remote_path}/"
            ]
            run_with_spinner(cmd_rsync, "Transfert Rsync (Initial) vers le serveur (Ignorant les fichiers lourds)")
            run_ssh_with_spinner(host_target, f"cd {remote_path}/{cfg.config.backend_folder} && ( [ -d .venv ] || uv venv ) && uv pip install -r requirements.txt", "Installation distante des dépendances Python")
            if not cfg.deploy.build_locally:
                run_ssh_with_spinner(host_target, f"cd {remote_path}/{cfg.config.frontend_folder} && npm install", "Installation distante des dépendances Node")
    else:
        console.print("[blue]L'application existe déjà sur le serveur.[/blue]")
        if not cfg.deploy.build_locally and repo_url:
            run_ssh_with_spinner(host_target, f"cd {remote_path} && jaspe update", "Mise à jour Intelligente (jaspe update) sur le serveur")
        else:
            if cfg.deploy.build_locally:
                front_path = target / cfg.config.frontend_folder
                run_with_spinner(["npm", "run", "build"], "Build local du frontend React/Vite", cwd=str(front_path))
                
            cmd_rsync = [
                "rsync", "-avz", "--delete", "--filter=:- .gitignore", "--exclude", ".git", "--exclude", "node_modules", 
                "--exclude", ".venv", "--exclude", "__pycache__", 
                str(target) + "/", f"{host_target}:{remote_path}/"
            ]
            run_with_spinner(cmd_rsync, "Envoi Rapide Rsync des modifs (Update local)")
            run_ssh_with_spinner(host_target, f"cd {remote_path}/{cfg.config.backend_folder} && ( [ -d .venv ] || uv venv ) && uv pip install -r requirements.txt", "Mise à jour distante des dépendances Python")
            if not cfg.deploy.build_locally:
                run_ssh_with_spinner(host_target, f"cd {remote_path}/{cfg.config.frontend_folder} && npm install", "Mise à jour distante des dépendances Node")

    # Phase 3: Synchro du fichier d'environnement
    console.print("\n[bold yellow]--- Phase 3 : Synchronisation Secrets ---[/bold yellow]")
    if cfg.deploy.sync_env:
        env_file = target / ".env.toml"
        if env_file.exists():
            res_env = run_ssh(host_target, f"test -f {remote_path}/.env.toml", check=False)
            if res_env.returncode == 0:
                console.print("[bold red]⚠️ Attention : Un fichier .env.toml existe déjà sur le serveur distant.[/bold red]")
                console.print(" [1] Écraser: Remplacer le serveur par la version locale de votre PC")
                console.print(" [2] Ignorer: Garder la version distante (Ne rien envoyer)")
                console.print(" [3] Fusion: Fusionner les deux avec priorité à votre PC (Local)")
                console.print(" [4] Fusion: Fusionner les deux avec priorité au serveur (Distant)")
                
                choice = Prompt.ask("Votre choix", choices=["1", "2", "3", "4"], default="3")
                
                if choice == "2":
                    console.print("[dim]Conservation du fichier distant. Ignoré.[/dim]")
                elif choice == "1":
                    run_with_spinner(["scp", str(env_file), f"{host_target}:{remote_path}/.env.toml"], "Transfert SCP de .env.toml (Écrasement)")
                    console.print("[green]Secrets mis à jour avec succès.[/green]")
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
                    run_with_spinner(["scp", str(tmp_file), f"{host_target}:{remote_path}/.env.toml"], "Transfert SCP de .env.toml (Fusion Intelligente)")
                    tmp_file.unlink()
                    console.print("[green]Secrets fusionnés et déployés avec succès.[/green]")
            else:
                run_with_spinner(["scp", str(env_file), f"{host_target}:{remote_path}/.env.toml"], "Transfert SCP Régulier de .env.toml")
                console.print("[green]Secrets mis à jour avec succès.[/green]")
        else:
            console.print("[dim]Aucun .env.toml détecté. Ignoré.[/dim]")
    else:
        console.print("[dim]sync_env=false. Ignoré.[/dim]")
            
    # Phase 4: Run Process
    console.print("\n[bold yellow]--- Phase 4 : Lancement / Bascule ---[/bold yellow]")
    skip_flag = " --skip-build" if cfg.deploy.build_locally else ""
    run_ssh_with_spinner(host_target, f"cd {remote_path} && jaspe start prod{skip_flag}", "Exécution finale globale (jaspe start prod)")
    console.print("\n[bold green]🚀 Mission Accomplie ! L'application tourne en Remote Production.[/]")
