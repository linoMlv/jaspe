# Audit Technique — Jaspe `runner.py` (Wrapper ASGI)

Audit de compatibilité complète avec FastAPI, basé sur l'analyse du wrapper généré par `jaspe start prod`.

---

## Code actuel audité

```python
import sys
import inspect
import os
sys.path.insert(0, "/home/coodlab-lino/vitae-cms/backend")

from app.main import app as user_app
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# Si l'utilisateur a passé une fonction (Factory Pattern) sans argument au lieu de l'instance
if inspect.isfunction(user_app) and len(inspect.signature(user_app).parameters) == 0:
    user_app = user_app()

class SPAFallbackMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if response.status_code == 404:
            if request.url.path.startswith("/api") or request.url.path.startswith("/assets"):
                return response
            
            file_path = os.path.join("/home/.../frontend/dist", request.url.path.lstrip("/"))
            if os.path.isfile(file_path):
                return FileResponse(file_path)
                
            if "." in request.url.path.split("/")[-1]:
                return response

            return FileResponse("/home/.../frontend/dist/index.html")
        return response

jaspe_app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
jaspe_app.add_middleware(SPAFallbackMiddleware)

assets_path = os.path.join("/home/.../frontend/dist", "assets")
if os.path.isdir(assets_path):
    jaspe_app.mount("/assets", StaticFiles(directory=assets_path), name="assets")

jaspe_app.mount("/", user_app)
```

---

## Synthèse des problèmes

| # | Criticité | Problème | Impact |
|---|---|---|---|
| 1 | 🔴 CRITIQUE | **Lifespan non propagé** | DB vide, startup/shutdown cassés |
| 2 | 🔴 CRITIQUE | **Middlewares utilisateur ignorés** | CORS, auth, rate-limit contournés |
| 3 | 🔴 CRITIQUE | **Exception handlers perdus** | Erreurs 500 au lieu de réponses custom |
| 4 | 🟠 MAJEUR | **WebSocket incompatible** | WS ne fonctionne pas du tout |
| 5 | 🟠 MAJEUR | **Path traversal possible** | Faille de sécurité (lecture de fichiers arbitraires) |
| 6 | 🟠 MAJEUR | **`/docs` et `/openapi.json` cassés** | Impossible d'utiliser Swagger/Redoc |
| 7 | 🟠 MAJEUR | **`dependency_overrides` cassés** | Tests e2e impossibles en prod-like |
| 8 | 🟡 MINEUR | **`BaseHTTPMiddleware` — streaming cassé** | Fuites mémoire avec SSE/streaming |
| 9 | 🟡 MINEUR | **Factory pattern incomplet** | Crash si factory avec arguments |
| 10 | 🟡 MINEUR | **Préfixes hardcodés** | Échec si `api_prefix ≠ /api` |
| 11 | 🟠 MAJEUR | **Variables d'env systemd mal échappées** | Valeurs tronquées/corrompues en prod |

---

## Détail des problèmes

---

### 🔴 1. CRITIQUE — Lifespan non propagé

> [!CAUTION]
> C'est le bug qui causait l'erreur 500 sur `/api/cv`.

**Problème :** `jaspe_app.mount("/", user_app)` monte l'app utilisateur comme une sous-application Starlette. Or, **Starlette ne propage pas les événements lifespan aux sous-applications montées**. Le startup et le shutdown de l'app utilisateur ne sont donc jamais exécutés.

**Impact :**
- Toute logique dans `lifespan()` (création de tables, seed, pools de connexions, caches, planificateurs) est **silencieusement ignorée**
- Toute logique dans les anciens décorateurs `@app.on_event("startup")` / `@app.on_event("shutdown")` est aussi perdue
- La DB reste vide, les connexions ne sont pas initialisées, les workers background ne démarrent pas

