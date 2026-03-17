from __future__ import annotations

import os
import shutil
import tarfile
from datetime import date
from pathlib import Path
from typing import Any

from .config import load_config
from .db import audit, execute, fetchall, fetchone, init_db
from .utils import (
    days_left,
    ensure_root,
    human_bytes,
    make_cert_cn,
    parse_connected_common_names,
    plus_days_iso,
    read_pem_block,
    run,
    sanitize_name,
    today_iso,
)


def bootstrap_database(server_host: str, protocol: str, port: int, bot_token: str = "", admin_ids: list[str] | None = None, notify_chat_id: str = "") -> None:
    init_db()
    execute("DELETE FROM configs")
    execute(
        "INSERT INTO configs(id, server_host, protocol, port, subnet, netmask) VALUES (1, ?, ?, ?, '10.8.0.0', '255.255.255.0')",
        (server_host, protocol, int(port)),
    )
    execute("DELETE FROM remotes")
    execute("INSERT INTO remotes(remote_host) VALUES (?)", (server_host,))
    execute(
        "UPDATE telegram_settings SET bot_token = ?, admin_ids = ?, notify_chat_id = ?, enabled = ? WHERE id = 1",
        (bot_token, ",".join(admin_ids or []), notify_chat_id, 1 if bot_token else 0),
    )
    for admin_id in admin_ids or []:
        execute("INSERT OR IGNORE INTO bot_users(telegram_id, can_manage) VALUES (?, 1)", (str(admin_id),))
    audit("installer", "bootstrap_database", f"host={server_host} proto={protocol} port={port}")


def current_config() -> dict[str, Any]:
    row = fetchone("SELECT * FROM configs WHERE id = 1")
    if not row:
        raise RuntimeError("Основная конфигурация в БД не найдена.")
    return dict(row)


def current_remotes() -> list[str]:
    return [row[0] for row in fetchall("SELECT remote_host FROM remotes ORDER BY id ASC")]


def set_primary_remote(remote_host: str) -> None:
    remote_host = remote_host.strip()
    if not remote_host:
        raise ValueError("remote_host пустой")
    execute("UPDATE configs SET server_host = ? WHERE id = 1", (remote_host,))
    execute("UPDATE remotes SET remote_host = ? WHERE id = (SELECT id FROM remotes ORDER BY id ASC LIMIT 1)", (remote_host,))
    audit("menu", "set_primary_remote", remote_host)
    for client in list_clients(raw=True):
        regenerate_profile(client["key_name"])


def add_remote(remote_host: str) -> None:
    execute("INSERT INTO remotes(remote_host) VALUES (?)", (remote_host.strip(),))
    audit("menu", "add_remote", remote_host.strip())


def delete_remote(remote_host: str) -> None:
    rows = current_remotes()
    if not rows or rows[0] == remote_host:
        raise ValueError("Нельзя удалить основной remote")
    execute("DELETE FROM remotes WHERE remote_host = ?", (remote_host,))
    audit("menu", "delete_remote", remote_host)


def telegram_settings() -> dict[str, Any]:
    row = fetchone("SELECT * FROM telegram_settings WHERE id = 1")
    return dict(row) if row else {"bot_token": "", "admin_ids": "", "notify_chat_id": "", "enabled": 0}


def set_telegram_settings(bot_token: str | None = None, admin_ids: list[str] | None = None, notify_chat_id: str | None = None, enabled: bool | None = None) -> None:
    row = telegram_settings()
    bot_token = row["bot_token"] if bot_token is None else bot_token
    admin_ids_value = row["admin_ids"] if admin_ids is None else ",".join([str(x).strip() for x in admin_ids if str(x).strip()])
    notify_chat_id = row["notify_chat_id"] if notify_chat_id is None else notify_chat_id
    enabled_value = row["enabled"] if enabled is None else int(bool(enabled))
    execute(
        "UPDATE telegram_settings SET bot_token = ?, admin_ids = ?, notify_chat_id = ?, enabled = ? WHERE id = 1",
        (bot_token, admin_ids_value, notify_chat_id, enabled_value),
    )
    if admin_ids is not None:
        for admin_id in admin_ids:
            execute("INSERT OR IGNORE INTO bot_users(telegram_id, can_manage) VALUES (?, 1)", (str(admin_id),))
    audit("menu", "set_telegram_settings", f"enabled={enabled_value}")


