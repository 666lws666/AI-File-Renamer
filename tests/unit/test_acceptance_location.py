"""Acceptance must test its own checkout, not a hard-coded primary checkout."""
import ast
from pathlib import Path


def test_acceptance_project_root_follows_script_location(tmp_path):
    script = Path(__file__).resolve().parents[2] / "acceptance_test.py"
    tree = ast.parse(script.read_text(encoding="utf-8"))
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "PROJECT_ROOT"
                              for target in node.targets))
    isolated_script = tmp_path / "isolated-checkout" / "acceptance_test.py"
    namespace = {"Path": Path, "__file__": str(isolated_script)}
    # Evaluate the actual root expression without running unrelated acceptance I/O.
    module = ast.Module(body=[assignment], type_ignores=[])
    exec(compile(module, str(script), "exec"), namespace)
    assert namespace["PROJECT_ROOT"] == isolated_script.parent.resolve()
