from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections import deque
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MEMORY_ROOT = REPO_ROOT / "memory"
ROOT_MEMORY = REPO_ROOT / "memory.md"
SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from generate_memory_evidence import build_documents  # noqa: E402


EXPECTED_LEVELS = {
    "maps": "1",
    "domains": "2",
    "decisions": "3",
    "evidence": "3",
}
LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _memory_documents() -> list[Path]:
    documents = [ROOT_MEMORY]
    if MEMORY_ROOT.exists():
        documents.extend(sorted(MEMORY_ROOT.rglob("*.md")))
    return documents


def _frontmatter(path: Path) -> tuple[dict[str, str | list[str]], list[str]]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return {}, [f"{path.relative_to(REPO_ROOT)}: missing frontmatter"]
    try:
        end = lines.index("---", 1)
    except ValueError:
        return {}, [f"{path.relative_to(REPO_ROOT)}: unterminated frontmatter"]
    result: dict[str, str | list[str]] = {}
    active_list = ""
    for line in lines[1:end]:
        if line.startswith("  - ") and active_list:
            value = line[4:].strip()
            current = result.setdefault(active_list, [])
            if isinstance(current, list):
                current.append(value)
            continue
        if ":" not in line:
            errors.append(f"{path.relative_to(REPO_ROOT)}: invalid frontmatter line: {line}")
            active_list = ""
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value:
            result[key] = value
            active_list = ""
        else:
            result[key] = []
            active_list = key
    return result, errors


def _inside_repo(path: Path) -> bool:
    try:
        path.relative_to(REPO_ROOT)
        return True
    except ValueError:
        return False


def _source_digest(sources: list[str]) -> tuple[str, list[str]]:
    digest = hashlib.sha256()
    errors: list[str] = []
    for relative in sorted(sources):
        path = (REPO_ROOT / relative).resolve()
        if not _inside_repo(path):
            errors.append(f"source escapes repository: {relative}")
            continue
        if not path.is_file():
            errors.append(f"source does not exist: {relative}")
            continue
        if path.is_symlink():
            errors.append(f"source is a symlink: {relative}")
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest(), errors


def _replace_fingerprint(path: Path, fingerprint: str) -> bool:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(
        r"(?m)^source_fingerprint:\s*.*$",
        f"source_fingerprint: {fingerprint}",
        text,
        count=1,
    )
    if count != 1:
        return False
    if updated != text:
        path.write_text(updated, encoding="utf-8")
    return True


def _local_markdown_links(path: Path) -> list[Path]:
    targets: list[Path] = []
    for raw_target in LINK_PATTERN.findall(path.read_text(encoding="utf-8")):
        target = raw_target.strip().strip("<>").split("#", 1)[0]
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        resolved = (path.parent / target).resolve()
        if resolved.suffix.lower() == ".md":
            targets.append(resolved)
    return targets


def _check_generated() -> list[str]:
    errors: list[str] = []
    for path, expected in build_documents().items():
        if not path.is_file():
            errors.append(f"missing generated evidence: {path.relative_to(REPO_ROOT)}")
        elif path.read_text(encoding="utf-8") != expected:
            errors.append(
                f"stale generated evidence: {path.relative_to(REPO_ROOT)} "
                "(run backend/scripts/generate_memory_evidence.py)"
            )
    return errors


def check_memory(*, refresh_fingerprints: bool = False) -> list[str]:
    errors: list[str] = []
    documents = _memory_documents()
    if not ROOT_MEMORY.is_file():
        return ["missing memory.md"]
    if len(documents) == 1:
        return ["memory/ contains no detail documents"]

    metadata_by_path: dict[Path, dict[str, str | list[str]]] = {}
    scopes: dict[str, Path] = {}
    for path in documents:
        metadata, parse_errors = _frontmatter(path)
        errors.extend(parse_errors)
        metadata_by_path[path] = metadata
        relative = path.relative_to(REPO_ROOT)
        expected_level = "0" if path == ROOT_MEMORY else EXPECTED_LEVELS.get(relative.parts[1], "")
        if not expected_level:
            errors.append(f"{relative}: document is outside a recognized memory level")
        elif str(metadata.get("memory_level") or "") != expected_level:
            errors.append(f"{relative}: expected memory_level {expected_level}")
        scope = str(metadata.get("scope") or "").strip()
        if not scope:
            errors.append(f"{relative}: missing scope")
        elif scope in scopes:
            errors.append(f"duplicate scope {scope}: {relative} and {scopes[scope].relative_to(REPO_ROOT)}")
        else:
            scopes[scope] = path

        sources = metadata.get("sources") or []
        generated = str(metadata.get("generated") or "").lower() == "true"
        if not isinstance(sources, list) or not sources:
            errors.append(f"{relative}: missing sources list")
            continue
        fingerprint, source_errors = _source_digest(sources)
        errors.extend(f"{relative}: {error}" for error in source_errors)
        if generated or source_errors:
            continue
        stored = str(metadata.get("source_fingerprint") or "")
        if refresh_fingerprints:
            if not _replace_fingerprint(path, fingerprint):
                errors.append(f"{relative}: missing source_fingerprint field")
        elif stored != fingerprint:
            errors.append(
                f"{relative}: source fingerprint is stale; review this memory document, then run "
                "`cd backend && python3 scripts/check_memory.py --refresh-fingerprints`"
            )

    document_set = {path.resolve() for path in documents}
    links: dict[Path, list[Path]] = {}
    for path in documents:
        relative = path.relative_to(REPO_ROOT)
        local_links = _local_markdown_links(path)
        links[path.resolve()] = local_links
        for target in local_links:
            if not _inside_repo(target):
                errors.append(f"{relative}: link escapes repository: {target}")
            elif not target.is_file():
                errors.append(f"{relative}: broken Markdown link: {target.relative_to(REPO_ROOT)}")

    reachable: set[Path] = set()
    queue = deque([ROOT_MEMORY.resolve()])
    while queue:
        current = queue.popleft()
        if current in reachable:
            continue
        reachable.add(current)
        for target in links.get(current, []):
            if target in document_set and target not in reachable:
                queue.append(target)
    for path in sorted(document_set - reachable):
        errors.append(f"unreachable memory document: {path.relative_to(REPO_ROOT)}")

    errors.extend(_check_generated())
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate progressive project memory.")
    parser.add_argument(
        "--refresh-fingerprints",
        action="store_true",
        help="Refresh source fingerprints after manually reviewing affected memory documents.",
    )
    args = parser.parse_args()
    errors = check_memory(refresh_fingerprints=args.refresh_fingerprints)
    if errors:
        print("Project memory check failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    action = "fingerprints refreshed and memory validated" if args.refresh_fingerprints else "memory validated"
    print(f"Project memory: {action}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