**Correction :** Le wrapper doit manuellement propager le lifespan de l'app utilisateur :

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def combined_lifespan(app):
    # Propager le lifespan de l'app utilisateur
    if hasattr(user_app.router, 'lifespan_context') and user_app.router.lifespan_context:
        async with user_app.router.lifespan_context(user_app) as state:
            yield state
    else:
        yield

jaspe_app = FastAPI(lifespan=combined_lifespan, docs_url=None, redoc_url=None, openapi_url=None)
```

---

### 🔴 2. CRITIQUE — Middlewares utilisateur ignorés

**Problème :** Quand une app est montée via `mount()`, les middlewares ajoutés à la **jaspe_app parente ne sont pas appliqués** aux requêtes routées vers `user_app`. *Et inversement*, les middlewares de `user_app` sont bien exécutés, **sauf** que le `SPAFallbackMiddleware` de Jaspe n'est PAS dans la pile de `user_app` — il est dans la pile de `jaspe_app`.

Le flux réel est :
```
Requête → jaspe_app middleware stack (SPAFallback) → mount "/" → user_app middleware stack (CORS, Security, etc.)
```

**Le problème concret :** Si l'utilisateur ajoute un middleware CORS à son `user_app`, ce middleware s'applique. **MAIS** le `SPAFallbackMiddleware` de Jaspe, lui, retourne des `FileResponse` *en dehors* de la stack middleware de l'app utilisateur. Résultat → les headers CORS ne sont pas ajoutés aux réponses SPA/statiques, ce qui casse le frontend dans certains cas (fonts CORS, workers, etc.).

**Correction :** Deux options :
- **Option A (recommandée)** — Ne pas utiliser `mount()`. À la place, utiliser une architecture ASGI pure qui wrape directement l'app utilisateur :

```python
class JaspeASGIWrapper:
    """Wrape l'app utilisateur au niveau ASGI sans mount()."""
    def __init__(self, user_app, static_dir, dist_dir, api_prefix, assets_prefix):
        self.user_app = user_app
        self.static_app = StaticFiles(directory=static_dir) if os.path.isdir(static_dir) else None
        self.dist_dir = dist_dir
        self.api_prefix = api_prefix
        self.assets_prefix = assets_prefix

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            # Propager directement le lifespan à l'app utilisateur
            await self.user_app(scope, receive, send)
            return

        path = scope.get("path", "")

        # Servir les assets statiques
        if path.startswith(self.assets_prefix) and self.static_app:
            await self.static_app(scope, receive, send)
            return

        # Tout le reste passe par l'app utilisateur
        # (qui applique ses propres middlewares : CORS, auth, etc.)
        await self.user_app(scope, receive, send)
```

- **Option B** — Copier les middlewares de `user_app` vers `jaspe_app`.

---

### 🔴 3. CRITIQUE — Exception handlers perdus

**Problème :** Les `exception_handler` enregistrés par l'utilisateur sur son `user_app` (`@app.exception_handler(...)`) ne sont pas hérités par `jaspe_app`. Comme `jaspe_app` est l'app racine, toute exception qui "remonte" au-delà de `user_app` (ou survient dans le middleware SPA) ne sera pas attrapée par les handlers custom.

**Impact :**
- Les exceptions custom de l'utilisateur (ex: `RateLimitExceeded`, `PermissionDenied`) peuvent produire des 500 au lieu de réponses JSON structurées
- Les overrides de `HTTPException` et `RequestValidationError` installés sur `user_app` fonctionnent dans le scope monté, mais pas pour les erreurs dans le fallback SPA

**Correction :** L'architecture ASGI pure (Option A ci-dessus) élimine ce problème puisque l'app utilisateur est la seule app et conserve tous ses handlers.

---

### 🟠 4. MAJEUR — WebSocket incompatible

**Problème :** `SPAFallbackMiddleware` hérite de `BaseHTTPMiddleware`, qui **ne supporte que HTTP**. Les connexions WebSocket (`scope["type"] == "websocket"`) sont silencieusement ignorées ou provoquent une erreur.

**Impact :**
- Toute app utilisant des WebSockets FastAPI (`@app.websocket("/ws")`) ne fonctionnera pas en production via Jaspe
- Pas d'erreur claire — la connexion WS échoue simplement

**Correction :** Utiliser un middleware ASGI pur au lieu de `BaseHTTPMiddleware` :

```python
class SPAFallbackMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            # Laisser passer WebSocket et lifespan sans interférence
            await self.app(scope, receive, send)
            return
        
        # Logique SPA fallback uniquement pour HTTP...
