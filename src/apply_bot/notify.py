from __future__ import annotations

import shutil
import subprocess


def notify(title: str, message: str) -> None:
    print(f"[{title}] {message}")
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", title, message], check=False)
