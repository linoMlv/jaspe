<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Vite-646CFF?style=for-the-badge&logo=vite&logoColor=white" alt="Vite">
  <img src="https://img.shields.io/badge/React-61DAFB?style=for-the-badge&logo=react&logoColor=black" alt="React">
  <img src="https://img.shields.io/badge/license-Apache%202.0-blue?style=for-the-badge" alt="License">
</p>

<h1 align="center">Jaspe</h1>

<p align="center">
  <strong>Déploiement zero-friction pour FastAPI + Vite/React/TypeScript.</strong><br>
  Zero Docker. Zero configuration complexe. Une seule commande.
</p>

---

## Table des matières
- [Pourquoi Jaspe ?](#pourquoi-jaspe-)
- [Fonctionnalités](#fonctionnalites)
- [Prérequis](#prerequis)
- [Installation](#installation)
- [Démarrage rapide](#démarrage-rapide)
- [Documentation](#documentation)
  - [Configuration : `jaspe.toml`](#configuration--jaspetoml)
  - [Secrets : `.env.toml`](#secrets--envtoml)
  - [Référence des commandes](#référence-des-commandes)
  - [Le Wrapper ASGI](#le-wrapper-asgi)
  - [Le Registre Global](#le-registre-global)
  - [L'Intégration Continue (CI/CD) Automatisée](#lintégration-continue-cicd-automatisée)
- [Adapter un projet existant à Jaspe](#adapter-un-projet-existant-à-jaspe)
  - [1. Vérifier la stack](#1-vérifier-la-stack)
  - [2. Organiser l'arborescence](#2-organiser-larborescence)
  - [3. Créer les fichiers de configuration](#3-créer-les-fichiers-de-configuration)
  - [4. Tester](#4-tester)
- [Structure du projet](#structure-du-projet)
- [Contribution](#contribution)
- [Licence](#licence)

---

## Pourquoi Jaspe ?

Déployer une application fullstack **FastAPI + React** sur un serveur Linux ne devrait pas nécessiter Docker, Kubernetes ou des fichiers de configuration interminables. Jaspe encapsule tout le workflow — du `git clone` au service `systemd` en production — dans un CLI minimaliste et opiniâtre.

**Trois principes :**

| Principe | Ce que ça signifie |
|---|---|
| **No-Touch** | Jaspe ne modifie jamais votre code source. Tout passe par un wrapper ASGI généré dynamiquement. |
| **Fail-Fast** | Si la version Node ne correspond pas, Jaspe bloque. Pour Python, Jaspe gère automatiquement la bonne version via `uv` — pas besoin de l'installer manuellement. |
| **KISS** | Jaspe fait tourner votre app sur un port local. Le SSL et le reverse proxy, c'est le job de Nginx ou Caddy. |

---

## Fonctionnalites

- **Scaffolding complet** — `jaspe init` crée l'arborescence, le venv Python (avec la bonne version via `uv`), le `package.json`, et les fichiers de config en une commande.
- **Gestion automatique de Python** — Jaspe crée un venv `uv` avec la version Python déclarée dans `jaspe.toml`. Pas besoin de l'installer manuellement sur le système, `uv` s'en charge.
- **Clonage intelligent** — `jaspe init <url>` clone un repo, vérifie le `jaspe.toml`, et installe toutes les dépendances automatiquement.
- **Intégration Continue GitHub Actions** — Jaspe génère nativement un workflow `.github/workflows/jaspe-deploy.yml` auto-réparateur capable de s'installer ou se mettre à jour "magiquement" sur votre VPS.
- **Déploiement distant Zero-Touch (Nouveau)** — `jaspe deploy` orchestre le transfert SSH (`rsync` filtré par `.gitignore`), auto-installe les prérequis sur un VPS vierge, gère intéractivement la fusion de vos secrets (`.env.toml`) et lance la production.
- **Mode développement** — `jaspe start dev` lance Vite et Uvicorn en parallèle avec des logs entrelacés et colorés dans le terminal.
- **Déploiement production** — `jaspe start prod` build le front, génère un wrapper ASGI, crée un service systemd, et démarre l'application sans sudo.
- **Tâches Planifiées (Cron) natives** — Ajoutez simplement un bloc `[[cron]]` dans le `jaspe.toml`, et Jaspe génère et orchestre automatiquement des *Timers* Systemd pour vos travaux en arrière-plan.
- **Gestion des dépendances** — `jaspe front-add` et `jaspe back-add` installent les paquets avec versionnage strict et reproductible.
- **Mise à jour et Auto-Rollback** — `jaspe update` orchestre le pull, les migrations, le build et le redémarrage, avec annulation `git reset` si le build crashe (Zero Downtime).
- **Registre global et Logs distants** — Gérez et monitorez vos applications avec `jaspe list`, `jaspe stop`, `jaspe remove` et `jaspe logs`.
- **Variables d'environnement dynamiques** — Fichier `.env.toml` centralisé avec un **Live-Reload** qui redémarre Uvicorn et Vite sur écoute.
- **UX Terminal** — Aucun log verbeux ("npm install", "uv sync", etc). Jaspe s'exécute silencieusement derrière d'élégants chargeurs animés et ne vous interrompt que via des boîtes de dialogue claires en cas d'erreur.

---

## Prerequis

| Outil | Version minimale | Note |
|---|---|---|
| [uv](https://github.com/astral-sh/uv) | dernière version | Gere aussi l'installation de Python automatiquement |
| Node.js | 20+ | Vérifie au démarrage (fail-fast) |
| Git | - | |
| systemd | natif (Linux) | Pour le déploiement production |

> **Python n'a pas besoin d'être installé manuellement.** Jaspe utilise `uv` pour créer un venv avec la version Python déclarée dans `jaspe.toml`. Si cette version n'est pas présente sur le système, `uv` la télécharge automatiquement.

---

## Installation

Le moyen le plus simple et recommandé d'installer Jaspe de façon globale sur n'importe quelle machine (Linux, WSL) est d'utiliser le script d'installation automatique : 

```bash
curl -fsSL https://raw.githubusercontent.com/linoMlv/jaspe/refs/heads/master/install.sh | bash
```

Si vous préférez procéder manuellement depuis les sources (pour le développement) :

```bash
git clone https://github.com/linomlv/jaspe.git
cd jaspe
uv sync
```

---

## Démarrage rapide

```bash
# Créer un nouveau projet
mkdir mon-projet && cd mon-projet
jaspe init

# Ou cloner un projet existant
jaspe init https://github.com/user/repo.git

# Lancer en développement
jaspe start dev

# Déployer en production
jaspe start prod
```

---

## Documentation

### Configuration : `jaspe.toml`

Le fichier central qui dicte le comportement de Jaspe. Généré automatiquement par `jaspe init`.

```toml
[config]
app_name = "mon_projet"
app_port = 8000
host = "127.0.0.1"           # Sécurisé par défaut pour reverse proxy
backend_folder = "backend"
frontend_folder = "frontend"

[git]
repo_url = "https://github.com/user/repo.git"
branch = "main"

[system]
autostart = true             # Active le service systemd au boot
restart_on_crash = true      # Restart=always dans systemd

[environment]
python_version = ">=3.11"    # Version du venv uv (téléchargée si absente)
node_version = ">=20.0"      # Contrainte validée au démarrage (fail-fast)

[backend]
entrypoint = "main:app"      # Module ASGI (module:variable)
migrations_dir = "alembic"   # Dossier Alembic (vide = pas de migrations)
api_prefix = "/api"           # Prefixe des routes backend (fallback 404 JSON)

[frontend]
build_command = "npm run build"
dist_folder = "dist"         # Sortie du build Vite
assets_prefix = "/assets"    # Prefixe de montage des fichiers statiques

[deploy]
# NOTE: Cette section contient des données sensibles. Il est RECOMMANDÉ 
# de la placer dans le fichier .env.toml (qui est ignoré par Git).
target = "user@192.168.0.1"
path = "/var/www/mon_projet"
sync_env = true
build_locally = false

[[cron]]
name = "cleanup"                # Identifiant pour le log et le service
schedule = "*-*-* 00:00:00"     # Format Calendar Systemd (ex: tous les minuits)
command = "scripts/cleanup.py"  # Commande relative à la racine du projet
```

> **Prefixes de routes :** `api_prefix` et `assets_prefix` controlent le comportement du wrapper ASGI en production. Toute requete commençant par `api_prefix` qui n'est pas gérée par FastAPI retourne une reponse JSON 404. Toute autre requête est redirigée vers `index.html` pour le routage SPA de React. Les fichiers statiques du build Vite sont montés sous `assets_prefix`.

### Secrets : `.env.toml`

Centralise les variables d'environnement pour le frontend et le backend. Jaspe fusionne ces variables avec l'environnement système avant de lancer les processus, sans polluer son propre contexte.

```toml
[frontend]
VITE_API_URL = "/api"

[backend]
DATABASE_URL = "postgresql://user:pass@localhost/db"
SECRET_KEY = "super_secret"

[deploy]
# Vos accès SSH confidentiels sont à l'abri ici (hors du jaspe.toml commité)
target = "user@vps.coodlab.fr"
path = "/var/www/abacus"
```

**Ordre de priorité :** Variables système (OS) > `.env.toml` > fichiers `.env` locaux.
**Fusion Logique :** Jaspe fusionne la section `[deploy]` de `.env.toml` par-dessus celle de `jaspe.toml`.

### Référence des commandes

#### `jaspe init [url]`

| Variante | Comportement |
|---|---|
| Sans argument | Crée l'arborescence (`backend/`, `frontend/`), génère `jaspe.toml`, `.env.toml`, initialise Git, crée le venv, lance `npm init`, et scaffold le Pipeline Github Actions CI. |
| Avec URL Git | Clone le repo, vérifie la présence de `jaspe.toml`, installe les dépendances (`uv pip install` + `npm ci`), crée un `.env.toml` vide. |

#### `jaspe start dev [--share]`

Lance l'environnement de développement :

1. Vérifie la version Node et crée/vérifie le venv Python via `uv`.
2. Charge les variables d'environnement depuis `.env.toml`.
3. Lance en parallèle `npm run dev` (Vite) et `uv run uvicorn --reload` (dans le venv).
4. Affiche les logs entrelacés avec prefixes colorés :
   ```
   [FRONT] Vite ready on http://localhost:5173
   [BACK ] Uvicorn running on http://127.0.0.1:8000
   ```
5. Mode "Live-Reload" : Toute édition du fichier `.env.toml` ou `jaspe.toml` redémarre instantanément les deux processus en fond.
6. Le flag `--share` spawne en parallèle un tunnel public `localtunnel` pour exposer et partager facilement votre version locale sur le web.
7. `Ctrl+C` arrête proprement les processus virtuels.

#### `jaspe start prod`

Déploie l'application pour la production (Mode "No-Sudo" Local SystemD) :

1. Vérifie la version Node, crée/vérifie le venv Python via `uv`, charge `.env.toml`.
2. Build le frontend (`npm run build`).
3. Génère le wrapper ASGI (`.jaspe/runner.py`) qui monte les fichiers statiques et gère le fallback SPA.
4. Crée et active un service systemd utilisateur (`~/.config/systemd/user/jaspe-<app_name>.service`) qui lance uvicorn via `uv run` dans le venv (`loginctl enable-linger` inclus).
5. Interroge votre config `[[cron]]` et instancie un *Timer* système autonome et infatigable distinct pour chaque tâche en arrière-plan.
6. Enregistre l'application dans le registre global.

#### `jaspe stop [app_name]`

Arrête le service systemd de l'application et met à jour son statut dans le registre.

#### `jaspe remove [app_name]`

Arrête le service, le désactive, supprime le fichier systemd et retire l'application du registre. Ne supprime pas les fichiers du projet.

#### `jaspe list`

Affiche un tableau de toutes les applications enregistrées avec leur nom, port, chemin et statut.

```
┏━━━━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┓
┃ Nom           ┃ Port ┃ Chemin                  ┃ Statut  ┃
┡━━━━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━┩
│ mon_projet    │ 8000 │ /var/www/mon_projet     │ active  │
└───────────────┴──────┴─────────────────────────┴─────────┘
```

#### `jaspe check-update`

Compare le commit local avec le commit distant de la branche configurée via `git fetch`.

#### `jaspe update [app_name]`

Workflow séquentiel de mise à jour :

1. `git fetch` + vérification des changements.
2. Arrêt du service systemd.
3. `git pull`.
4. Synchronisation des dépendances (`uv pip install` + `npm ci`).
5. Migrations Alembic (si `migrations_dir` est configuré).
6. Build du frontend.
7. Redémarrage du service.

> **Rollback Automatique :** En cas d'erreur de lint/build (Étape 6) ou de crash des migrations base de données (Étape 5), Jaspe intercepte l'erreur, annule la mise à jour Git (`git reset --hard`) et redémarre proprement l'ancienne version saine pour protéger la production.

#### `jaspe deploy`

Déploie intégralement votre application sur un serveur SSH distant de façon automatisée et interactive :
1. **Audit & Auto-Installer :** Jaspe vérifie via SSH que la cible possède les prérequis. S'il s'agit d'un VPS vierge, un menu interactif CLI propose de télécharger et configurer de façon autonome `uv` et `jaspe` sur la cible.
2. **Transfert Smart Rsync :** Jaspe transfère vos sources à l'aide d'un `rsync` optimisé. Ce dernier repère et applique automatiquement les règles de votre `.gitignore` local, bannissant les dossiers encombrants du transfert.
3. **Fusion Multi-Voies des Secrets :** Identifie si le serveur cache déjà un fichier `.env.toml`. Si oui, une invite à choix multiple (Écraser / Ignorer / Fusion priorité locale / Fusion priorité lointaine) résout élégamment le conflit d'environnement via des fusions de dictionnaires TOML en arrière-plan.
4. **Target Ignition :** Active le boot `jaspe start prod` déporté, installant le Service SystemD automatiquement à distance.

> **TIPS `build_locally` :** Si votre VPS est une instance budget souffrant d'1Go de RAM, l'installation de NodeJS n'est plus obligatoire. Indiquez `build_locally = true` dans `.toml` — Jaspe compilera le lourd package React *sur votre PC*, puis déploiera l'artefact fini sur le port `/dist/` du serveur, libérant drastiquement les processeurs de votre infrastructure !

#### `jaspe front-add [-D/--dev] <paquet>`

Installe un paquet npm avec `--save-exact` pour fixer la version. Le flag `--dev` place le paquet dans les `devDependencies`.

#### `jaspe back-add <paquet>`

Installe un paquet Python via `uv`, récupère la version exacte, et met à jour `requirements.txt`.

#### `jaspe logs [-f/--follow] [--cron <name>] [app_name]`

Affiche la console de production de l'application en s'interfaçant directement et formattant la sortie de `journalctl --user`. L'option `--cron` redirige l'écoute directement sur le flux standard I/O de la tâche planifiée choisie.

#### `jaspe db make "message"` / `jaspe db reset`

Outils utilitaires pour encapsuler `alembic` en dev. `make` génère automatiquement les scripts de migrations d'après l'architecture Python courante, et `reset` vide (downgrade base) puis rejoue (upgrade head) la base de données locale depuis zéro.

### Le Wrapper ASGI

Le coeur de la philosophie **No-Touch**. Lors d'un `jaspe start prod`, Jaspe génère un fichier `.jaspe/runner.py` qui :

- Importe l'application FastAPI de l'utilisateur.
- Monte les fichiers statiques du build Vite (`/assets`).
- Gère le fallback 404 pour le routage SPA de React.

Ce fichier n'est jamais versionné et est régénéré à chaque déploiement.

### Le Registre Global

Jaspe maintient un fichier `~/.jaspe/registry.json` qui permet aux commandes `stop`, `update`, `list` et `remove` de fonctionner depuis n'importe quel repertoire.

### L'Intégration Continue (CI/CD) Automatisée

Le scaffolding de `jaspe init` insère d'emblée le fichier de workflow Github Actions `.github/workflows/jaspe-deploy.yml`. Ce pipeline est configuré par défaut pour s'appuyer sur le mécanisme de clef SSH via `appleboy/ssh-action` avec un script bash "d'Auto-Guérison" (Self-Healing). 

Ce système vérifie dynamiquement si le projet distant possède déjà un manifeste `jaspe.toml`. S'il n'existe pas, l'Action s'injecte via un `jaspe init <url>`. S'il existe sur le serveur, l'Action enchaîne sur un simple protocole `jaspe update`. Ainsi, vous pouvez brancher votre repo Github sur un VPC vierge ou ancien, Jaspe construira lui-même l'application étape par étape !

---

## Adapter un projet existant à Jaspe

Vous avez déjà une application FastAPI + React et vous souhaitez la déployer avec Jaspe ? Suivez ces étapes.

### 1. Vérifier la stack

Jaspe cible une stack précise. Avant de commencer, assurez-vous que votre projet utilise :

| Couche | Technologie attendue |
|---|---|
| Backend | **FastAPI** avec un point d'entrée ASGI (ex: `main:app`) |
| Frontend | **Vite + React + TypeScript** avec un build statique (`npm run build` → `dist/`) |
| Python | Géré via **uv** (ou tout venv compatible avec `pip install -r requirements.txt`) |
| Node | `package.json` présent avec les scripts `dev` et `build` |

Si votre backend n'est pas FastAPI ou que votre frontend ne produit pas un dossier de fichiers statiques, Jaspe n'est pas adapté.

### 2. Organiser l'arborescence

Jaspe s'attend à une séparation claire entre le backend et le frontend, chacun dans son propre dossier à la racine du projet :

```
mon-projet/
├── backend/
│   ├── main.py              # Contient l'instance FastAPI (app)
│   ├── requirements.txt
│   └── ...
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── src/
│   └── ...
├── jaspe.toml               # À créer (étape 3)
└── .env.toml                # À créer (étape 3)
```

**Points importants :**

- Les noms `backend/` et `frontend/` sont les valeurs par défaut. Vous pouvez utiliser d'autres noms en les configurant dans `jaspe.toml` (`backend_folder` / `frontend_folder`).
- Votre API FastAPI doit préfixer ses routes avec un préfixe cohérent (par défaut `/api`, ex: `@app.get("/api/users")`). Ce préfixe est configurable via `api_prefix` dans `jaspe.toml` — en production, Jaspe l'utilise pour distinguer les appels API (reponse JSON 404) du routage SPA (fallback vers `index.html`).
- Le frontend n'a pas besoin de configuration spéciale pour être servi — Jaspe s'en charge via le wrapper ASGI. Vite produit un dossier `dist/` avec un sous-dossier `assets/`, et Jaspe les monte automatiquement sous `assets_prefix` (par défaut `/assets`, configurable).

### 3. Créer les fichiers de configuration

#### `jaspe.toml`

Créez ce fichier à la racine de votre projet et adaptez les valeurs :

```toml
[config]
app_name = "mon-projet"       # Nom unique, utilisé pour le service systemd
app_port = 8000
host = "127.0.0.1"
backend_folder = "backend"    # Nom de votre dossier backend
frontend_folder = "frontend"  # Nom de votre dossier frontend

[git]
repo_url = "https://github.com/user/mon-projet.git"
branch = "main"

[system]
autostart = true
restart_on_crash = true

[environment]
python_version = ">=3.11"     # uv créera un venv avec cette version
node_version = ">=20.0"

[backend]
entrypoint = "main:app"       # <module>:<variable> de votre instance FastAPI
migrations_dir = "alembic"    # Laissez vide ("") si vous n'utilisez pas Alembic
api_prefix = "/api"            # Préfixe de vos routes API

[frontend]
build_command = "npm run build"
dist_folder = "dist"
assets_prefix = "/assets"      # Préfixe de montage des fichiers statiques
```

> Si vos routes API utilisent un préfixe différent (ex: `/v1`, `/backend`), modifiez `api_prefix` en conséquence. Jaspe retournera une 404 JSON pour toute requête sous ce préfixe non gérée par FastAPI, et servira `index.html` pour tout le reste.

Le champ `entrypoint` est le plus important : il doit pointer vers le module Python et la variable qui contient votre instance `FastAPI()`. Par exemple, si votre app est dans `backend/app/server.py` sous le nom `application`, l'entrypoint sera `app.server:application`.

#### `.env.toml`

Centralisez vos variables d'environnement au lieu de les eparpiller dans des fichiers `.env` :

```toml
[frontend]
VITE_API_URL = "/api"

[backend]
DATABASE_URL = "postgresql://user:pass@localhost/db"
SECRET_KEY = "votre_secret"
CORS_ORIGINS = "http://localhost:5173"
```

> **Ne commitez pas** ce fichier s'il contient des secrets. Ajoutez `.env.toml` a votre `.gitignore`.

### 4. Tester

```bash
# Vérifier que tout est correctement configuré
jaspe start dev
```

Jaspe créera automatiquement un venv avec la version Python déclarée dans `jaspe.toml` (téléchargée par `uv` si absente du système). Si la version Node ne satisfait pas la contrainte, Jaspe s'arrêtera avec un message explicite.

Une fois le mode dev fonctionnel, le déploiement en production se fait en une commande :

```bash
jaspe start prod
```

---

## Structure du projet

```
jaspe/
├── pyproject.toml              # Configuration du package Python
├── README.md
└── src/
    └── jaspe/
        ├── __init__.py
        ├── main.py             # Point d'entree CLI (Typer)
        ├── config.py           # Modèles de données et parseur jaspe.toml
        ├── registry.py         # Registre global ~/.jaspe/registry.json
        ├── init_cmd.py         # Logique de la commande init
        ├── deps.py             # Gestion des dépendances (front-add / back-add)
        ├── env_manager.py      # Vérification des versions et fusion .env.toml
        ├── dev_server.py       # Serveur de développement (Vite + Uvicorn)
        ├── prod_server.py      # Deploiement production (wrapper ASGI + systemd)
        └── updater.py          # Systeme de mise a jour (check-update / update)
```

---

## Contribution

Les contributions sont les bienvenues. Clonez le repo, installez les dépendances avec `uv sync`, et soumettez une pull request.

```bash
git clone https://github.com/linomlv/jaspe.git
cd jaspe
uv sync
uv run jaspe --help
```

---

## Licence

Ce projet est distribué sous la licence **Apache License 2.0**.

```
Copyright 2025 Coodlab — Mallevaey Lino

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

---

<p align="center">
  Fait avec soin par <a href="">Coodlab</a>
</p>
