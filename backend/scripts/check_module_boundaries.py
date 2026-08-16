from __future__ import annotations

import ast
import re
from pathlib import Path


SYSTEM = "english"
KNOWN_SYSTEMS = {"math", "cs408", "english"}
FORBIDDEN_SYSTEMS = KNOWN_SYSTEMS - {SYSTEM}
BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
APP_ROOT = BACKEND_ROOT / "app"
SCRIPT_ROOT = BACKEND_ROOT / "scripts"
FRONTEND_ROOT = REPO_ROOT / "frontend" / "src"
WRITE_METHODS = {"post", "put", "patch", "delete"}
SYMLINK_SCAN_IGNORES = {".git", ".venv", "node_modules", "dist", "__pycache__"}
JS_IMPORT_RE = re.compile(r"(?:\bfrom\s*|\bimport\s*\(\s*|\bimport\s*)['\"]([^'\"]+)['\"]")


def _python_module(path: Path) -> str:
    relative = path.relative_to(BACKEND_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _python_imports(path: Path) -> list[tuple[int, str]]:
    module = _python_module(path)
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    result: list[tuple[int, str]] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported = node.module or ""
            if node.level:
                parts = package.split(".") if package else []
                keep = max(0, len(parts) - node.level + 1)
                imported = ".".join([*parts[:keep], *([imported] if imported else [])])
            result.append((node.lineno, imported))
    return result


def _has_dependency_default(function: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> bool:
    defaults = [*function.args.defaults, *(item for item in function.args.kw_defaults if item is not None)]
    for default in defaults:
        for node in ast.walk(default):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id != "Depends" or not node.args:
                continue
            target = node.args[0]
            if isinstance(target, ast.Name) and target.id == name:
                return True
            if isinstance(target, ast.Attribute) and target.attr == name:
                return True
    return False


def check_layout() -> list[str]:
    errors: list[str] = []
    required = (
        APP_ROOT / SYSTEM,
        SCRIPT_ROOT / SYSTEM,
        FRONTEND_ROOT / SYSTEM,
        APP_ROOT / "platform",
        FRONTEND_ROOT / "platform",
        APP_ROOT / "main.py",
        FRONTEND_ROOT / "StudyApp.vue",
    )
    for path in required:
        if not path.exists():
            errors.append(f"missing required path: {path.relative_to(REPO_ROOT)}")
    for sibling in FORBIDDEN_SYSTEMS:
        for root in (APP_ROOT, SCRIPT_ROOT, FRONTEND_ROOT):
            path = root / sibling
            if path.exists():
                errors.append(f"sibling system directory exists: {path.relative_to(REPO_ROOT)}")
    for path in REPO_ROOT.rglob("*"):
        relative = path.relative_to(REPO_ROOT)
        if any(part in SYMLINK_SCAN_IGNORES for part in relative.parts):
            continue
        if path.is_symlink():
            errors.append(f"symlink is forbidden: {relative}")
    return errors


def check_backend() -> list[str]:
    errors: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")) + sorted(SCRIPT_ROOT.rglob("*.py")):
        for line, imported in _python_imports(path):
            for sibling in FORBIDDEN_SYSTEMS:
                if imported in {f"app.{sibling}", f"scripts.{sibling}"} or imported.startswith(
                    (f"app.{sibling}.", f"scripts.{sibling}.")
                ):
                    errors.append(
                        f"{path.relative_to(REPO_ROOT)}:{line}: imports sibling namespace {imported}"
                    )
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            write_routes = [
                decorator
                for decorator in node.decorator_list
                if isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr in WRITE_METHODS
            ]
            if write_routes and not _has_dependency_default(node, "verify_write_origin"):
                errors.append(
                    f"{path.relative_to(REPO_ROOT)}:{node.lineno}: write endpoint lacks verify_write_origin"
                )
    return errors


def check_frontend() -> list[str]:
    errors: list[str] = []
    for path in [*sorted(FRONTEND_ROOT.rglob("*.js")), *sorted(FRONTEND_ROOT.rglob("*.vue"))]:
        text = path.read_text(encoding="utf-8")
        for match in JS_IMPORT_RE.finditer(text):
            specifier = match.group(1).replace("\\", "/")
            line = text.count("\n", 0, match.start()) + 1
            for sibling in FORBIDDEN_SYSTEMS:
                if re.search(rf"(^|/)({re.escape(sibling)})(/|$)", specifier):
                    errors.append(
                        f"{path.relative_to(REPO_ROOT)}:{line}: imports sibling frontend {specifier}"
                    )
        for sibling in FORBIDDEN_SYSTEMS:
            if f"/api/{sibling}" in text:
                errors.append(
                    f"{path.relative_to(REPO_ROOT)}: embeds sibling endpoint /api/{sibling}"
                )
    return errors


def check_absolute_dependencies() -> list[str]:
    errors: list[str] = []
    forbidden_roots = {
        "/root/pro-study-platform/",
        *(f"/root/{name}/" for name in FORBIDDEN_SYSTEMS),
        *(f"/root/pro-study-platform-{name}/" for name in KNOWN_SYSTEMS),
    }
    scan_roots = [REPO_ROOT / name for name in ("backend", "frontend", "scripts")]
    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.name == "check_module_boundaries.py":
                continue
            if any(part in {".venv", "node_modules", "dist", "__pycache__", "data"} for part in path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for forbidden in forbidden_roots:
                if forbidden in text:
                    errors.append(
                        f"{path.relative_to(REPO_ROOT)}: absolute dependency on {forbidden}"
                    )
    return errors


def main() -> int:
    errors = [
        *check_layout(),
        *check_backend(),
        *check_frontend(),
        *check_absolute_dependencies(),
    ]
    if errors:
        print(f"{SYSTEM} boundary check failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"{SYSTEM} is a standalone system: no sibling directories, imports, endpoints, or symlinks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
