"""
Project-local vault — `scribe init` (idempotent, from ExoLab).

Running `scribe init` inside a project gives that project its own isolated
Scribe context: a `./config.toml` the config loader already prefers over the
global one (cwd is the first search path), plus project-local RAG and SME
stores under `./.scribe/`. Documents ingested here never mix with another
project's knowledge.

Idempotent by design: existing files are reported, never overwritten.
"""

from __future__ import annotations

from pathlib import Path

VAULT_DIR = ".scribe"

_CONFIG_TEMPLATE = """\
# Scribe project vault — created by `scribe init`.
# This file wins over ~/.config/scribe/config.toml whenever Scribe is
# started from this directory.

[scribe]
workspace_dir = "{workspace}"

["scribe.rag"]
index_dir = "{vault}/rag"

["scribe.sme"]
db_path = "{vault}/sme"
"""


def init_vault(project_dir: Path | str) -> dict:
    """
    Create the project vault. Returns a report dict:
    {created: [...], existing: [...], vault: path}.
    """
    root = Path(project_dir).resolve()
    vault = root / VAULT_DIR
    created: list[str] = []
    existing: list[str] = []

    for sub in (vault, vault / "rag", vault / "sme", vault / "sessions"):
        if sub.is_dir():
            existing.append(str(sub.relative_to(root)))
        else:
            sub.mkdir(parents=True)
            created.append(str(sub.relative_to(root)))

    config_file = root / "config.toml"
    if config_file.exists():
        existing.append("config.toml")
    else:
        config_file.write_text(
            _CONFIG_TEMPLATE.format(workspace=str(root), vault=f"{root}/{VAULT_DIR}"),
            encoding="utf-8",
        )
        created.append("config.toml")

    _ensure_gitignore(root, created, existing)
    return {"vault": str(vault), "created": created, "existing": existing}


def _ensure_gitignore(root: Path, created: list[str], existing: list[str]) -> None:
    """Keep the vault out of version control when the project is a repo."""
    if not (root / ".git").is_dir():
        return
    gitignore = root / ".gitignore"
    line = f"{VAULT_DIR}/"
    if gitignore.exists():
        if line in gitignore.read_text(encoding="utf-8").splitlines():
            existing.append(".gitignore entry")
            return
        with open(gitignore, "a", encoding="utf-8") as f:
            f.write(f"\n# Scribe project vault\n{line}\n")
    else:
        gitignore.write_text(f"# Scribe project vault\n{line}\n", encoding="utf-8")
    created.append(".gitignore entry")
