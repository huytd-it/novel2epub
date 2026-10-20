"""Optional deployment-wide metadata, without writing overrides into SQLite."""
from __future__ import annotations

import os
import shlex
from pathlib import Path


def publisher_override(base_dir: Path) -> str:
    """Process env wins; otherwise read .env beside the DB, then in the project.

    Only read the publisher setting; never import or expose other credentials.
    An empty value leaves existing database metadata unchanged.
    """
    key = "NOVEL2EPUB_PUBLISHER"
    if key in os.environ:
        return os.environ[key].strip()
    candidates = [base_dir / ".env", Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"]
    for path in dict.fromkeys(candidates):
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except (OSError, UnicodeError):
            continue
        for line in lines:
            name, separator, value = line.strip().removeprefix("export ").partition("=")
            if separator and name.strip() == key:
                try:
                    return " ".join(shlex.split(value, comments=True)).strip()
                except ValueError:
                    return ""
    return ""