def allowed_bot_users() -> list[str]:
    return [row[0] for row in fetchall("SELECT telegram_id FROM bot_users ORDER BY telegram_id")]


def add_bot_user(telegram_id: str) -> None:
    execute("INSERT OR IGNORE INTO bot_users(telegram_id, can_manage) VALUES (?, 1)", (str(telegram_id),))
    audit("bot-admin", "add_bot_user", str(telegram_id))


def remove_bot_user(telegram_id: str) -> None:
    execute("DELETE FROM bot_users WHERE telegram_id = ?", (str(telegram_id),))
    audit("bot-admin", "remove_bot_user", str(telegram_id))


def _easyrsa_env() -> dict[str, str]:
    """Return a safe Easy-RSA environment.

    IMPORTANT: Do NOT set EASYRSA_REQ_CN/EASYRSA_CN here.
    In Easy-RSA 3.1+, build-server-full/build-client-full do not support an external commonName.
    """
    env = dict(os.environ)
    env.update(
        {
            'EASYRSA_BATCH': '1',
            'EASYRSA_CERT_EXPIRE': '3650',
            'EASYRSA_DIGEST': 'sha256',
        }
    )
    env.pop('EASYRSA_REQ_CN', None)
    env.pop('EASYRSA_CN', None)
    return env


def _client_row(key_name: str):
    row = fetchone("SELECT * FROM clients WHERE key_name = ?", (sanitize_name(key_name),))
    if not row:
        raise ValueError(f"Клиент '{key_name}' не найден")
    return row


def restart_openvpn() -> None:
    service = load_config()["service_name"]
    run(["systemctl", "restart", service], check=False)


def start_openvpn() -> None:
    service = load_config()["service_name"]
    run(["systemctl", "start", service], check=False)


def stop_openvpn() -> None:
    service = load_config()["service_name"]
    run(["systemctl", "stop", service], check=False)


def service_status_text() -> str:
    service = load_config()["service_name"]
    proc = run(["systemctl", "is-active", service], check=False, capture_output=True)
    return proc.stdout.strip() or proc.stderr.strip() or "unknown"


def _sync_crl() -> None:
    cfg = load_config()
    easyrsa = Path(cfg["easy_rsa_dir"])
    pki = easyrsa / "pki"
    crl = pki / "crl.pem"
    if crl.exists():
        shutil.copy2(crl, Path(cfg["server_dir"]) / "crl.pem")
        Path(cfg["server_dir"]).joinpath("crl.pem").chmod(0o644)


def _revoke_cert(cert_cn: str) -> None:
    cfg = load_config()
    easyrsa = Path(cfg["easy_rsa_dir"])
    if not easyrsa.exists():
        return
    run(["bash", "-lc", f"cd {easyrsa} && ./easyrsa --batch revoke '{cert_cn}' && ./easyrsa gen-crl"], check=False)
    _sync_crl()
    restart_openvpn()


def _render_client_profile(cert_cn: str) -> str:
    cfg = load_config()
    config = current_config()
    easyrsa_dir = Path(cfg["easy_rsa_dir"])
    pki = easyrsa_dir / "pki"
    cert = pki / "issued" / f"{cert_cn}.crt"
    key = pki / "private" / f"{cert_cn}.key"
    ca = Path(cfg["server_dir"]) / "ca.crt"
    ta = Path(cfg["server_dir"]) / "tls-crypt.key"
    remotes = current_remotes()
    remote_lines = "\n".join([f"remote {host} {config['port']}" for host in remotes])
    return f"""client
nobind
dev tun
proto {config['protocol']}
remote-random
resolv-retry infinite
persist-key
persist-tun
remote-cert-tls server
auth SHA256
data-ciphers AES-256-GCM:AES-128-GCM:CHACHA20-POLY1305
verb 3
{remote_lines}
<ca>
{read_pem_block(ca)}
</ca>
<cert>
{read_pem_block(cert)}
</cert>
<key>
{read_pem_block(key)}
</key>
<tls-crypt>
{read_pem_block(ta)}
</tls-crypt>
"""