```

---

### 🟠 5. MAJEUR — Path traversal possible

> [!WARNING]
> Faille de sécurité permettant la lecture de fichiers arbitraires sur le serveur.

**Problème :** Le code construit `file_path` directement à partir de `request.url.path` :
```python
file_path = os.path.join(DIST_DIR, request.url.path.lstrip("/"))
if os.path.isfile(file_path):
    return FileResponse(file_path)
```

Un attaquant peut envoyer une requête comme `GET /../../etc/passwd` ou utiliser des encodages URL doubles (`%2e%2e%2f`) pour échapper au dossier `dist/`. Certes, `lstrip("/")` est là, mais `os.path.join` ne canonicalise pas le chemin.

**Correction :** Valider que le chemin résolu reste bien dans le dossier `dist/` :

```python
file_path = os.path.realpath(os.path.join(DIST_DIR, request.url.path.lstrip("/")))
if file_path.startswith(os.path.realpath(DIST_DIR)) and os.path.isfile(file_path):
    return FileResponse(file_path)
```

---

### 🟠 6. MAJEUR — `/docs` et `/openapi.json` cassés

**Problème :** `jaspe_app` est créée avec `docs_url=None, redoc_url=None, openapi_url=None` — ce qui est bien, les docs de `jaspe_app` n'ont pas de raison d'exister. **MAIS**, comme `user_app` est montée à `/`, ses propres docs (`/docs`, `/redoc`, `/openapi.json`) sont accessibles, mais potentiellement cassées :

1. Le `root_path` de `user_app` peut être mal calculé par Starlette quand elle est montée comme sous-app
2. Le Swagger UI tentera de charger `/openapi.json` depuis le mauvais chemin

**Impact :** En production, `/docs` peut afficher une erreur "Failed to load API definition" ou pointer vers le mauvais endpoint.

**Correction :** L'architecture ASGI pure résout ce problème. Si on garde `mount()`, il faut s'assurer que le `root_path` n'est pas modifié :

```python
# Forcer le root_path vide car on monte à "/"
user_app.root_path = ""
```

---

### 🟠 7. MAJEUR — `dependency_overrides` cassés

**Problème :** Les `dependency_overrides` de `user_app` ne sont pas accessibles depuis `jaspe_app`, et vice-versa. Cela rend les tests d'intégration en contexte production-like impossibles si le test client est créé sur `jaspe_app`.

**Impact :** Mineur en production pure, mais bloquant pour quiconque utilise `TestClient(jaspe_app)` avec des mocks.

**Correction :** L'architecture ASGI pure élimine ce problème.

---

### 🟡 8. MINEUR — `BaseHTTPMiddleware` casse le streaming

**Problème :** `BaseHTTPMiddleware` intercale une queue `asyncio` entre le producteur et le consommateur des réponses. Cela :
- **Supprime le backpressure** : si le client est lent, les données s'accumulent en mémoire
- **Casse les `StreamingResponse`** : les headers ne sont envoyés qu'une fois la première itération terminée
- **Casse Server-Sent Events (SSE)** : le flush n'est pas propagé correctement

**Impact :** Toute app utilisant SSE (`text/event-stream`), streaming de fichiers, ou réponses chunked sera dégradée ou cassée.

**Correction :** Utiliser un middleware ASGI pur (cf. point 4).

---

### 🟡 9. MINEUR — Factory pattern incomplet

**Problème :** Le code détecte les factory patterns :
```python
if inspect.isfunction(user_app) and len(inspect.signature(user_app).parameters) == 0:
    user_app = user_app()
