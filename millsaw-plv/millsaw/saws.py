"""
Saw-machine registry and FTP sender.

Stores known saw PCs in saws.json next to the application; uses stdlib
ftplib to upload PLV files to whichever FTP server runs on the saw side
(our mill_saw_ftp.py, FileZilla Server, etc.).
"""

from __future__ import annotations

import ftplib
import json
import socket
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Optional


SAWS_FILENAME = "saws.json"


@dataclass
class Saw:
    name: str
    host: str
    port: int = 2121
    username: str = "millsaw"
    password: str = ""
    remote_dir: str = "/"
    passive: bool = True
    timeout_sec: int = 30


@dataclass
class SawList:
    saws: List[Saw] = field(default_factory=list)

    def find(self, name):
        for s in self.saws:
            if s.name == name:
                return s
        return None


class SawRegistry:
    def __init__(self, base_dir):
        self.path = Path(base_dir) / SAWS_FILENAME

    def load(self):
        if not self.path.exists():
            return SawList()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return SawList()
        saws = []
        for raw in data.get("saws", []):
            try:
                saws.append(Saw(
                    name=str(raw.get("name", "")).strip() or "saw",
                    host=str(raw.get("host", "")).strip(),
                    port=int(raw.get("port", 2121)),
                    username=str(raw.get("username", "millsaw")),
                    password=str(raw.get("password", "")),
                    remote_dir=str(raw.get("remote_dir", "/")) or "/",
                    passive=bool(raw.get("passive", True)),
                    timeout_sec=int(raw.get("timeout_sec", 30)),
                ))
            except (TypeError, ValueError):
                continue
        return SawList(saws=saws)

    def save(self, saw_list):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"saws": [asdict(s) for s in saw_list.saws]}, indent=2),
            encoding="utf-8",
        )


class SendError(Exception):
    """Raised on any FTP transfer failure; message is user-facing."""


# Tuple of exception classes safe to catch in except clauses.
# Filtered to only proper BaseException subclasses to avoid TypeErrors
# on systems where pyOpenSSL or ssl integrate weirdly with ftplib.
_FTP_ERRORS = tuple(
    e for e in (
        ftplib.error_reply, ftplib.error_perm, ftplib.error_temp,
        ftplib.error_proto, OSError, EOFError, socket.gaierror,
    )
    if isinstance(e, type) and issubclass(e, BaseException)
)


def send_plv(saw, local_path, remote_filename=None, progress=None):
    """Upload a single .plv file via FTP. Returns the remote filename."""
    local = Path(local_path)
    if not local.exists():
        raise SendError(f"Local file not found: {local}")
    if not saw.host:
        raise SendError(f"Saw '{saw.name}' has no host configured.")
    fname = remote_filename or local.name
    total = local.stat().st_size
    sent = [0]

    try:
        ftp = ftplib.FTP()
        ftp.connect(saw.host, saw.port, timeout=saw.timeout_sec)
        ftp.login(saw.username, saw.password)
        ftp.set_pasv(saw.passive)

        target = (saw.remote_dir or "/").strip()
        if target and target not in ("/", ""):
            try:
                ftp.cwd(target)
            except ftplib.error_perm:
                _safe_makedirs(ftp, target)
                ftp.cwd(target)

        def _cb(data):
            sent[0] += len(data)
            if progress:
                try:
                    progress(sent[0], total)
                except Exception:
                    pass

        with local.open("rb") as f:
            ftp.storbinary("STOR " + fname, f, blocksize=65536, callback=_cb)
        ftp.quit()
        return fname
    except _FTP_ERRORS as e:
        raise SendError(f"FTP transfer failed: {e}") from e
    except Exception as e:
        raise SendError(f"Unexpected error: {type(e).__name__}: {e}") from e


def test_connection(saw):
    """Quick connectivity / auth test; raises SendError on any failure."""
    if not saw.host:
        raise SendError("No host configured.")
    try:
        ftp = ftplib.FTP()
        ftp.connect(saw.host, saw.port, timeout=saw.timeout_sec)
        ftp.login(saw.username, saw.password)
        ftp.set_pasv(saw.passive)
        target = (saw.remote_dir or "/").strip()
        if target and target not in ("/", ""):
            ftp.cwd(target)
        pwd = ftp.pwd()
        ftp.quit()
        return f"Connected. Remote dir = {pwd}"
    except _FTP_ERRORS as e:
        raise SendError(str(e)) from e
    except Exception as e:
        raise SendError(f"{type(e).__name__}: {e}") from e


def _safe_makedirs(ftp, path):
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    if path.startswith("/"):
        ftp.cwd("/")
    for p in parts:
        try:
            ftp.cwd(p)
        except ftplib.error_perm:
            try:
                ftp.mkd(p)
            except ftplib.error_perm:
                return
            try:
                ftp.cwd(p)
            except ftplib.error_perm:
                return