def create_client(key_name: str, validity_days: int, actor: str = "menu") -> dict[str, Any]:
    ensure_root()
    cfg = load_config()
    key_name = sanitize_name(key_name)
    if fetchone("SELECT 1 FROM clients WHERE key_name = ?", (key_name,)):
        raise ValueError(f"Клиент '{key_name}' уже существует")
    cert_cn = make_cert_cn(key_name)
    easyrsa_dir = Path(cfg["easy_rsa_dir"])
    run(["bash", "-lc", f"cd {easyrsa_dir} && ./easyrsa --batch build-client-full '{cert_cn}' nopass"], env=_easyrsa_env())
    client_dir = Path(cfg["client_dir"]) / key_name
    client_dir.mkdir(parents=True, exist_ok=True)
    profile_text = _render_client_profile(cert_cn)
    profile_path = client_dir / f"{key_name}.ovpn"
    profile_path.write_text(profile_text, encoding="utf-8")
    profile_path.chmod(0o600)
    export_dir = Path(cfg["export_dir"])
    export_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(profile_path, export_dir / profile_path.name)
    expiration = plus_days_iso(int(validity_days))
    execute(
        "INSERT INTO clients(key_name, cert_cn, created_date, expiration_date, active, profile_path) VALUES (?, ?, ?, ?, 1, ?)",
        (key_name, cert_cn, today_iso(), expiration, str(profile_path)),
    )
    audit(actor, "create_client", f"{key_name} cert_cn={cert_cn} days={validity_days}")
    return {"key_name": key_name, "cert_cn": cert_cn, "profile_path": str(profile_path), "expiration_date": expiration}


def regenerate_profile(key_name: str) -> str:
    row = _client_row(key_name)
    profile_text = _render_client_profile(row["cert_cn"])
    profile_path = Path(row["profile_path"])
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(profile_text, encoding="utf-8")
    profile_path.chmod(0o600)
    export_dir = Path(load_config()["export_dir"])
    export_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(profile_path, export_dir / profile_path.name)
    audit("system", "regenerate_profile", row["key_name"])
    return str(profile_path)


def recreate_client(key_name: str, actor: str = "menu") -> dict[str, Any]:
    ensure_root()
    row = _client_row(key_name)
    remaining_days = max(days_left(row["expiration_date"]) or 30, 1)
    old_cn = row["cert_cn"]
    _revoke_cert(old_cn)
    new_cn = make_cert_cn(row["key_name"])
    cfg = load_config()
    easyrsa_dir = Path(cfg["easy_rsa_dir"])
    run(["bash", "-lc", f"cd {easyrsa_dir} && ./easyrsa --batch build-client-full '{new_cn}' nopass"], env=_easyrsa_env())
    execute("UPDATE clients SET cert_cn = ?, active = 1, expiration_date = ? WHERE key_name = ?", (new_cn, plus_days_iso(remaining_days), row["key_name"]))
    profile_path = regenerate_profile(row["key_name"])
    unblock_client(row["key_name"], actor="system")
    audit(actor, "recreate_client", f"{row['key_name']} old={old_cn} new={new_cn}")
    return {"key_name": row["key_name"], "cert_cn": new_cn, "profile_path": profile_path}


def delete_client(key_name: str, actor: str = "menu") -> None:
    ensure_root()
    row = _client_row(key_name)
    _revoke_cert(row["cert_cn"])
    profile_path = Path(row["profile_path"])
    client_dir = profile_path.parent
    export_file = Path(load_config()["export_dir"]) / profile_path.name
    if export_file.exists():
        export_file.unlink()
    if client_dir.exists():
        shutil.rmtree(client_dir, ignore_errors=True)
    ccd_file = Path(load_config()["ccd_dir"]) / row["cert_cn"]
    if ccd_file.exists():
        ccd_file.unlink()
    execute("DELETE FROM clients WHERE key_name = ?", (row["key_name"],))
    audit(actor, "delete_client", row["key_name"])


