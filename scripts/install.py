#!/usr/bin/env python3
"""Install decode-economic-news and verify its required a-stock-data skill."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = SKILL_ROOT / "skill-dependencies.json"
EXCLUDED_NAMES = {
    ".backups",
    ".cache",
    ".DS_Store",
    ".env",
    "__pycache__",
    "work",
}
EXCLUDED_SUFFIXES = (".pyc", ".secret", ".secrets")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"missing YAML frontmatter: {path}")
    try:
        block = text.split("---\n", 2)[1]
    except IndexError as exc:
        raise ValueError(f"invalid YAML frontmatter: {path}") from exc
    result: dict[str, str] = {}
    for raw in block.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#") or ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        value = value.strip().strip('"').strip("'")
        result[key.strip()] = value
    return result


def version_tuple(value: str) -> tuple[int, ...] | None:
    pieces = value.strip().lstrip("vV").split(".")
    if not pieces or any(not piece.isdigit() for piece in pieces):
        return None
    return tuple(int(piece) for piece in pieces)


def version_at_least(actual: str, minimum: str) -> bool | None:
    left = version_tuple(actual)
    right = version_tuple(minimum)
    if left is None or right is None:
        return None
    size = max(len(left), len(right))
    return left + (0,) * (size - len(left)) >= right + (0,) * (size - len(right))


def validate_skill(path: Path, expected_name: str, minimum_version: str = "") -> dict[str, Any]:
    skill_md = path if path.is_file() else path / "SKILL.md"
    if not skill_md.is_file():
        raise ValueError(f"SKILL.md not found: {skill_md}")
    frontmatter = parse_frontmatter(skill_md)
    actual_name = frontmatter.get("name", "")
    if actual_name != expected_name:
        raise ValueError(f"expected skill {expected_name!r}, found {actual_name!r} in {skill_md}")
    actual_version = frontmatter.get("version", "")
    version_ok = version_at_least(actual_version, minimum_version) if minimum_version else True
    if version_ok is False:
        raise ValueError(
            f"{expected_name} {actual_version} is older than required {minimum_version}"
        )
    return {
        "name": actual_name,
        "version": actual_version or None,
        "minimum_version": minimum_version or None,
        "version_status": "ok" if version_ok is True else "unversioned",
        "skill_md": str(skill_md.resolve()),
        "sha256": hashlib.sha256(skill_md.read_bytes()).hexdigest(),
    }


def ignored_names(_: str, names: list[str]) -> set[str]:
    ignored = set()
    for name in names:
        if name in EXCLUDED_NAMES or name.startswith(".env.") or name.endswith(EXCLUDED_SUFFIXES):
            ignored.add(name)
    return ignored


def same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def install_skill_tree(
    source: Path, target: Path, *, dry_run: bool = False
) -> dict[str, Any]:
    source = source.resolve()
    if source.is_file():
        source_root = source.parent
    else:
        source_root = source
    if same_path(source_root, target):
        return {"action": "already_installed", "target": str(target), "backup": None}
    if dry_run:
        return {
            "action": "would_install",
            "source": str(source_root),
            "target": str(target),
            "backup": str(target.parent / ".backups" / target.name / "<timestamp>") if target.exists() else None,
        }

    target.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=f".{target.name}-stage-", dir=target.parent))
    staged = staging_root / target.name
    backup: Path | None = None
    try:
        if source.is_file():
            staged.mkdir()
            shutil.copy2(source, staged / "SKILL.md")
        else:
            shutil.copytree(source_root, staged, ignore=ignored_names)
        validate_skill(staged, target.name)
        if target.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_root = target.parent / ".backups" / target.name
            backup_root.mkdir(parents=True, exist_ok=True)
            backup = backup_root / stamp
            counter = 1
            while backup.exists():
                backup = backup_root / f"{stamp}-{counter}"
                counter += 1
            target.rename(backup)
        try:
            staged.rename(target)
        except Exception:
            if backup and backup.exists() and not target.exists():
                backup.rename(target)
            raise
        return {
            "action": "installed",
            "source": str(source_root),
            "target": str(target),
            "backup": str(backup) if backup else None,
        }
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def fetch_skill(url: str, destination: Path) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "decode-economic-news-installer/1.0", "Accept": "text/plain"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        content = response.read(2_000_000)
    if len(content) < 256 or not content.startswith(b"---"):
        raise RuntimeError("downloaded a-stock-data SKILL.md is empty or malformed")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return {"url": url, "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}


def dependency_spec(manifest: dict[str, Any]) -> dict[str, Any]:
    for item in manifest.get("required_skills") or []:
        if item.get("name") == "a-stock-data":
            return dict(item)
    raise ValueError("skill-dependencies.json must declare required skill a-stock-data")


def resolve_dependency_source(
    source_root: Path, explicit: Path | None
) -> Path | None:
    if explicit:
        return explicit.expanduser().resolve()
    sibling = source_root.parent / "a-stock-data"
    if (sibling / "SKILL.md").is_file():
        return sibling.resolve()
    return None


def package_status(packages: list[str]) -> dict[str, Any]:
    modules = [package.split(">=", 1)[0].split("==", 1)[0].replace("-", "_") for package in packages]
    installed = [module for module in modules if importlib.util.find_spec(module) is not None]
    missing = [package for package, module in zip(packages, modules) if module not in installed]
    return {"required_for_full_a_share_features": packages, "installed_modules": installed, "missing": missing}


def install_python_packages(packages: list[str]) -> None:
    subprocess.run([sys.executable, "-m", "pip", "install", *packages], check=True)


def install(
    *,
    codex_home: Path,
    dependency_source: Path | None = None,
    fetch_dependency: bool = False,
    install_python_deps: bool = False,
    skip_python_package_check: bool = False,
    dry_run: bool = False,
    source_root: Path = SKILL_ROOT,
    manifest_path: Path = MANIFEST_PATH,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    minimum_python = tuple(int(item) for item in str(manifest["python"]["minimum_version"]).split("."))
    if sys.version_info[: len(minimum_python)] < minimum_python:
        raise RuntimeError(f"Python {manifest['python']['minimum_version']} or newer is required")

    skills_dir = codex_home.expanduser().resolve() / "skills"
    dep = dependency_spec(manifest)
    dep_target = skills_dir / dep["name"]
    explicit_source = resolve_dependency_source(source_root, dependency_source)
    dependency_install: dict[str, Any]
    download_record: dict[str, Any] | None = None

    if explicit_source:
        validate_skill(explicit_source, dep["name"], dep.get("minimum_version", ""))
        dependency_install = install_skill_tree(explicit_source, dep_target, dry_run=dry_run)
    elif dep_target.is_dir():
        dependency_install = {"action": "verified_existing", "target": str(dep_target), "backup": None}
    elif fetch_dependency:
        if dry_run:
            dependency_install = {
                "action": "would_fetch_and_install",
                "url": dep["raw_skill_url"],
                "target": str(dep_target),
                "backup": None,
            }
        else:
            with tempfile.TemporaryDirectory(prefix="a-stock-data-download-") as temp:
                downloaded = Path(temp) / "a-stock-data" / "SKILL.md"
                download_record = fetch_skill(dep["raw_skill_url"], downloaded)
                validate_skill(downloaded, dep["name"], dep.get("minimum_version", ""))
                dependency_install = install_skill_tree(downloaded, dep_target)
    else:
        raise RuntimeError(
            "required skill a-stock-data is not installed. Provide --a-stock-data-source PATH "
            "or explicitly allow the reviewed upstream download with --fetch-a-stock-data"
        )

    if not dry_run and dep_target.exists():
        dependency_validation = validate_skill(dep_target, dep["name"], dep.get("minimum_version", ""))
    else:
        source_for_validation = explicit_source or dep_target
        dependency_validation = (
            validate_skill(source_for_validation, dep["name"], dep.get("minimum_version", ""))
            if source_for_validation.exists()
            else {"name": dep["name"], "minimum_version": dep.get("minimum_version"), "version_status": "pending"}
        )

    current_validation = validate_skill(source_root, manifest["skill"])
    current_install = install_skill_tree(source_root, skills_dir / manifest["skill"], dry_run=dry_run)

    packages = list(manifest["python"].get("a_stock_data_packages") or [])
    before = package_status(packages)
    if install_python_deps and before["missing"] and not dry_run:
        install_python_packages(before["missing"])
    after = package_status(packages) if not skip_python_package_check else {"check": "skipped"}
    warnings = []
    if not skip_python_package_check and after.get("missing"):
        warnings.append(
            "Full a-stock-data adapters need additional Python packages. Re-run with --install-python-deps "
            "or install the missing packages in the interpreter used by Codex."
        )
    if download_record:
        warnings.append(
            "a-stock-data was fetched from a mutable upstream branch; review the recorded SHA-256 before redistribution."
        )
    return {
        "schema": "skill.install-report/1",
        "created_at": utc_now(),
        "status": "dry_run" if dry_run else ("installed_with_warnings" if warnings else "installed"),
        "codex_home": str(codex_home.expanduser().resolve()),
        "skill": {"validation": current_validation, "installation": current_install},
        "dependency": {
            "required": True,
            "specification": dep,
            "validation": dependency_validation,
            "installation": dependency_install,
            "download": download_record,
        },
        "python_packages": after,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--codex-home",
        type=Path,
        default=Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex"),
        help="Codex home directory; defaults to CODEX_HOME or ~/.codex",
    )
    parser.add_argument(
        "--a-stock-data-source",
        type=Path,
        help="local a-stock-data directory or SKILL.md; preferred for reproducible/offline installs",
    )
    parser.add_argument(
        "--fetch-a-stock-data",
        action="store_true",
        help="explicitly fetch a-stock-data SKILL.md from the reviewed upstream URL",
    )
    parser.add_argument(
        "--install-python-deps",
        action="store_true",
        help="install missing a-stock-data Python packages into the current interpreter",
    )
    parser.add_argument(
        "--skip-python-package-check",
        action="store_true",
        help="skip checking optional Python packages used by full a-stock-data adapters",
    )
    parser.add_argument("--dry-run", action="store_true", help="validate and show actions without writing")
    parser.add_argument("--report", type=Path, help="also write the JSON installation report to this path")
    args = parser.parse_args()
    if args.a_stock_data_source and args.fetch_a_stock_data:
        parser.error("choose --a-stock-data-source or --fetch-a-stock-data, not both")
    try:
        result = install(
            codex_home=args.codex_home,
            dependency_source=args.a_stock_data_source,
            fetch_dependency=args.fetch_a_stock_data,
            install_python_deps=args.install_python_deps,
            skip_python_package_check=args.skip_python_package_check,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"installation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
