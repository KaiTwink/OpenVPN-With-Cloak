from __future__ import annotations

from .openvpn import sync_expired_clients


def main() -> int:
    sync_expired_clients()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
