"""Guardrail tests that encode SCOPE/ARCHITECTURE safety invariants.

These run today against the *target* package skeleton so the rules are enforced
from day one as real code is migrated in. They use static source inspection so
they pass before the modules contain logic.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "my_trade"


def _imports_in(pkg_dir: Path) -> set[str]:
    """Collect all imported module paths under a package directory."""
    found: set[str] = set()
    for py in pkg_dir.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module)
    return found


def test_target_package_exists() -> None:
    assert (SRC / "core").is_dir()
    assert (SRC / "research").is_dir()


def test_research_layer_never_imports_execution() -> None:
    """Claude (research) layer must never import the execution adapter.

    This is the core safety invariant: the non-deterministic layer cannot reach
    code that places/modifies orders.
    """
    research_dir = SRC / "research"
    if not research_dir.is_dir():
        return
    imports = _imports_in(research_dir)
    forbidden = {
        "my_trade.core.execution",
        "my_trade.core.risk",
    }
    leaked = {imp for imp in imports if any(imp.startswith(f) for f in forbidden)}
    assert not leaked, f"research/ illegally imports execution/risk: {leaked}"
