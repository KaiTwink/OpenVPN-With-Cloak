from __future__ import annotations

import os
import re
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, List, Set


def ensure_root() -> None:
    if os.geteuid() != 0:
        raise PermissionError("Этот скрипт нужно запускать от root.")


def run(cmd: list[str], *, check: bool = True, capture_output: bool = False, text: bool = True, env: dict | None = None):
    return subprocess.run(
        cmd,
        check=check,
        capture_output=capture_output,
        text=text,
        env=env,
    )


def sanitize_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", name.strip())
    cleaned = re.sub(r"-+", "-", cleaned).strip("-._")
    if not cleaned:
        raise ValueError("Имя пустое или содержит только недопустимые символы.")
    return cleaned[:48]


def make_cert_cn(key_name: str) -> str:
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    return f"{sanitize_name(key_name)}-{stamp}"


def today_iso() -> str:
    return date.today().isoformat()


def plus_days_iso(days: int) -> str:
    return (date.today()).fromordinal(date.today().toordinal() + int(days)).isoformat()


def days_left(expiration_date: str | None) -> int | None:
    if not expiration_date:
        return None
    return (date.fromisoformat(expiration_date) - date.today()).days


def human_bytes(size: int) -> str:
    size = int(size or 0)
    units = ["B", "KB", "MB", "GB", "TB"]
    num = float(size)
    for unit in units:
        if num < 1024.0 or unit == units[-1]:
            return f"{num:.2f} {unit}"
        num /= 1024.0
    return f"{size} B"


def read_pem_block(path: str | Path) -> str:
    text = Path(path).read_text(encoding="utf-8")
    return text.strip()


def get_default_interface() -> str | None:
    proc = run(["ip", "route", "show", "default"], check=False, capture_output=True)
    if proc.returncode != 0:
        return None
    m = re.search(r"dev\s+(\S+)", proc.stdout)
    return m.group(1) if m else None


def parse_connected_common_names(status_file: str | Path) -> Set[str]:
    path = Path(status_file)
    if not path.exists():
        return set()
    names: Set[str] = set()
    lines = [line.strip() for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]
    in_clients = False
    for line in lines:
        if line.startswith("CLIENT_LIST"):
            parts = line.split(",")
            if len(parts) >= 2:
                names.add(parts[1].strip())
            continue
        if line.startswith("Common Name,Real Address"):
            in_clients = True
            continue
        if line.startswith("ROUTING TABLE") or line.startswith("GLOBAL STATS") or line == "END":
            in_clients = False
            continue
        if in_clients:
            parts = line.split(",")
            if parts and parts[0].strip() and parts[0] != "Updated":
                names.add(parts[0].strip())
    return names
