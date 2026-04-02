import json
from pathlib import Path

JASPE_HOME = Path.home() / ".jaspe"
REGISTRY_PATH = JASPE_HOME / "registry.json"


def create_jaspe_home_if_missing() -> None:
    JASPE_HOME.mkdir(parents=True, exist_ok=True)


def create_registry_file_if_missing() -> None:
    create_jaspe_home_if_missing()
    if not REGISTRY_PATH.exists():
        REGISTRY_PATH.write_text(json.dumps({"apps": {}}, indent=2), encoding="utf-8")


def read_registry() -> dict:
    create_registry_file_if_missing()
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def write_registry(data: dict) -> None:
    create_registry_file_if_missing()
    REGISTRY_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def add_or_update_app(app_name: str, path: str, port: int, status: str) -> None:
    data = read_registry()
    data["apps"][app_name] = {
        "path": path,
        "port": port,
        "status": status,
    }
    write_registry(data)


def remove_app(app_name: str) -> None:
    data = read_registry()
    data["apps"].pop(app_name, None)
    write_registry(data)


def get_app_path(app_name: str) -> str | None:
    data = read_registry()
    app = data["apps"].get(app_name)
    return app["path"] if app else None
