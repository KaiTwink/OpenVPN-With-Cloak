#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_ROOT="/opt/ovpnmgr"
VENV_DIR="$TARGET_ROOT/venv"
CONFIG_DIR="/etc/ovpnmgr"
CONFIG_FILE="$CONFIG_DIR/config.json"
DB_PATH="$CONFIG_DIR/openvpn.db"
SERVER_DIR="/etc/openvpn/server"
CLIENT_DIR="/etc/openvpn/clients"
CCD_DIR="/etc/openvpn/ccd"
EASYRSA_DIR="/etc/openvpn/easy-rsa"
EXPORT_DIR="/root/OpenVPNKeys"
HOOKS_DIR="$TARGET_ROOT/src/ovpnmgr/hooks"
LOG_DIR="/var/log/openvpn"
SERVICE_NAME="openvpn-server@server.service"

log() { echo "[$(date '+%F %T')] $*"; }
warn() { echo "[$(date '+%F %T')] WARNING: $*" >&2; }
die() { echo "[$(date '+%F %T')] ERROR: $*" >&2; exit 1; }

require_root() {
  [[ ${EUID:-$(id -u)} -eq 0 ]] || die "Запустите install.sh от root"
}

repair_apt() {
  export DEBIAN_FRONTEND=noninteractive
  dpkg --configure -a || true
  apt-get -f install -y || true
  apt-get update -y
}

install_packages() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get install -y \
    openvpn easy-rsa sqlite3 docker.io python3 python3-venv python3-pip \
    curl ca-certificates iptables-persistent netfilter-persistent unzip jq
  systemctl enable --now docker || true
}

ask_value() {
  local prompt="$1" default="${2:-}" value=""
  if [[ -n "$default" ]]; then
    read -r -p "$prompt [$default]: " value || true
    printf '%s\n' "${value:-$default}"
  else
    read -r -p "$prompt: " value || true
    printf '%s\n' "$value"
  fi
}

collect_inputs() {
  SERVER_HOST="$(ask_value 'Домен или IP адрес OpenVPN' '')"
  [[ -n "$SERVER_HOST" ]] || die "Домен или IP адрес обязателен"
  OVPN_PROTO="$(ask_value 'Протокол основного OpenVPN (udp/tcp)' 'udp')"
  [[ "$OVPN_PROTO" == "udp" || "$OVPN_PROTO" == "tcp" ]] || die "Протокол должен быть udp или tcp"
  OVPN_PORT="$(ask_value 'Порт основного OpenVPN' '443')"
  [[ "$OVPN_PORT" =~ ^[0-9]+$ ]] || die "Порт должен быть числом"
  BOT_TOKEN="$(ask_value 'Токен Telegram бота (можно оставить пустым)' '')"
  BOT_ADMIN_IDS=""
  BOT_NOTIFY_CHAT_ID=""
  if [[ -n "$BOT_TOKEN" ]]; then
    BOT_ADMIN_IDS="$(ask_value 'Telegram admin IDs через запятую' '')"
    BOT_NOTIFY_CHAT_ID="$(ask_value 'Telegram chat ID для уведомлений/бэкапов (можно пустым)' '')"
  fi
}

