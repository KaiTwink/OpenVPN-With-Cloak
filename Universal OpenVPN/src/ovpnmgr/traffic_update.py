from __future__ import annotations

import sys

from .openvpn import update_traffic


def main() -> int:
    if len(sys.argv) < 4:
        return 1
    cert_cn = sys.argv[1]
    rx = int(sys.argv[2] or 0)
    tx = int(sys.argv[3] or 0)
    update_traffic(cert_cn, rx, tx)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
