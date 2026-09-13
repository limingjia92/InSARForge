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


def test_import_boundaries_and_product_forward_reference():
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
    code = "import sys; from insarforge.contracts import plugins; assert 'insarforge.products.models' not in sys.modules; assert not {'numpy','pydantic','yaml','h5py','osgeo','earthaccess'} & set(sys.modules)"
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
