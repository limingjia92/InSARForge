"""P4.3-04 extension proof; Git-tree invariance is captured by delivery outside CI.

Only the public registry/binding/Runtime path selects either Analyzer. Existing
boundary suites remain unchanged. AST checks cover all production Python files.
"""

import ast
import hashlib
import importlib.util
import json
import subprocess
import sys
from dataclasses import dataclass, field, is_dataclass, replace
from pathlib import Path
from typing import get_type_hints

import pytest

from insarforge.contracts.context import ExecutionContext
from insarforge.contracts.execution import OutputRef, TaskState, WorkflowPlan
from insarforge.contracts.identity import PluginDescriptor, PluginKind
from insarforge.contracts.plugins import AnalysisRequest
from insarforge.core.registry import PluginRegistry
from insarforge.core.result_identity import record_semantic_material
from insarforge.core.runtime import Runtime
from insarforge.products.models import Product, ProductDraft
from insarforge.products.validation import validate_product_structure

from ._canonical_workflow import BUDGET, canonical_plan, reopen_workspace
from ._fake_operations import Factory, build_harness
from ._fake_plugins import (
    CallJournal,
    Controls,
    FakeAnalyzer,
    FakeConfig,
    business,
    draft,
    known,
)

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src"
PRODUCTION = SOURCE / "insarforge"
KINDS = {"MISSION", "PROVIDER", "PROCESSOR", "CORRECTION", "ANALYZER", "QC"}
FAMILIES = tuple(
    "insarforge." + name
    for name in (
        "missions",
        "providers",
        "processors",
        "corrections",
        "analyzers",
        "qc",
    )
)
V2_DESCRIPTOR = PluginDescriptor(
    PluginKind.ANALYZER, "synthetic:analyzer-v2", 1, "2", "Synthetic Analyzer V2", ()
)
MARKER = "synthetic:analyzer-v2"


@dataclass(frozen=True)
class FakeAnalyzerV2:
    config: FakeConfig
    journal: CallJournal
    descriptor: PluginDescriptor = field(default=V2_DESCRIPTOR, init=False)

    def analyze(
        self, request: AnalysisRequest, context: ExecutionContext
    ) -> tuple[ProductDraft, ...]:
        value = draft(self.config, "analyze", request.parameters)
        value = replace(
            value,
            semantic_metadata={
                **value.semantic_metadata,
                "synthetic:implementation": known(MARKER),
            },
        )
        return business(
            self.journal, "analyze", AnalysisRequest, request, context, (value,)
        )


def extension():
    """Copy registrations through public APIs, then add one Analyzer and seal."""
    harness = build_harness()
    registry = PluginRegistry(required_api_version=1)
    for registration in harness.registry.registrations():
        registry.register(
            registration.descriptor, registration.factory, registration.bindings
        )
    controls = Controls()
    original = harness.registration("analyze")
    binding = harness.registry.resolve_binding(original.ref, "synthetic:analyze", 1)
    implementation = {
        name: Path(__file__).with_name(name)
        for name in (
            "__init__.py",
            "_fake_plugins.py",
            "_fake_operations.py",
            Path(__file__).name,
        )
    }
    digest = hashlib.sha256()
    for name, path in sorted(implementation.items()):
        digest.update(name.encode() + b"\0" + path.read_bytes())
    v2_binding = replace(
        binding,
        handler=replace(
            binding.handler,
            plugin_type=FakeAnalyzerV2,
            controls=controls,
            wrapper_digest=digest.hexdigest(),
        ),
    )
    registry.register(
        V2_DESCRIPTOR, Factory(FakeAnalyzerV2, harness.config, controls), (v2_binding,)
    )
    registry.seal()
    return harness, registry, controls, implementation


def selected_plan(harness, ref):
    base = canonical_plan(harness)
    return WorkflowPlan(
        1,
        (
            base.task("search"),
            base.task("acquire"),
            replace(
                base.task("analyze"),
                plugin_ref=ref,
                inputs={"source": (OutputRef("acquire", "out"),)},
            ),
        ),
    )


