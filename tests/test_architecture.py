"""Cleanup audit: enforce library/CLI separation and independent statistical imports."""

import ast
import subprocess
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "python/perpcarry"


def test_library_modules_do_not_import_command_line_tools():
    violations = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if "tools" in path.relative_to(PACKAGE).parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imports = [node.module or ""]
                imports += [f"{node.module}.{alias.name}" for alias in node.names]
            else:
                continue
            if any(
                name == "perpcarry.tools" or name.startswith("perpcarry.tools.") for name in imports
            ):
                violations.append(f"{path.relative_to(PACKAGE)}:{node.lineno}")
    assert not violations, "Library depends on CLI tools: " + ", ".join(violations)


def test_statistical_models_import_without_compiled_replay():
    script = """
import sys
class NoCompiledReplay:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "perpcarry_cpp":
            raise ModuleNotFoundError("compiled replay unavailable")
sys.meta_path.insert(0, NoCompiledReplay())
from perpcarry.models import impact_model, impact_model_io
from perpcarry.models import funding_model, funding_walk_forward, rolling_funding
from perpcarry.strategy import carry, costs, funding, sizing
law = impact_model.FittedLaw("square_root", 40.0, 0.5)
assert law.predict([0.01])[0] == 4.0
assert impact_model_io.SCHEMA_VERSION == 1
assert funding_model.Prior().shape == 3
assert rolling_funding.RollingFundingModel().rolling_days == 90
assert funding_walk_forward.Config().horizons == (3, 21)
assert carry.Policy(3, .8, .5).allow_synthetic_costs is False
assert callable(costs.from_artifact)
assert callable(funding.from_model)
assert callable(sizing.size_position)
assert "perpcarry_cpp" not in sys.modules
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
