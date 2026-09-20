import ast
import subprocess
import sys
from pathlib import Path

PRODUCTION = [
    Path("src/insarforge/contracts/__init__.py"),
    Path("src/insarforge/contracts/errors.py"),
    Path("src/insarforge/contracts/values.py"),
    Path("src/insarforge/contracts/identity.py"),
    Path("src/insarforge/contracts/context.py"),
    Path("src/insarforge/contracts/records.py"),
    Path("src/insarforge/contracts/plugins.py"),
    Path("src/insarforge/products/semantics.py"),
]
FORBIDDEN = (
    "insarforge.config",
    "pydantic",
    "yaml",
    "numpy",
    "h5py",
    "osgeo",
    "earthaccess",
    "insarforge.missions",
    "insarforge.providers",
    "insarforge.processors",
    "insarforge.corrections",
    "insarforge.analyzers",
    "insarforge.qc",
)


def test_import_boundaries_and_lightweight_product_dependency():
    for path in PRODUCTION:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert not any(name.startswith(FORBIDDEN) for name in names), path
    code = "import sys; from insarforge.contracts import plugins; assert 'insarforge.products.models' in sys.modules; assert 'insarforge.contracts.operations' not in sys.modules; assert not {'numpy','pydantic','yaml','h5py','osgeo','earthaccess'} & set(sys.modules)"
    subprocess.run([sys.executable, "-c", code], check=True)


def test_lightweight_contract_package_and_protocol_invariants():
    init = Path("src/insarforge/contracts/__init__.py").read_text()
    assert "from ." not in init
    tree = ast.parse(Path("src/insarforge/contracts/plugins.py").read_text())
    protocols = [
        n
        for n in tree.body
        if isinstance(n, ast.ClassDef)
        and any(getattr(b, "id", None) == "Protocol" for b in n.bases)
    ]
    assert {n.name for n in protocols} == {
        "Mission",
        "Provider",
        "Processor",
        "Correction",
        "Analyzer",
        "QC",
    }
    assert all(
        not any(isinstance(x, ast.Name) and x.id == "ABC" for x in n.bases)
        for n in protocols
    )
    assert all(
        not any(isinstance(x, ast.FunctionDef) and x.name == "run" for x in n.body)
        for n in protocols
    )


def test_persistence_guard_imports_without_config_or_heavy_dependencies():
    code = """
import importlib.abc
import sys

class BlockHeavy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("insarforge.config", "pydantic", "yaml", "numpy", "h5py")):
            raise AssertionError("forbidden dependency: " + fullname)

sys.meta_path.insert(0, BlockHeavy())
from insarforge.contracts import _persistence
from insarforge.products import serialization, directory_manifest_serialization
assert not any(name.startswith("insarforge.config") for name in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", code], check=True, capture_output=True, text=True
    )
    assert result.stdout == result.stderr == ""


def _module_imports(path):
    """Normalize relative imports and imported submodule candidates."""
    from importlib.util import resolve_name

    module = ".".join(path.with_suffix("").parts[1:])
    package = module.rsplit(".", 1)[0]
    names = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                base = resolve_name("." * node.level + base, package)
            names.add(base)
            names.update(base + "." + alias.name for alias in node.names)
    return names


def test_planning_module_dependency_direction():
    base = Path("src/insarforge")
    lower = {
        "contracts/execution.py": (
            "insarforge.contracts._execution_json",
            "insarforge.contracts.context",
            "insarforge.contracts.errors",
            "insarforge.contracts.identity",
            "insarforge.contracts.values",
        ),
        "contracts/_execution_json.py": (
            "insarforge.contracts._persistence",
            "insarforge.contracts.errors",
            "insarforge.contracts.values",
        ),
        "core/planning.py": (
            "insarforge.contracts",
            "insarforge.core.registry",
            "insarforge.products.validation",
        ),
    }
    for relative, allowed in lower.items():
        names = _module_imports(base / relative)
        assert not any(name.startswith(FORBIDDEN) for name in names)
        project = {name for name in names if name.startswith("insarforge")}
        assert all(
            any(name == prefix or name.startswith(prefix + ".") for prefix in allowed)
            for name in project
        ), (relative, project)
    for path in (base / "contracts").glob("*.py"):
        names = _module_imports(path)
        assert not any(
            name.startswith("insarforge.core")
            and not name.startswith("insarforge.core.exceptions")
            for name in names
        ), path
        if path.name not in {"execution.py", "operations.py", "__init__.py"}:
            assert not any(
                name.startswith("insarforge.contracts.execution") for name in names
            ), path
    for path in (base / "products").glob("*.py"):
        assert not any(
            name.startswith(
                ("insarforge.contracts.execution", "insarforge.core.planning")
            )
            for name in _module_imports(path)
        ), path


def test_planning_isolated_imports_and_resolvable_annotations():
    code = """
import importlib.abc
import inspect
import sys
import typing

class BlockRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("insarforge.config", "pydantic", "yaml", "numpy",
                                "h5py", "osgeo", "earthaccess", "insarforge.missions",
                                "insarforge.providers", "insarforge.processors",
                                "insarforge.corrections", "insarforge.analyzers",
                                "insarforge.qc")):
            raise AssertionError(fullname)

sys.meta_path.insert(0, BlockRuntime())
from insarforge.contracts import execution
assert "insarforge.contracts.operations" not in sys.modules
assert "insarforge.products.models" not in sys.modules
assert "insarforge.core.registry" not in sys.modules
from insarforge.core import planning
for module in (execution, planning):
    for name, member in vars(module).items():
        if getattr(member, "__module__", None) == module.__name__:
            if inspect.isfunction(member) or inspect.isclass(member):
                typing.get_type_hints(member)
            if inspect.isclass(member):
                for method in vars(member).values():
                    if isinstance(method, classmethod):
                        method = method.__func__
                    if inspect.isfunction(method):
                        typing.get_type_hints(method)
"""
    subprocess.run([sys.executable, "-B", "-I", "-c", code], check=True)


def test_planning_has_no_concrete_plugin_dispatch():
    tree = ast.parse(Path("src/insarforge/core/planning.py").read_text())
    concrete = {
        "sentinel1",
        "sentinel-1",
        "isce2",
        "isce3",
        "gamma",
        "stamps",
        "mintpy",
    }
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.Match, ast.Compare, ast.Dict)):
            strings = {
                part.value.lower()
                for part in ast.walk(node)
                if isinstance(part, ast.Constant) and isinstance(part.value, str)
            }
            assert not strings & concrete