def test_arch01_registration_resolves_same_operation_independently():
    harness, registry, controls, _ = extension()
    original = harness.registration("analyze")
    assert original.ref != V2_DESCRIPTOR.ref
    assert len(registry) == 7 and registry.is_sealed
    assert len(harness.registry) == 6 and harness.registry.is_sealed
    assert {r.ref.kind.name for r in registry.registrations()} == KINDS
    assert registry.resolve(original.ref).descriptor == original.descriptor
    assert registry.resolve(V2_DESCRIPTOR.ref).descriptor == V2_DESCRIPTOR
    old = registry.resolve_binding(original.ref, "synthetic:analyze", 1)
    new = registry.resolve_binding(V2_DESCRIPTOR.ref, "synthetic:analyze", 1)
    assert old is original.bindings[0] and new is not old
    assert replace(new, handler=old.handler) == old
    assert (
        old.handler.plugin_type is FakeAnalyzer
        and new.handler.plugin_type is FakeAnalyzerV2
    )
    assert not harness.controls.journal.snapshot() and not controls.journal.snapshot()
    assert FakeAnalyzerV2.__bases__ == FakeAnalyzer.__bases__ == (object,)
    assert not any(
        hasattr(cls, name)
        for cls in (FakeAnalyzer, FakeAnalyzerV2)
        for name in ("run", "execute")
    )
    assert get_type_hints(FakeAnalyzerV2.analyze) == get_type_hints(
        FakeAnalyzer.analyze
    )


def test_arch02_arch03_runtime_selection_and_deterministic_v2_product(tmp_path):
    outputs, reports = [], []
    for index, use_v2 in enumerate((False, True, True)):
        harness, registry, controls, implementation = extension()
        ref = V2_DESCRIPTOR.ref if use_v2 else harness.registration("analyze").ref
        plan = selected_plan(harness, ref)
        workspace = tmp_path / str(index)
        runtime = Runtime(
            registry,
            workspace,
            budget=BUDGET,
            implementation_files={
                r.ref: dict(implementation) for r in registry.registrations()
            },
        )
        dry = runtime.dry_run(plan)
        assert dry.plan_digest == plan.digest
        assert not workspace.exists()
        assert not controls.journal.snapshot() or all(
            c.stage == "validate" for c in controls.journal.snapshot()
        )
        assert all(c.stage == "validate" for c in harness.controls.journal.snapshot())
        result = runtime.run(plan)
        assert result.status == "SUCCEEDED"
        assert result.states == dict.fromkeys(
            ("search", "acquire", "analyze"), TaskState.SUCCEEDED
        )
        disk = reopen_workspace(workspace)
        assert disk.artifacts == result.outputs
        assert disk.plan.task("analyze").plugin_ref == ref
        selected = controls if use_v2 else harness.controls
        unselected = harness.controls if use_v2 else controls
        assert selected.journal.count("invoke", "analyze", "analyze") == 1
        assert selected.journal.count("business", "analyze", "analyze") == 1
        assert unselected.journal.count("invoke", "analyze", "analyze") == 0
        assert unselected.journal.count("business", "analyze", "analyze") == 0
        call = next(
            c
            for c in selected.journal.snapshot()
            if c.stage == "business" and c.operation == "analyze"
        )
        incoming = call.request.product_inputs["source"][0]
        assert incoming.artifact == disk.artifacts["acquire"]["out"][0]
        assert incoming.value == disk.records["acquire"]["out"][0]
        record = disk.records["analyze"]["out"][0]
        assert (
            type(record) is Product
            and validate_product_structure(record).is_fully_verified
        )
        assert record.producer.plugin == ref
        assert record.produced_by.attempt_id == disk.receipts["analyze"]["attempt_id"]
        assert tuple((e.role, e.artifact) for e in record.lineage) == (
            ("source", incoming.artifact),
        )
        assert (
            disk.started["analyze"]["resolved_inputs"]["source"][0]["artifact"][
                "record_id"
            ]
            == incoming.artifact.record_id
        )
        for name in ("search", "acquire", "analyze"):
            assert disk.resolutions[name]["disposition"] == "executed"
            assert disk.finished[name]["outcome"] == "succeeded"
            assert disk.finished[name]["receipt"] == disk.resolutions[name]["receipt"]
        marker = record.semantic_metadata.get("synthetic:implementation")
        assert (marker.value if marker else None) == (MARKER if use_v2 else None)
        out = disk.artifacts["analyze"]["out"][0]
        assert out.semantic_digest is not None
        outputs.append((record_semantic_material(record, {}), out.semantic_digest))
        reports.append(
            {
                "plugin_id": ref.plugin_id,
                "api_version": ref.api_version,
                "operation_id": plan.task("analyze").operation_id,
                "run_id": result.run_id,
                "selected_invokes": 1,
                "unselected_invokes": 0,
                "marker": marker.value if marker else None,
                "semantic_digest": out.semantic_digest,
                "plan_digest": plan.digest,
            }
        )
    assert outputs[1] == outputs[2] and outputs[0] != outputs[1]
    assert reports[1]["run_id"] != reports[2]["run_id"]
    assert reports[1]["plan_digest"] == reports[2]["plan_digest"]
    (tmp_path / "selection.json").write_text(
        json.dumps(reports, indent=2), encoding="utf-8"
    )