copy_project() {
  rm -rf "$TARGET_ROOT"
  mkdir -p "$TARGET_ROOT"
  cp -a "$PROJECT_ROOT"/* "$TARGET_ROOT"/
}

setup_python() {
  python3 -m venv "$VENV_DIR"
  "$VENV_DIR/bin/pip" install --upgrade pip wheel
  "$VENV_DIR/bin/pip" install -r "$TARGET_ROOT/requirements.txt"
}

write_config() {
  if ! systemctl list-unit-files | grep -q '^openvpn-server@'; then
    SERVICE_NAME="openvpn@server.service"
  fi
  python3 - <<PY
import json
from pathlib import Path
cfg = {
  "db_path": "$DB_PATH",
  "easy_rsa_dir": "$EASYRSA_DIR",
  "server_dir": "$SERVER_DIR",
  "ccd_dir": "$CCD_DIR",
  "client_dir": "$CLIENT_DIR",
  "export_dir": "$EXPORT_DIR",
  "status_file": "$LOG_DIR/openvpn-status.log",
  "server_log": "$LOG_DIR/server.log",
  "service_name": "$SERVICE_NAME",
  "hook_python": "$VENV_DIR/bin/python",
  "server_host": "$SERVER_HOST",
  "server_proto": "$OVPN_PROTO",
  "server_port": int("$OVPN_PORT"),
  "server_subnet": "10.8.0.0",
  "server_netmask": "255.255.255.0",
  "dns_1": "1.1.1.1",
  "dns_2": "1.0.0.1",
  "bot_enabled": bool("$BOT_TOKEN"),
  "bot_token": "$BOT_TOKEN",
  "bot_admin_ids": [x.strip() for x in "$BOT_ADMIN_IDS".split(",") if x.strip()],
  "bot_notify_chat_id": "$BOT_NOTIFY_CHAT_ID",
  "project_root": "$TARGET_ROOT",
}
Path("$CONFIG_DIR").mkdir(parents=True, exist_ok=True)
Path("$CONFIG_FILE").write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY
}

bootstrap_db() {
  PYTHONPATH="$TARGET_ROOT/src" "$VENV_DIR/bin/python" - <<PY
from ovpnmgr.openvpn import bootstrap_database
bootstrap_database(
    server_host="$SERVER_HOST",
    protocol="$OVPN_PROTO",
    port=int("$OVPN_PORT"),
    bot_token="$BOT_TOKEN",
    admin_ids=[x.strip() for x in "$BOT_ADMIN_IDS".split(",") if x.strip()],
    notify_chat_id="$BOT_NOTIFY_CHAT_ID",
)
PY
}

setup_dirs() {
  mkdir -p "$SERVER_DIR" "$CLIENT_DIR" "$CCD_DIR" "$EXPORT_DIR" "$LOG_DIR" "$CONFIG_DIR" /var/lib/openvpn
  chmod 700 "$EXPORT_DIR"
  chmod +x "$HOOKS_DIR/client-disconnect.sh"
}

setup_pki() {
  if [[ ! -d "$EASYRSA_DIR" ]]; then
    make-cadir "$EASYRSA_DIR"
  fi
  pushd "$EASYRSA_DIR" >/dev/null
  export EASYRSA_BATCH=1
  export EASYRSA_DIGEST=sha256

  # CA can have a custom CN, but build-*-full does NOT allow external CN in recent Easy-RSA.
  if [[ ! -d pki ]]; then
    ./easyrsa init-pki
    EASYRSA_REQ_CN="$SERVER_HOST-CA" ./easyrsa build-ca nopass
  fi

  # Ensure no external CN leaks into server/client cert generation.
  unset EASYRSA_REQ_CN EASYRSA_CN

  if [[ ! -f pki/issued/server.crt ]]; then
    # Clean possible leftovers from a failed previous attempt
    rm -f pki/reqs/server.req pki/private/server.key pki/issued/server.crt
    ./easyrsa build-server-full server nopass
  fi
  if [[ ! -f pki/dh.pem ]]; then
    ./easyrsa gen-dh
  fi
  ./easyrsa gen-crl
  popd >/dev/null

  cp "$EASYRSA_DIR/pki/ca.crt" "$SERVER_DIR/ca.crt"
  cp "$EASYRSA_DIR/pki/issued/server.crt" "$SERVER_DIR/server.crt"
  cp "$EASYRSA_DIR/pki/private/server.key" "$SERVER_DIR/server.key"
  cp "$EASYRSA_DIR/pki/dh.pem" "$SERVER_DIR/dh.pem"
  cp "$EASYRSA_DIR/pki/crl.pem" "$SERVER_DIR/crl.pem"
  chmod 644 "$SERVER_DIR/ca.crt" "$SERVER_DIR/server.crt" "$SERVER_DIR/dh.pem" "$SERVER_DIR/crl.pem"
  chmod 600 "$SERVER_DIR/server.key"
  if [[ ! -f "$SERVER_DIR/tls-crypt.key" ]]; then
    openvpn --genkey secret "$SERVER_DIR/tls-crypt.key"
  fi
  chmod 600 "$SERVER_DIR/tls-crypt.key"
}

write_server_config() {
  cat > "$SERVER_DIR/server.conf" <<CONF
port $OVPN_PORT
proto $OVPN_PROTO
dev tun
user nobody
group nogroup
persist-key
persist-tun
topology subnet
server 10.8.0.0 255.255.255.0
ifconfig-pool-persist /var/lib/openvpn/ipp.txt
push "redirect-gateway def1 bypass-dhcp"
push "dhcp-option DNS 1.1.1.1"
push "dhcp-option DNS 1.0.0.1"
keepalive 10 120
tls-server
tls-version-min 1.2
ca $SERVER_DIR/ca.crt
cert $SERVER_DIR/server.crt
key $SERVER_DIR/server.key
dh $SERVER_DIR/dh.pem
tls-crypt $SERVER_DIR/tls-crypt.key
data-ciphers AES-256-GCM:AES-128-GCM:CHACHA20-POLY1305
data-ciphers-fallback AES-256-CBC
auth SHA256
crl-verify $SERVER_DIR/crl.pem
client-config-dir $CCD_DIR
status $LOG_DIR/openvpn-status.log
log-append $LOG_DIR/server.log
verb 3
script-security 2
client-disconnect $HOOKS_DIR/client-disconnect.sh
CONF
  if [[ "$OVPN_PROTO" == "udp" ]]; then
    echo 'explicit-exit-notify 1' >> "$SERVER_DIR/server.conf"
  fi
}

setup_sysctl_fw() {
  cat >/etc/sysctl.d/99-ovpnmgr.conf <<CONF
net.ipv4.ip_forward=1
CONF
  sysctl --system >/dev/null
  local iface
  iface="$(ip route show default | awk '/default/ {print $5; exit}')"
  [[ -n "$iface" ]] || die "Не удалось определить внешний интерфейс"
  iptables -C INPUT -p "$OVPN_PROTO" --dport "$OVPN_PORT" -j ACCEPT 2>/dev/null || iptables -A INPUT -p "$OVPN_PROTO" --dport "$OVPN_PORT" -j ACCEPT
  iptables -C FORWARD -s 10.8.0.0/24 -j ACCEPT 2>/dev/null || iptables -A FORWARD -s 10.8.0.0/24 -j ACCEPT
  iptables -C FORWARD -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || iptables -A FORWARD -m state --state RELATED,ESTABLISHED -j ACCEPT
  iptables -t nat -C POSTROUTING -s 10.8.0.0/24 -o "$iface" -j MASQUERADE 2>/dev/null || iptables -t nat -A POSTROUTING -s 10.8.0.0/24 -o "$iface" -j MASQUERADE
  netfilter-persistent save || true
  if command -v ufw >/dev/null 2>&1; then
    ufw allow "$OVPN_PORT/$OVPN_PROTO" || true
  fi
}

install_wrappers() {
  cat >/usr/local/bin/ovpnmenu <<CONF
#!/usr/bin/env bash
PYTHONPATH="$TARGET_ROOT/src" exec "$VENV_DIR/bin/python" -m ovpnmgr.menu "\$@"
CONF
  chmod +x /usr/local/bin/ovpnmenu
  cat >/usr/local/bin/ovpnbot <<CONF
#!/usr/bin/env bash
PYTHONPATH="$TARGET_ROOT/src" exec "$VENV_DIR/bin/python" -m ovpnmgr.bot "\$@"
CONF
  chmod +x /usr/local/bin/ovpnbot
}

install_systemd() {
  cp "$TARGET_ROOT/systemd/ovpnmgr-expiry.service" /etc/systemd/system/
  cp "$TARGET_ROOT/systemd/ovpnmgr-expiry.timer" /etc/systemd/system/
  if [[ -n "$BOT_TOKEN" ]]; then
    cp "$TARGET_ROOT/systemd/ovpnmgr-bot.service" /etc/systemd/system/
  fi
  systemctl daemon-reload
  if systemctl list-unit-files | grep -q '^openvpn-server@'; then
    systemctl enable --now openvpn-server@server.service
  else
    mkdir -p /etc/openvpn
    cp "$SERVER_DIR/server.conf" /etc/openvpn/server.conf
    systemctl enable --now openvpn@server.service
  fi
  systemctl enable --now ovpnmgr-expiry.timer
  if [[ -n "$BOT_TOKEN" ]]; then
    systemctl enable --now ovpnmgr-bot.service
  fi
}

print_summary() {
  cat <<CONF

Установка завершена.

Команды:
  ovpnmenu                 - меню управления
  ovpnbot                  - запуск бота вручную
  systemctl status $SERVICE_NAME

Пути:
  База данных: $DB_PATH
  Конфиг OpenVPN: $SERVER_DIR/server.conf
  Клиентские файлы: $EXPORT_DIR
  Проект: $TARGET_ROOT

Подключение:
  $SERVER_HOST:$OVPN_PORT/$OVPN_PROTO
CONF
}

main() {
  require_root
  repair_apt
  install_packages
  collect_inputs
  copy_project
  setup_python
  setup_dirs
  write_config
  bootstrap_db
  setup_pki
  write_server_config
  setup_sysctl_fw
  install_wrappers
  install_systemd
  print_summary
}

main "$@"
