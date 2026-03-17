from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

DEFAULT_CONFIG_PATH = Path(os.environ.get("OVPNMGR_CONFIG", "/etc/ovpnmgr/config.json"))

DEFAULTS: Dict[str, Any] = {
    "db_path": "/etc/ovpnmgr/openvpn.db",
    "easy_rsa_dir": "/etc/openvpn/easy-rsa",
    "server_dir": "/etc/openvpn/server",
    "ccd_dir": "/etc/openvpn/ccd",
    "client_dir": "/etc/openvpn/clients",
    "export_dir": "/root/OpenVPNKeys",
    "status_file": "/var/log/openvpn/openvpn-status.log",
    "server_log": "/var/log/openvpn/server.log",
    "service_name": "openvpn-server@server.service",
    "hook_python": "/opt/ovpnmgr/venv/bin/python",
    "server_host": "127.0.0.1",
    "server_proto": "udp",
    "server_port": 443,
    "server_subnet": "10.8.0.0",
    "server_netmask": "255.255.255.0",
    "dns_1": "1.1.1.1",
    "dns_2": "1.0.0.1",
    "bot_enabled": False,
    "bot_token": "",
    "bot_admin_ids": [],
    "bot_notify_chat_id": "",
    "project_root": "/opt/ovpnmgr",
}


def load_config(path: Path | str | None = None) -> Dict[str, Any]:
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    data: Dict[str, Any] = DEFAULTS.copy()
    if cfg_path.exists():
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        data.update(raw)
    return data


def save_config(data: Dict[str, Any], path: Path | str | None = None) -> None:
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
