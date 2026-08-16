from __future__ import annotations

import argparse
import ast
import re
from collections import defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = REPO_ROOT / "memory" / "evidence"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
ROUTE_FILES = (
    "backend/app/platform/api.py",
    "backend/app/english/api.py",
    "backend/app/main.py",
)
SCHEMA_FILES = (
    ("platform", "backend/app/platform/db.py"),
    ("english", "backend/app/english/schema.py"),
)
ENV_PATTERN = re.compile(r"\bSTUDY_[A-Z0-9_]+\b")


def _frontmatter(scope: str, sources: list[str]) -> str:
    lines = [
        "---",
        "memory_level: 3",
        f"scope: {scope}",
        "load_policy: generated-on-demand",
        "generated: true",
        "generator: backend/scripts/generate_memory_evidence.py",
        "sources:",
    ]
    lines.extend(f"  - {source}" for source in sources)
    lines.extend(["---", ""])
    return "\n".join(lines)


def _literal_string(node: ast.AST | None) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


def _router_prefix(tree: ast.Module) -> str:
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "router" for target in node.targets):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        for keyword in node.value.keywords:
            if keyword.arg == "prefix":
                return _literal_string(keyword.value)
    return ""


def _depends_on(function: ast.FunctionDef | ast.AsyncFunctionDef, dependency: str) -> bool:
    for node in ast.walk(function):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "Depends" or not node.args:
            continue
        target = node.args[0]
        if isinstance(target, ast.Name) and target.id == dependency:
            return True
        if isinstance(target, ast.Attribute) and target.attr == dependency:
            return True
    return False


def _is_rate_limited(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr == "limit"
        for decorator in function.decorator_list
    )


def _backend_routes() -> list[dict[str, str]]:
    routes: list[dict[str, str]] = []
    for relative in ROUTE_FILES:
        path = REPO_ROOT / relative
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        prefix = _router_prefix(tree)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                    continue
                method = decorator.func.attr.lower()
                if method not in HTTP_METHODS or not decorator.args:
                    continue
                route_path = _literal_string(decorator.args[0])
                if not route_path:
                    continue
                routes.append(
                    {
                        "method": method.upper(),
                        "path": f"{prefix}{route_path}",
                        "handler": node.name,
                        "auth": "yes" if _depends_on(node, "get_current_user") else "no",
                        "origin": "yes" if _depends_on(node, "verify_write_origin") else "no",
                        "rate": "yes" if _is_rate_limited(node) else "no",
                        "source": relative,
                    }
                )
    return sorted(routes, key=lambda item: (item["path"], item["method"], item["handler"]))


def _frontend_routes() -> list[tuple[str, str]]:
    path = REPO_ROOT / "frontend/src/english/navigation.js"
    text = path.read_text(encoding="utf-8")
    match = re.search(r"pathViews\s*:\s*\{(?P<body>.*?)\}\s*,\s*viewPaths", text, flags=re.S)
    if not match:
        return []
    return re.findall(r"['\"]([^'\"]+)['\"]\s*:\s*['\"]([^'\"]+)['\"]", match.group("body"))


