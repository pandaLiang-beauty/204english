from __future__ import annotations

import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.english.reliability_check import run_checks as run_system_checks  # noqa: E402
from scripts.platform.reliability_check import run_checks as run_platform_checks  # noqa: E402


def main() -> int:
    run_platform_checks()
    run_system_checks()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
