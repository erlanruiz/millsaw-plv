#!/usr/bin/env python3
"""
Mill Saw FTP Server - runs on the saw PC.

Hosts an FTP server that accepts incoming .plv files into the configured
drop folder. Designed for Python 3.8 on Windows 7 (the last Windows
version supported by 3.8) and uses pyftpdlib (a small pure-Python FTP
server library).

Configuration is read from ftp_server.ini in the same folder as this
script. A default config is created on first run. Edit the file then
restart the listener.

The IT-side app (the one that generates PLVs) connects with the
configured user/password and uploads files via standard FTP.

If pyftpdlib is not installed, run:
    py -3.8 -m pip install pyftpdlib
or
    python -m pip install pyftpdlib
"""

from __future__ import annotations

import configparser
import datetime
import logging
import logging.handlers
import os
import sys
import threading

try:
    from pyftpdlib.authorizers import DummyAuthorizer
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import FTPServer
except ImportError:
    sys.stderr.write(
        "ERROR: pyftpdlib is not installed. Open Command Prompt and run:\n"
        "    python -m pip install pyftpdlib\n"
        "Then re-run this script.\n"
    )
    sys.exit(1)


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "ftp_server.ini")
LOG_PATH = os.path.join(SCRIPT_DIR, "ftp_server.log")


DEFAULT_CONFIG = """\
; Mill Saw FTP server configuration. Restart the service after editing.

[server]
; Port to bind. FTP standard is 21 (requires admin on Win7); 2121 needs no admin.
port = 2121
; Bind address. 0.0.0.0 = all interfaces (recommended).
bind = 0.0.0.0
; Passive-mode port range (must also be open in the firewall).
passive_ports_min = 50000
passive_ports_max = 50050

[storage]
; Where uploaded files land. The folder is created if missing.
drop_folder = C:\\iLENIA\\Cn\\Troptim\\PLV

[user]
; Credentials the IT app must present to upload.
username = millsaw
password = changeme

[security]
; Comma-separated list of source IPs allowed to connect. Empty = allow any.
; Example: allowed_ips = 192.0.2.50,192.0.2.51
allowed_ips =

[logging]
max_size_kb = 1024
backups = 3
"""


def ensure_config() -> configparser.ConfigParser:
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write(DEFAULT_CONFIG)
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH, encoding="utf-8")
    return cfg


def setup_logging(max_kb: int, backups: int) -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    if max_kb > 0:
        h = logging.handlers.RotatingFileHandler(
            LOG_PATH, maxBytes=max_kb * 1024, backupCount=backups,
            encoding="utf-8",
        )
        h.setFormatter(fmt)
        root.addHandler(h)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)
    # pyftpdlib uses its own logger; route into ours
    logging.getLogger("pyftpdlib").setLevel(logging.INFO)


class WhitelistHandler(FTPHandler):
    """FTPHandler that drops connections whose source IP is not whitelisted."""
    allowed_ips: set = set()  # populated from config at startup

    def on_connect(self):
        if self.allowed_ips and self.remote_ip not in self.allowed_ips:
            logging.warning(
                "REJECT %s - not in allowed_ips", self.remote_ip
            )
            self.respond("530 Source IP not authorized.")
            self.close_when_done()
            return
        super().on_connect()

    def on_file_received(self, file_path):
        size = 0
        try:
            size = os.path.getsize(file_path)
        except OSError:
            pass
        logging.info(
            "RECV %s -> %s (%d bytes)",
            self.remote_ip, os.path.basename(file_path), size
        )


def main() -> int:
    cfg = ensure_config()

    bind = cfg.get("server", "bind", fallback="0.0.0.0").strip()
    port = cfg.getint("server", "port", fallback=2121)
    pmin = cfg.getint("server", "passive_ports_min", fallback=50000)
    pmax = cfg.getint("server", "passive_ports_max", fallback=50050)

    drop = cfg.get(
        "storage", "drop_folder",
        fallback=r"C:\iLENIA\Cn\Troptim\PLV",
    ).strip()
    username = cfg.get("user", "username", fallback="millsaw").strip()
    password = cfg.get("user", "password", fallback="changeme")
    raw_allowed = cfg.get("security", "allowed_ips", fallback="").strip()
    allowed = {ip.strip() for ip in raw_allowed.split(",") if ip.strip()}
    log_max = cfg.getint("logging", "max_size_kb", fallback=1024)
    backups = cfg.getint("logging", "backups", fallback=3)

    setup_logging(log_max, backups)

    # Refuse to run with the placeholder password written by the installer.
    if not password or password.strip().lower() == "changeme":
        logging.error("Set your own password in %s ([user] password) before starting.", CONFIG_PATH)
        return 3

    try:
        os.makedirs(drop, exist_ok=True)
    except OSError as e:
        logging.error("Cannot create drop folder %s: %s", drop, e)
        return 2

    # Authorizer: a single user with write access to the drop folder only.
    # 'elradfmw' = list+download+upload+rename+delete+make/remove dirs.
    # For pure upload we'd narrow this; keeping it broad makes manual
    # cleanup with WinSCP/FileZilla easier.
    authorizer = DummyAuthorizer()
    authorizer.add_user(username, password, drop, perm="elradfmw")

    handler = WhitelistHandler
    handler.authorizer = authorizer
    handler.banner = "Mill Saw PLV FTP server ready."
    handler.passive_ports = range(pmin, pmax + 1)
    handler.allowed_ips = allowed

    addr = (bind, port)
    server = FTPServer(addr, handler)
    # Reasonable concurrency caps for one saw PC.
    server.max_cons = 16
    server.max_cons_per_ip = 4

    logging.info("=" * 56)
    logging.info("Mill Saw FTP server starting")
    logging.info("  bind         : %s:%s", bind, port)
    logging.info("  drop folder  : %s", drop)
    logging.info("  user         : %s", username)
    logging.info("  passive port : %d-%d", pmin, pmax)
    logging.info("  allowed IPs  : %s", allowed if allowed else "(any)")
    logging.info("  config file  : %s", CONFIG_PATH)
    logging.info("=" * 56)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Stopped by user.")
    finally:
        server.close_all()
    return 0


if __name__ == "__main__":
    sys.exit(main())