```

Mais il ne gère pas :
- Les callables (classes avec `__call__`)
- Les coroutines async (`async def create_app()`)
- Les factory avec arguments par défaut (`def create_app(debug=False)`)
- Les factory retournant un objet non-FastAPI (ex: Starlette pure)

**Correction :**
```python
import asyncio

if callable(user_app) and not isinstance(user_app, FastAPI):
    sig = inspect.signature(user_app)
    # Vérifier si tous les paramètres ont une valeur par défaut
    can_call = all(
        p.default is not inspect.Parameter.empty 
        for p in sig.parameters.values()
    )
    if can_call:
        result = user_app()
        if asyncio.iscoroutine(result):
            result = asyncio.get_event_loop().run_until_complete(result)
        user_app = result
```

---

### 🟡 10. MINEUR — Préfixes hardcodés

**Problème :** Le middleware SPA contient :
```python
if request.url.path.startswith("/api") or request.url.path.startswith("/assets"):
```

Ces valeurs sont hardcodées mais proviennent de `jaspe.toml` (`api_prefix` et `assets_prefix`). Si l'utilisateur configure `api_prefix = "/v1"`, le fallback SPA cassera les routes API en les redirigeant vers `index.html`.

**Correction :** Les préfixes doivent être injectés dynamiquement lors de la génération du runner :
```python
API_PREFIX = "{api_prefix}"     # Injecté par Jaspe
ASSETS_PREFIX = "{assets_prefix}" # Injecté par Jaspe

# ...
if request.url.path.startswith(API_PREFIX) or request.url.path.startswith(ASSETS_PREFIX):
```

> [!NOTE]
> Vérifier si Jaspe les injecte déjà lors de la génération (template string). Si c'est le cas, ce point est déjà OK dans Jaspe mais le runner actuel sur le serveur a les bonnes valeurs `/api` et `/assets`. À confirmer.

---

### 🟠 11. MAJEUR — Variables d'environnement systemd mal échappées

> [!WARNING]
> Ce n'est pas dans `runner.py` mais dans la génération du fichier `.service` par Jaspe. C'est cependant critique pour le bon fonctionnement du wrapper en production.

**Problème observé :** Le fichier unit systemd contient :
```ini
Environment=CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,...,http://82.25.112.182:4582
Environment=ADMIN_PASSWORD=Univ.LILLE@BB62*$
```

**Deux bugs :**
1. **Virgules** : systemd interprète les virgules dans `Environment=` comme des séparateurs d'assignations multiples. `http://82.25.112.182:4582` est interprété comme une variable distincte et rejeté (`Invalid environment assignment, ignoring: 82.25.112.182`). La valeur de `CORS_ORIGINS` est **tronquée**.
2. **Dollar `$`** : systemd interprète `$` comme une expansion de variable. `Univ.LILLE@BB62*$` perd son `$` final, corrompant le mot de passe.

**Correction :** Jaspe doit wrapper chaque assignation entre guillemets et échapper les `$` :
```ini
Environment="CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,...,http://82.25.112.182:4582"
Environment="ADMIN_PASSWORD=Univ.LILLE@BB62*$$"
```

Ou mieux : utiliser `EnvironmentFile=` avec un fichier `.env` séparé (plus simple, pas de parsing systemd complexe) :
```ini
EnvironmentFile=/home/coodlab-lino/vitae-cms/.jaspe/env
```

---

## Proposition d'architecture cible

Le fix fondamental est de **remplacer `mount()` par un wrapper ASGI pur** qui agit comme un proxy transparent :