def rooted(name, roots):
    return any(name == root or name.startswith(root + ".") for root in roots)


def imports(tree, module, *, is_package=False):
    """Resolve relative/from imports and ordinary literal dynamic-import calls."""
    package = module if is_package else module.rsplit(".", 1)[0]
    names, aliases = set(), {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
                aliases[alias.asname or alias.name.split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                base = importlib.util.resolve_name("." * node.level + base, package)
            names.add(base)
            for alias in node.names:
                names.add(base + "." + alias.name)
                aliases[alias.asname or alias.name] = base + "." + alias.name
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        target = aliases.get(func.id, func.id) if isinstance(func, ast.Name) else ""
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            target = aliases.get(func.value.id, func.value.id) + "." + func.attr
        if target not in (
            "__import__",
            "builtins.__import__",
            "importlib.import_module",
        ):
            continue
        assert (
            node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ), "nonliteral dynamic import needs explicit boundary review"
        name = node.args[0].value
        if name.startswith("."):
            assert len(node.args) > 1 and isinstance(node.args[1], ast.Constant)
            name = importlib.util.resolve_name(name, node.args[1].value)
        names.add(name)
    return names


@pytest.mark.parametrize(
    "code,expected",
    [
        ("import tests.integration as f", "tests.integration"),
        ("from integration import _fake_plugins", "integration._fake_plugins"),
        ("from .. import analyzers", "insarforge.analyzers"),
        ("from ..providers import concrete", "insarforge.providers.concrete"),
        (
            "from importlib import import_module as load; load('tests.integration')",
            "tests.integration",
        ),
        (
            "import importlib as il; il.import_module('insarforge.analyzers')",
            "insarforge.analyzers",
        ),
    ],
)
def test_arch05_import_normalizer_covers_alias_relative_and_dynamic(code, expected):
    assert expected in imports(ast.parse(code), "insarforge.core.example")


def test_arch05_recursive_production_import_direction(tmp_path):
    inventory = {}
    for path in sorted(PRODUCTION.rglob("*.py")):
        assert not path.is_symlink()
        module = ".".join(path.relative_to(SOURCE).with_suffix("").parts)
        package = path.name == "__init__.py"
        if package:
            module = module.removesuffix(".__init__")
        names = imports(
            ast.parse(path.read_text(encoding="utf-8")), module, is_package=package
        )
        assert not any(
            rooted(n, ("tests", "integration", "_fake_plugins", "_fake_operations"))
            for n in names
        ), (path, names)
        if path.is_relative_to(PRODUCTION / "core"):
            assert not any(rooted(n, FAMILIES) for n in names), (path, names)
        inventory[str(path.relative_to(ROOT))] = sorted(names)
    assert inventory and "src/insarforge/core/runtime.py" in inventory
    (tmp_path / "imports.json").write_text(
        json.dumps(inventory, indent=2), encoding="utf-8"
    )


def test_arch05_cold_core_import_cannot_load_fakes_or_concrete_families():
    modules = []
    for path in sorted((PRODUCTION / "core").rglob("*.py")):
        module = ".".join(path.relative_to(SOURCE).with_suffix("").parts)
        modules.append(module.removesuffix(".__init__"))
    code = """
import importlib, importlib.abc, json, sys
blocked = ('tests','integration','insarforge.missions','insarforge.providers',
           'insarforge.processors','insarforge.corrections','insarforge.analyzers','insarforge.qc',
           'isce','isce2','isce3','gamma','gmtsar','stamps','mintpy')
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        assert not any(fullname==p or fullname.startswith(p+'.') for p in blocked), fullname
sys.meta_path.insert(0,Guard())
for module in json.loads(sys.argv[1]): importlib.import_module(module)
assert not any(n==p or n.startswith(p+'.') for n in sys.modules for p in blocked)
"""
    result = subprocess.run(
        [sys.executable, "-B", "-I", "-c", code, json.dumps(modules)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == result.stderr == ""


def test_arch06_core_has_no_concrete_dispatch(tmp_path):
    forbidden = {
        "fakeanalyzerv2",
        "fakeanalyzer",
        "synthetic:analyzer-v2",
        "synthetic:analyzer",
        "sentinel1",
        "sentinel-1",
        "isce2",
        "isce3",
        "gamma",
        "gmtsar",
        "stamps",
        "mintpy",
    }
    checked = []
    for path in sorted((PRODUCTION / "core").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id.lower() not in forbidden
            if isinstance(node, ast.Attribute):
                assert node.attr.lower() not in forbidden
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value.lower() not in forbidden
        checked.append(str(path.relative_to(ROOT)))
    (tmp_path / "dispatch.json").write_text(
        json.dumps({"files": checked, "forbidden": sorted(forbidden)}, indent=2),
        encoding="utf-8",
    )


def test_arch07_protocols_retain_exact_family_surfaces():
    tree = ast.parse((PRODUCTION / "contracts/plugins.py").read_text(encoding="utf-8"))
    protocols = {
        n.name: n
        for n in tree.body
        if isinstance(n, ast.ClassDef)
        and any(isinstance(b, ast.Name) and b.id == "Protocol" for b in n.bases)
    }
    expected = {
        "Mission": {"descriptor", "inspect"},
        "Provider": {"descriptor", "search", "acquire"},
        "Processor": {"descriptor", "process"},
        "Correction": {"descriptor", "correct"},
        "Analyzer": {"descriptor", "analyze"},
        "QC": {"descriptor", "assess"},
    }
    assert set(protocols) == set(expected)
    for name, node in protocols.items():
        methods = {
            n.name
            for n in node.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert methods == expected[name] and methods.isdisjoint({"run", "execute"})
        assert (
            len(node.bases) == 1
            and isinstance(node.bases[0], ast.Name)
            and node.bases[0].id == "Protocol"
        )


def test_arch08_product_is_a_shared_record_not_seventh_family():
    _, registry, _, _ = extension()
    assert set(PluginKind.__members__) == KINDS
    assert {k.value for k in PluginKind} == {n.lower() for n in KINDS}
    assert len(registry.registrations()) == 7
    assert len(registry.registrations(PluginKind.ANALYZER)) == 2
    assert {r.ref.kind for r in registry.registrations()} == set(PluginKind)
    for cls in (Product, ProductDraft):
        assert is_dataclass(cls) and cls.__dataclass_params__.frozen
        assert cls.__module__ == "insarforge.products.models" and cls.__bases__ == (
            object,
        )
        assert not any(hasattr(cls, name) for name in ("descriptor", "run", "execute"))
    assert all(
        r.factory.plugin_type not in (Product, ProductDraft)
        for r in registry.registrations()
    )
