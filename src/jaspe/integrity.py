import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
import typer

from jaspe.config import JaspeConfig

console = Console()

TRACKED_FILES = [
    "jaspe.toml",
    ".env.toml",
]

def _calculate_file_hash(path: Path) -> Optional[str]:
    """Calcule le hash SHA-256 d'un fichier s'il existe."""
    if not path.exists():
        return None
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()


def get_current_hashes(project_path: Path, config: JaspeConfig) -> Dict[str, str]:
    """Calcule les hashes actuels des fichiers suivis."""
    hashes = {}
    
    # 1. Fichiers racine
    for f in TRACKED_FILES:
        h = _calculate_file_hash(project_path / f)
        if h:
            hashes[f] = h
            
    # 2. Fichiers de dépendances (folders dynamiques)
    reqs = project_path / config.config.backend_folder / "requirements.txt"
    h_reqs = _calculate_file_hash(reqs)
    if h_reqs:
        hashes["requirements.txt"] = h_reqs
        
    pkg = project_path / config.config.frontend_folder / "package.json"
    h_pkg = _calculate_file_hash(pkg)
    if h_pkg:
        hashes["package.json"] = h_pkg
        
    return hashes


def update_stored_hashes(project_path: Path, config: JaspeConfig) -> None:
    """Met à jour les hashes stockés dans .jaspe/hashes.json."""
    jaspe_dir = project_path / ".jaspe"
    jaspe_dir.mkdir(exist_ok=True)
    
    hashes = get_current_hashes(project_path, config)
    hash_file = jaspe_dir / "hashes.json"
    
    with open(hash_file, "w", encoding="utf-8") as f:
        json.dump(hashes, f, indent=4)


def check_integrity(project_path: Path, config: JaspeConfig) -> List[str]:
    """Compare les hashes actuels avec les hashes stockés. Retourne la liste des fichiers modifiés."""
    hash_file = project_path / ".jaspe" / "hashes.json"
    if not hash_file.exists():
        # Si le fichier n'existe pas encore (premier run après update de jaspe), 
        # on ne bloque pas mais on suggère de l'initialiser
        return []
        
    try:
        with open(hash_file, "r", encoding="utf-8") as f:
            stored = json.load(f)
    except (json.JSONDecodeError, IOError):
        return []
        
    current = get_current_hashes(project_path, config)
    mismatches = []
    
    for filename, cur_hash in current.items():
        if filename not in stored or stored[filename] != cur_hash:
            mismatches.append(filename)
            
    return mismatches


def audit_and_prompt_reload(project_path: Path, config: JaspeConfig) -> None:
    """Vérifie l'intégrité et propose un reload si nécessaire."""
    mismatched_files = check_integrity(project_path, config)
    
    if mismatched_files:
        console.print(Panel(
            f"[bold yellow]⚠️  Attention : Dérive de configuration détectée ![/bold yellow]\n\n"
            f"Les fichiers suivants ont été modifiés manuellement :\n"
            + "\n".join([f"  - [cyan]{f}[/cyan]" for f in mismatched_files]) +
            f"\n\nVotre environnement local (Venv, Node Modules) n'est peut-être plus à jour.",
            title="Audit d'Intégrité",
            border_style="yellow"
        ))
        
        if Confirm.ask("Voulez-vous effectuer un [bold]jaspe reload[/bold] maintenant pour synchroniser ?", default=True):
            from jaspe.main import reload
            # On simule l'appel à reload
            # Note: On utilise typer.Exit pour arrêter l'exécution actuelle si on reload
            # Mais c'est mieux si l'utilisateur lance la commande lui-même pour voir les logs
            console.print("[blue]Lancement du reload...[/blue]")
            raise typer.Exit(subprocess_reload(project_path))
        else:
            console.print("[dim]Poursuite avec l'environnement actuel (non recommandé).[/dim]\n")


def subprocess_reload(project_path: Path) -> int:
    """Lance un jaspe reload via subprocess pour garantir la propreté."""
    import subprocess
    res = subprocess.run(["jaspe", "reload"], cwd=str(project_path))
    return res.returncode