def _render_api_map() -> str:
    sources = [*ROUTE_FILES, "frontend/src/english/navigation.js", "frontend/src/router.js"]
    lines = [
        _frontmatter("evidence.api-routes", sources),
        "# API And Route Evidence",
        "",
        "> Generated file. Run `cd backend && python3 scripts/generate_memory_evidence.py` after route changes.",
        "",
        "## Backend HTTP Routes",
        "",
        "`Auth` means the handler depends on `get_current_user`. `Origin` means it depends on `verify_write_origin`.",
        "",
        "| Method | Path | Handler | Auth | Origin | Rate limit | Source |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in _backend_routes():
        lines.append(
            f"| {item['method']} | `{item['path']}` | `{item['handler']}` | "
            f"{item['auth']} | {item['origin']} | {item['rate']} | `{item['source']}` |"
        )
    lines.extend(
        [
            "",
            "## Frontend Routes",
            "",
            "| Path | View state |",
            "| --- | --- |",
        ]
    )
    for route_path, view in _frontend_routes():
        lines.append(f"| `{route_path}` | `{view}` |")
    lines.append("")
    return "\n".join(lines)


def _string_constant(path: Path, name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        value = ast.literal_eval(node.value)
        return value if isinstance(value, str) else ""
    return ""


def _schema_tables(sql: str) -> list[tuple[str, list[str]]]:
    result: list[tuple[str, list[str]]] = []
    for match in re.finditer(
        r"CREATE TABLE IF NOT EXISTS\s+([A-Za-z_][A-Za-z0-9_]*)\s*\((.*?)\n\);",
        sql,
        flags=re.S | re.I,
    ):
        columns: list[str] = []
        for raw_line in match.group(2).splitlines():
            line = raw_line.strip().rstrip(",")
            if not line:
                continue
            first = line.split(None, 1)[0].strip('"`')
            if first.upper() in {"PRIMARY", "UNIQUE", "FOREIGN", "CONSTRAINT", "CHECK"}:
                continue
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", first):
                columns.append(first)
        result.append((match.group(1), columns))
    return result


def _schema_indexes(sql: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for match in re.finditer(
        r"CREATE\s+(?:UNIQUE\s+)?INDEX IF NOT EXISTS\s+([A-Za-z_][A-Za-z0-9_]*)\s+ON\s+([A-Za-z_][A-Za-z0-9_]*)",
        sql,
        flags=re.I,
    ):
        result[match.group(2)].append(match.group(1))
    return result


def _render_schema_map() -> str:
    sources = [relative for _, relative in SCHEMA_FILES]
    lines = [
        _frontmatter("evidence.schema", sources),
        "# Schema Evidence",
        "",
        "> Generated from the SQLite base schemas.",
        "",
        "| Owner | Table | Columns | Indexes |",
        "| --- | --- | --- | --- |",
    ]
    for owner, relative in SCHEMA_FILES:
        sql = _string_constant(REPO_ROOT / relative, "SCHEMA_SQL")
        indexes = _schema_indexes(sql)
        for table, columns in _schema_tables(sql):
            column_text = ", ".join(f"`{column}`" for column in columns)
            index_text = ", ".join(f"`{index}`" for index in indexes.get(table, [])) or "-"
            lines.append(f"| {owner} | `{table}` | {column_text} | {index_text} |")
    lines.append("")
    return "\n".join(lines)


def _config_scan_files() -> list[Path]:
    paths = [REPO_ROOT / ".env.example", *REPO_ROOT.glob("*.sh")]
    for root in (
        REPO_ROOT / "scripts",
        REPO_ROOT / "backend" / "app",
        REPO_ROOT / "backend" / "scripts",
        REPO_ROOT / "frontend" / "src",
    ):
        if root.exists():
            paths.extend(path for path in root.rglob("*") if path.suffix in {".py", ".js", ".vue", ".sh"})
    paths.append(REPO_ROOT / "frontend" / "vite.config.js")
    return sorted({path for path in paths if path.is_file()})


def _env_defaults() -> dict[str, str]:
    defaults: dict[str, str] = {}
    for line in (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if ENV_PATTERN.fullmatch(name.strip()):
            defaults[name.strip()] = value.strip()
    return defaults


def _render_config_map() -> str:
    files = _config_scan_files()
    occurrences: dict[str, set[str]] = defaultdict(set)
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        relative = path.relative_to(REPO_ROOT).as_posix()
        for name in ENV_PATTERN.findall(text):
            if name.endswith("_") or name.rsplit("_", 1)[-1] == "AI":
                continue
            occurrences[name].add(relative)
    defaults = _env_defaults()
    used_sources = sorted({relative for references in occurrences.values() for relative in references})
    lines = [
        _frontmatter("evidence.configuration", used_sources),
        "# Configuration Evidence",
        "",
        "> Generated by static scanning. Secret values are never read from `.env.local` and are never written here.",
        "",
        "| Variable | Example/default | Referenced by |",
        "| --- | --- | --- |",
    ]
    for name in sorted(occurrences):
        secret = name.endswith(("_API_KEY", "_PASSWORD", "_SECRET", "_ACCESS_TOKEN"))
        default = "`<secret>`" if secret else f"`{defaults.get(name) or '(empty / code default)'}`"
        refs = sorted(occurrences[name])
        visible = ", ".join(f"`{item}`" for item in refs[:5])
        if len(refs) > 5:
            visible += f" (+{len(refs) - 5})"
        lines.append(f"| `{name}` | {default} | {visible} |")
    lines.append("")
    return "\n".join(lines)


def build_documents() -> dict[Path, str]:
    return {
        EVIDENCE_ROOT / "api-map.md": _render_api_map(),
        EVIDENCE_ROOT / "schema-map.md": _render_schema_map(),
        EVIDENCE_ROOT / "config-map.md": _render_config_map(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate deterministic project-memory evidence from source code.")
    parser.add_argument("--check", action="store_true", help="Fail when generated evidence is missing or stale.")
    args = parser.parse_args()
    stale: list[str] = []
    for path, content in build_documents().items():
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                stale.append(path.relative_to(REPO_ROOT).as_posix())
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(path.relative_to(REPO_ROOT).as_posix())
    if stale:
        print("Generated memory evidence is stale:")
        for relative in stale:
            print(f"- {relative}")
        print("Run: cd backend && python3 scripts/generate_memory_evidence.py")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
