#!/usr/bin/env python3
"""Local git operations for deploy-app. It never pushes: publishing is always done by the user.

Usage:  repo.py state <path>                          is it a repo, remote, branch, upstream, what would be pushed
        repo.py init <path>                           git init -b main plus a .gitignore (keeps an existing one)
        repo.py commit <path> -m MSG (--all | --files F [F ...])
                                                      scans for secrets first and refuses if it finds any
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from analyze import analyze, parent_apps_warning, project_files, repo_root, scan_secrets  # noqa: E402

GITIGNORE = """# Added by coolify-ops (deploy-app)
node_modules/
.venv/
venv/
__pycache__/
*.pyc
db.sqlite3
staticfiles/
media/
vendor/
.next/
.nuxt/
.output/
.angular/
.svelte-kit/
.astro/
.react-router/
.env
.env.*
!.env.example
.DS_Store
"""


class Error(Exception):
    pass


def git(path: Path, *args: str, check: bool = True) -> str:
    try:
        r = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True)
    except FileNotFoundError:
        raise Error("git is not installed") from None
    if check and r.returncode != 0:
        raise Error(f"git {args[0]} failed: {(r.stderr or r.stdout).strip()[:400]}")
    return r.stdout.strip()


def is_repo(path: Path) -> bool:
    return git(path, "rev-parse", "--is-inside-work-tree", check=False) == "true"


def cmd_state(a) -> dict:
    path = Path(a.path).expanduser().resolve()
    if not path.is_dir():
        raise Error(f"Folder {path} does not exist")
    if not is_repo(path):
        res = {"ok": True, "path": str(path), "is_repo": False, "has_gitignore": (path / ".gitignore").exists()}
        if warning := parent_apps_warning(path):  # the repository may have to be the parent folder
            res["parent_warning"] = warning
        return res
    remote = git(path, "remote", "get-url", "origin", check=False)
    remote = re.sub(r"//[^/@]+@", "//", remote)  # never print credentials stored in the URL
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", remote)
    has_upstream = bool(git(path, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", check=False))
    has_commits = bool(git(path, "rev-parse", "--verify", "-q", "HEAD", check=False))
    # No upstream (new repository): everything would be pushed
    rng = ["@{u}..HEAD"] if has_upstream else (["HEAD"] if has_commits else [])
    to_push = git(path, "log", "--oneline", *rng).splitlines() if rng else []
    status = git(path, "status", "--porcelain")
    top = repo_root(path)[0]
    return {"ok": True, "path": str(path), "is_repo": True, "root": str(top), "branch": git(path, "branch", "--show-current"),
            "remote": m.group(1) if m else (remote or None), "remote_is_github": bool(m),
            "has_upstream": has_upstream, "has_commits": has_commits,
            "to_push": to_push, "uncommitted": len(status.splitlines()) if status else 0,
            "has_gitignore": (path / ".gitignore").exists()}


def cmd_init(a) -> dict:
    path = Path(a.path).expanduser().resolve()
    if not path.is_dir():
        raise Error(f"Folder {path} does not exist")
    if is_repo(path):
        raise Error("Already a git repository")
    created, extra = False, []
    if not (path / ".gitignore").exists():
        extra = build_output(path)
        (path / ".gitignore").write_text(GITIGNORE + "".join(f"{d}\n" for d in extra))
        created = True
    git(path, "init", "-b", "main")
    return {"ok": True, "path": str(path), "branch": "main", "created_gitignore": created, "ignored_build_output": extra}


def build_output(path: Path) -> list[str]:
    """Top folder of the build output when the image builds it (a local build may hold inlined build-time values),
    for the project or, in a repository with several apps, for each app folder.

    Not for plain static sites (static-nginx copies the folder as is: a «build/» there may hold real files)."""
    r = analyze(path)
    monorepo = r.get("monorepo") or {}
    stacks = [(f"{a['path']}/", a) for a in monorepo.get("apps", [])] if monorepo.get("kind") == "apps" \
        else [("", r.get("stack") or {})]
    lines = []
    for prefix, stack in stacks:
        top = (stack.get("build_dir") or "").split("/")[0]
        if stack.get("template") in (None, "static-nginx") or not top or top in {".", ".."}:
            continue
        line = f"{prefix}{top}/"
        if line not in GITIGNORE.splitlines() and line not in lines:
            lines.append(line)
    return lines


def cmd_commit(a) -> dict:
    path = Path(a.path).expanduser().resolve()
    if not is_repo(path):
        raise Error("Not a git repository: run «repo.py init» first")
    # Same view as a push (tracked plus untracked-not-ignored files) of what will be staged: the whole repository with
    # --all (git add --all stages it even from an app folder), else the folder; plus anything already staged anywhere
    top, subdir = repo_root(path)
    path = top / subdir  # git's spelling of the path, so every file is relative to top
    files = set(project_files(top if a.all else path))
    files |= {top / f for f in git(top, "diff", "--cached", "--name-only").splitlines() if (top / f).is_file()}
    secrets = scan_secrets(top, sorted(files))
    if secrets:
        return {"ok": False, "error": "possible secrets in files that would be committed; nothing was committed",
                "secrets": secrets}
    if a.all:
        git(path, "add", "--all")
    else:
        missing = [f for f in a.files if not (path / f).exists()]
        if missing:
            raise Error(f"Files not found: {', '.join(missing)}")
        git(path, "add", "--", *a.files)
    if not git(path, "diff", "--cached", "--name-only"):
        return {"ok": True, "committed": False, "reason": "nothing to commit"}
    git(path, "commit", "-m", a.message)
    return {"ok": True, "committed": True, "commit": git(path, "rev-parse", "--short", "HEAD"),
            "files": len(git(path, "show", "--name-only", "--format=", "HEAD").splitlines())}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="repo.py", description="Local git operations for deploy-app (never pushes)")
    s = p.add_subparsers(dest="command", required=True)
    c = s.add_parser("state", help="repository state and what a push would publish"); c.add_argument("path")
    c.set_defaults(f=cmd_state)
    c = s.add_parser("init", help="git init -b main and a .gitignore if missing"); c.add_argument("path")
    c.set_defaults(f=cmd_init)
    c = s.add_parser("commit", help="commit after a secrets scan")
    c.add_argument("path"); c.add_argument("-m", "--message", required=True)
    g = c.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true", help="every file not ignored by .gitignore")
    g.add_argument("--files", nargs="+", help="only these files (relative to the project)")
    c.set_defaults(f=cmd_commit)
    return p


def main(argv=None) -> None:
    a = parser().parse_args(argv)
    try:
        res = a.f(a)
    except Error as e:
        res = {"ok": False, "error": str(e)}
    print(json.dumps(res, ensure_ascii=False))
    sys.exit(0 if res.get("ok") else 1)


if __name__ == "__main__":
    main()