def block_client(key_name: str, actor: str = "menu") -> None:
    row = _client_row(key_name)
    ccd_dir = Path(load_config()["ccd_dir"])
    ccd_dir.mkdir(parents=True, exist_ok=True)
    (ccd_dir / row["cert_cn"]).write_text("disable\n", encoding="utf-8")
    execute("UPDATE clients SET active = 0 WHERE key_name = ?", (row["key_name"],))
    audit(actor, "block_client", row["key_name"])
    restart_openvpn()


def unblock_client(key_name: str, actor: str = "menu") -> None:
    row = _client_row(key_name)
    ccd_file = Path(load_config()["ccd_dir"]) / row["cert_cn"]
    if ccd_file.exists():
        ccd_file.unlink()
    execute("UPDATE clients SET active = 1 WHERE key_name = ?", (row["key_name"],))
    audit(actor, "unblock_client", row["key_name"])
    restart_openvpn()


def extend_client(key_name: str, add_days: int, actor: str = "menu") -> str:
    row = _client_row(key_name)
    base = date.today()
    if row["expiration_date"]:
        base = max(base, date.fromisoformat(row["expiration_date"]))
    new_date = base.fromordinal(base.toordinal() + int(add_days)).isoformat()
    execute("UPDATE clients SET expiration_date = ? WHERE key_name = ?", (new_date, row["key_name"]))
    audit(actor, "extend_client", f"{row['key_name']} +{add_days} => {new_date}")
    return new_date


def list_clients(*, raw: bool = False) -> list[dict[str, Any]]:
    rows = fetchall("SELECT * FROM clients ORDER BY key_name COLLATE NOCASE")
    connected_cns = parse_connected_common_names(load_config()["status_file"])
    result = []
    for row in rows:
        d = dict(row)
        d["days_left"] = days_left(d["expiration_date"])
        d["connected"] = d["cert_cn"] in connected_cns
        d["traffic_human"] = human_bytes(d["traffic_used"])
        result.append(d)
    return result


def connected_clients() -> list[dict[str, Any]]:
    connected_cns = parse_connected_common_names(load_config()["status_file"])
    if not connected_cns:
        return []
    result = []
    for cn in connected_cns:
        row = fetchone("SELECT key_name, cert_cn FROM clients WHERE cert_cn = ?", (cn,))
        if row:
            result.append({"key_name": row["key_name"], "cert_cn": row["cert_cn"]})
        else:
            result.append({"key_name": cn, "cert_cn": cn})
    return result


def update_traffic(cert_cn: str, rx_bytes: int, tx_bytes: int) -> None:
    total = int(rx_bytes or 0) + int(tx_bytes or 0)
    execute(
        "UPDATE clients SET traffic_used = traffic_used + ?, last_connected_at = CURRENT_TIMESTAMP WHERE cert_cn = ?",
        (total, cert_cn),
    )


def sync_expired_clients() -> list[str]:
    blocked = []
    for client in list_clients(raw=True):
        left = days_left(client["expiration_date"])
        if client["expiration_date"] and left is not None and left < 0 and client["active"]:
            block_client(client["key_name"], actor="expiry-worker")
            blocked.append(client["key_name"])
    return blocked


def backup_all(output_path: str | None = None) -> str:
    cfg = load_config()
    if output_path is None:
        output_path = f"/root/ovpnmgr-backup-{date.today().isoformat()}.tar.gz"
    files_to_pack = [
        cfg["db_path"],
        cfg["server_dir"],
        cfg["easy_rsa_dir"],
        cfg["client_dir"],
        cfg["export_dir"],
        "/etc/ovpnmgr/config.json",
    ]
    with tarfile.open(output_path, "w:gz") as tar:
        for item in files_to_pack:
            path = Path(item)
            if path.exists():
                tar.add(path, arcname=path.relative_to("/") if path.is_absolute() else path)
    audit("menu", "backup_all", output_path)
    return output_path


def summary_text() -> str:
    clients = list_clients(raw=True)
    connected = connected_clients()
    cfg = current_config()
    return (
        f"OpenVPN: {service_status_text()}\n"
        f"Remote: {cfg['server_host']}:{cfg['port']}/{cfg['protocol']}\n"
        f"Ключей: {len(clients)} | Подключено: {len(connected)}"
    )