```python
import sys, os, inspect

sys.path.insert(0, "{backend_path}")

from {entrypoint_module} import {entrypoint_var} as user_app

# Factory pattern support
if callable(user_app) and not hasattr(user_app, "__call__"):
    user_app = user_app()

from starlette.staticfiles import StaticFiles
from starlette.responses import FileResponse

DIST_DIR = "{dist_path}"
ASSETS_DIR = os.path.join(DIST_DIR, "assets")
INDEX_HTML = os.path.join(DIST_DIR, "index.html")
API_PREFIX = "{api_prefix}"
ASSETS_PREFIX = "{assets_prefix}"

static_app = StaticFiles(directory=ASSETS_DIR) if os.path.isdir(ASSETS_DIR) else None


class JaspeWrapper:
    """
    Wrapper ASGI transparent — NE MONTE PAS l'app utilisateur.
    Agit comme un reverse-proxy en interceptant uniquement les requêtes
    pour les fichiers statiques et le fallback SPA.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        # Propager lifespan directement
        if scope["type"] in ("lifespan", "websocket"):
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # 1. Assets Vite — servir directement
        if path.startswith(ASSETS_PREFIX) and static_app:
            scope["path"] = path[len(ASSETS_PREFIX):]
            scope["root_path"] = ASSETS_PREFIX
            await static_app(scope, receive, send)
            return

        # 2. Routes API — passer à l'app utilisateur telle quelle
        if path.startswith(API_PREFIX):
            await self.app(scope, receive, send)
            return

        # 3. Fichier statique racine (favicon.ico, robots.txt, etc.)
        candidate = os.path.realpath(os.path.join(DIST_DIR, path.lstrip("/")))
        if candidate.startswith(os.path.realpath(DIST_DIR)) and os.path.isfile(candidate):
            response = FileResponse(candidate)
            await response(scope, receive, send)
            return

        # 4. Tenter l'app utilisateur (routes custom hors API, /uploads, etc.)
        #    Si 404 → fallback SPA
        status_code = None
        headers_sent = False
        response_started = False
        original_body = []

        async def capture_send(message):
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
                response_started = True
            if status_code == 404 and not path.startswith(API_PREFIX):
                # On ne transmet pas — on va fallback
                return
            await send(message)

        await self.app(scope, receive, capture_send)

        if status_code == 404 and not _looks_like_file(path):
            # Fallback SPA
            response = FileResponse(INDEX_HTML)
            await response(scope, receive, send)


def _looks_like_file(path: str) -> bool:
    last = path.rsplit("/", 1)[-1]
    return "." in last


# L'app ASGI exposée à uvicorn
jaspe_app = JaspeWrapper(user_app)
```

**Avantages de cette approche :**
- ✅ Le lifespan est propagé nativement
- ✅ Tous les middlewares de l'app utilisateur s'appliquent à toutes les réponses
- ✅ Les exception handlers fonctionnent
- ✅ WebSocket fonctionne
- ✅ Streaming/SSE fonctionne
- ✅ `/docs` et `/openapi.json` fonctionnent
- ✅ Pas de path traversal
- ✅ `dependency_overrides` fonctionnent pour les tests

---

## Checklist de corrections

- [ ] **Runner :** Remplacer `mount()` par un wrapper ASGI pur
- [ ] **Runner :** Propager le lifespan de l'app utilisateur
- [ ] **Runner :** Utiliser un middleware ASGI pur (pas BaseHTTPMiddleware)
- [ ] **Runner :** Supporter WebSocket (ne pas intercepter `scope["type"] == "websocket"`)
- [ ] **Runner :** Protéger contre le path traversal (`os.path.realpath` + vérification de préfixe)
- [ ] **Runner :** Injecter dynamiquement `api_prefix` et `assets_prefix` depuis `jaspe.toml`
- [ ] **Runner :** Améliorer la détection du factory pattern (async, callables, args par défaut)
- [ ] **Systemd :** Wrapper les valeurs `Environment=` entre guillemets
- [ ] **Systemd :** Échapper les `$` en `$$`
- [ ] **Systemd :** Envisager `EnvironmentFile=` comme alternative plus robuste
- [ ] **Runner :** Ne pas bloquer `/docs`/`/openapi.json` si l'utilisateur les active
