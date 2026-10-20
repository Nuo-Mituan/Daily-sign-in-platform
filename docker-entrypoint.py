#!/usr/bin/env python3
"""Drop privileges after fixing bind-mount ownership for the app UID/GID."""

from __future__ import annotations

import os
import sys
from pathlib import Path

TARGET_UID = int(os.environ.get("PUID", "10001"))
TARGET_GID = int(os.environ.get("PGID", "10001"))
PRIVATE_DIRS = [
    Path(os.environ.get("DATA_DIR", "/app/data")),
    Path(os.environ.get("LOGS_DIR", "/app/logs")),
    Path(os.environ.get("MODULES_DIR", "/app/modules")),
    Path("/app/app/push_drivers/custom"),
]


def chown_tree(path: Path, uid: int, gid: int) -> None:
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
    for root, dirs, files in os.walk(path):
        os.chown(root, uid, gid)
        for name in dirs + files:
            os.chown(Path(root) / name, uid, gid)


def main() -> None:
    for directory in PRIVATE_DIRS:
        chown_tree(directory, TARGET_UID, TARGET_GID)
        try:
            directory.chmod(0o700)
        except OSError:
            pass
    os.umask(0o077)
    os.setgroups([])
    os.setgid(TARGET_GID)
    os.setuid(TARGET_UID)
    command = sys.argv[1:] or ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5000"]
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
