"""Local POSIX single-writer storage; append-only facts and atomic small records."""

import hashlib
import math
import os
import re
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path

from insarforge.contracts._execution_json import canonical, decode, fields
from insarforge.contracts.errors import WorkspaceError

_FIELDS = {
    "run": "run_id scope_id resume_of plan_digest engine_identity implementations source_kind config_refs code_provenance",
    "started": "run_id scope_id task_id attempt_id sequence plan_digest fingerprint execution inputs allocation prepared started_at resolved_inputs",
    "finished": "attempt_id outcome error_code retryable ended_at receipt evidence",
    "receipt": "attempt_id task_id scope_id fingerprint execution inputs outputs cache_policy",
    "resolution": "task_id state disposition receipt error_code blocked_by fingerprint execution cache_reasons",
    "summary": "run_id status states completion_order",
    "recovery": "source_run status attempts",
    "index": "receipt receipt_digest",
    "transition": "task_id state",
}


def _validate_payload(kind, p):
    def text(value):
        return type(value) is str and bool(value)

    def identifier(value):
        return type(value) is str and re.fullmatch("[0-9a-f]{32}", value) is not None

    def digest(value):
        return type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None

    def timestamp(value):
        return type(value) in (int, float) and math.isfinite(value) and value >= 0

    if kind == "run":
        valid = (
            identifier(p["run_id"])
            and identifier(p["scope_id"])
            and (p["resume_of"] is None or identifier(p["resume_of"]))
            and digest(p["plan_digest"])
            and type(p["engine_identity"]) is dict
            and type(p["implementations"]) is dict
            and p["source_kind"] == "programmatic"
            and type(p["config_refs"]) is list
        )
    elif kind == "started":
        a = p["allocation"]
        valid = (
            all(identifier(p[k]) for k in ("run_id", "scope_id", "attempt_id"))
            and text(p["task_id"])
            and type(p["sequence"]) is int
            and p["sequence"] >= 1
            and digest(p["plan_digest"])
            and all(p[k] is None or digest(p[k]) for k in ("fingerprint", "execution"))
            and (p["inputs"] is None or type(p["inputs"]) is list)
            and type(a) is dict
            and set(a) == {"cpu_cores", "gpu_count", "memory_bytes"}
            and type(a["cpu_cores"]) is int
            and a["cpu_cores"] >= 1
            and type(a["gpu_count"]) is int
            and a["gpu_count"] >= 0
            and (
                a["memory_bytes"] is None
                or type(a["memory_bytes"]) is int
                and a["memory_bytes"] > 0
            )
            and type(p["prepared"]) is dict
            and timestamp(p["started_at"])
        )
    elif kind == "finished":
        valid = (
            identifier(p["attempt_id"])
            and p["outcome"] in ("succeeded", "failed", "interrupted")
            and type(p["retryable"]) is bool
            and (not p["retryable"] or p["outcome"] == "failed")
            and (
                p["error_code"] is None
                or p["error_code"]
                in (
                    "EXECUTION_RETRYABLE",
                    "EXECUTION_FAILED",
                    "CONTRACT_INVALID",
                    "OUTPUT_INVALID",
                    "INTERRUPTED",
                )
            )
            and timestamp(p["ended_at"])
            and (p["receipt"] is None or text(p["receipt"]))
            and type(p["evidence"]) is list
        )
    elif kind == "receipt":
        valid = (
            identifier(p["attempt_id"])
            and identifier(p["scope_id"])
            and text(p["task_id"])
            and all(p[k] is None or digest(p[k]) for k in ("fingerprint", "execution"))
            and (p["inputs"] is None or type(p["inputs"]) is list)
            and type(p["outputs"]) is dict
            and bool(p["outputs"])
            and all(
                text(k) and type(v) is list and bool(v) for k, v in p["outputs"].items()
            )
            and p["cache_policy"] in ("auto", "disabled")
        )
        if valid:
            from insarforge.contracts.execution import _artifact_from_dict

            for refs in p["outputs"].values():
                for ref in refs:
                    _artifact_from_dict(ref)
    elif kind == "resolution":
        valid = (
            text(p["task_id"])
            and p["state"] in ("succeeded", "failed", "blocked")
            and p["disposition"] in (None, "executed", "cache_reused")
            and (p["receipt"] is None or text(p["receipt"]))
            and type(p["blocked_by"]) is list
            and all(text(v) for v in p["blocked_by"])
            and p["error_code"]
            in (
                None,
                "UPSTREAM_FAILED",
                "RESTART_FORBIDDEN",
                "PREFLIGHT_FAILED",
                "EXECUTION_RETRYABLE",
                "EXECUTION_FAILED",
                "CONTRACT_INVALID",
                "OUTPUT_INVALID",
                "INTERRUPTED",
            )
        )
    elif kind == "summary":
        valid = (
            identifier(p["run_id"])
            and p["status"] in ("SUCCEEDED", "FAILED", "INTERRUPTED")
            and type(p["states"]) is dict
            and all(
                text(k)
                and v in ("pending", "running", "succeeded", "failed", "blocked")
                for k, v in p["states"].items()
            )
            and type(p["completion_order"]) is list
            and all(text(v) for v in p["completion_order"])
        )
    elif kind == "recovery":
        valid = (
            identifier(p["source_run"])
            and p["status"] == "INTERRUPTED"
            and type(p["attempts"]) is list
        )
    elif kind == "index":
        valid = text(p["receipt"]) and digest(p["receipt_digest"])
    else:
        valid = text(p["task_id"]) and p["state"] in (
            "pending",
            "running",
            "succeeded",
            "failed",
            "blocked",
        )
    if not valid:
        raise WorkspaceError("RECORD_VALUE")
    # Nested projections are closed schemas, not arbitrary persistence bags.
    if kind == "run":
        from insarforge.contracts.execution import _artifact_from_dict

        for identity in [p["engine_identity"], *p["implementations"].values()]:
            fields(identity, "value reusable reasons")
            if (
                type(identity["reusable"]) is not bool
                or (identity["value"] is not None and not digest(identity["value"]))
                or type(identity["reasons"]) is not list
                or not all(text(v) for v in identity["reasons"])
                or identity["reusable"] != (identity["value"] is not None)
            ):
                raise WorkspaceError("RECORD_IDENTITY")
        origin = fields(p["code_provenance"], "package_version source_revision")
        revision = origin["source_revision"]
        if not text(origin["package_version"]) or not (
            revision is None
            or type(revision) is str
            and re.fullmatch("[0-9a-f]{40}", revision)
        ):
            raise WorkspaceError("RECORD_CODE_PROVENANCE")
        for ref in p["config_refs"]:
            _artifact_from_dict(ref)
    if kind in ("started", "receipt") and p["inputs"] is not None:
        ports = []
        for item in p["inputs"]:
            fields(item, "port semantic_digests")
            if (
                not text(item["port"])
                or type(item["semantic_digests"]) is not list
                or not all(digest(v) for v in item["semantic_digests"])
            ):
                raise WorkspaceError("RECORD_INPUTS")
            ports.append(item["port"])
        if ports != sorted(set(ports)):
            raise WorkspaceError("RECORD_INPUT_PORTS")
    if kind == "started":
        from insarforge.contracts.execution import _artifact_from_dict
        from insarforge.provenance.runtime_evidence import (
            ArtifactEvidence,
            PreparationEvidence,
        )

        PreparationEvidence.from_dict(p["prepared"])
        if type(p["resolved_inputs"]) is not dict:
            raise WorkspaceError("RECORD_RESOLVED_INPUTS")
        for port, values in p["resolved_inputs"].items():
            if not text(port) or type(values) is not list:
                raise WorkspaceError("RECORD_RESOLVED_INPUTS")
            for item in values:
                fields(item, "artifact manifest_location effective_digest evidence")
                ref = _artifact_from_dict(item["artifact"])
                if not text(item["manifest_location"]) or (
                    item["effective_digest"] is not None
                    and not digest(item["effective_digest"])
                ):
                    raise WorkspaceError("RECORD_RESOLVED_INPUTS")
                if item["evidence"] is not None:
                    if ArtifactEvidence.from_dict(item["evidence"]).artifact != ref:
                        raise WorkspaceError("RECORD_INPUT_BINDING")
        effective = [
            {
                "port": port,
                "semantic_digests": [item["effective_digest"] for item in values],
            }
            for port, values in sorted(p["resolved_inputs"].items())
        ]
        if any(d is None for row in effective for d in row["semantic_digests"]):
            effective = None
        if effective != p["inputs"]:
            raise WorkspaceError("RECORD_EFFECTIVE_INPUT_BINDING")
    if kind == "resolution":
        if not all(
            p[k] is None or digest(p[k]) for k in ("fingerprint", "execution")
        ) or (
            type(p["cache_reasons"]) is not list
            or not all(text(v) for v in p["cache_reasons"])
        ):
            raise WorkspaceError("RECORD_RESOLUTION_EVIDENCE")
    if kind == "finished":
        if (
            (p["outcome"] == "succeeded") != (p["receipt"] is not None)
            or p["retryable"] != (p["error_code"] == "EXECUTION_RETRYABLE")
            or (p["outcome"] == "succeeded" and p["error_code"] is not None)
        ):
            raise WorkspaceError("RECORD_OUTCOME")
        from insarforge.products.assets import NativeAsset
        from insarforge.products.serialization import _d

        for item in p["evidence"]:
            _d(item, NativeAsset)
    if kind == "recovery":
        for item in p["attempts"]:
            fields(item, "attempt_id outcome receipt")
            if (
                not identifier(item["attempt_id"])
                or item["outcome"] not in ("succeeded", "interrupted")
                or (item["outcome"] == "succeeded") != text(item["receipt"])
                or (item["outcome"] == "interrupted" and item["receipt"] is not None)
            ):
                raise WorkspaceError("RECORD_RECOVERY")


def record_bytes(kind, payload):
    if kind not in _FIELDS:
        raise WorkspaceError("RECORD_KIND")
    try:
        fields(payload, _FIELDS[kind])
        _validate_payload(kind, payload)
        return canonical({"schema_version": 2, "kind": kind, "payload": payload})
    except Exception:
        raise WorkspaceError("RECORD_INVALID") from None


def parse_record(raw, kind):
    try:
        data = fields(decode(raw), "schema_version kind payload")
        if (
            type(data["schema_version"]) is not int
            or data["schema_version"] != 2
            or data["kind"] != kind
        ):
            raise WorkspaceError("RUNTIME_RECORD_VERSION_UNSUPPORTED")
        payload = fields(data["payload"], _FIELDS[kind])
        record_bytes(kind, payload)
        return payload
    except WorkspaceError:
        raise
    except Exception:
        raise WorkspaceError("RECORD_INVALID") from None


def key(value):
    return hashlib.sha256(value.encode()).hexdigest()


def check_local(path):
    """Fail closed outside explicitly supported Linux local filesystems."""
    if os.name != "posix" or not Path("/proc/self/mountinfo").is_file():
        raise WorkspaceError("WORKSPACE_PLATFORM_UNSUPPORTED")
    matches = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        before, after = line.split(" - ", 1)
        mount = Path(before.split()[4].replace(r"\040", " "))
        if path == mount or mount in path.parents:
            matches.append((len(mount.parts), after.split()[0]))
    if not matches or max(matches)[1] not in {
        "ext4",
        "ext3",
        "ext2",
        "xfs",
        "btrfs",
        "tmpfs",
        "overlay",
    }:
        raise WorkspaceError("WORKSPACE_FILESYSTEM_UNSUPPORTED")


def safe_path(path):
    if not path.is_absolute() or ".." in path.parts:
        raise WorkspaceError("WORKSPACE_PATH")
    for part in (*reversed(path.parents), path):
        if part.is_symlink():
            raise WorkspaceError("WORKSPACE_SYMLINK")


class Workspace:
    """One coordinator owns this store; plugin workers never receive it."""

    def __init__(self, root):
        self.root = Path(root)
        self.area = self.root / ".insarforge"
        self._locked = False

    def path(self, relative):
        p = Path(relative)
        if p.is_absolute() or not p.parts or any(x in (".", "..") for x in p.parts):
            raise WorkspaceError("WORKSPACE_RELATIVE_PATH")
        result = self.area / p
        safe_path(result)
        return result

    @contextmanager
    def writer(self):
        safe_path(self.root)
        check_local(self.root)
        import fcntl

        if any((p / ".git").exists() for p in (self.root, *self.root.parents)):
            raise WorkspaceError("REPOSITORY_IS_NOT_WORKSPACE")
        self.area.mkdir(parents=True, exist_ok=True)
        safe_path(self.area)
        fd = os.open(
            self.area / "workspace.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
        )
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_nlink != 1:
                raise WorkspaceError("WORKSPACE_LOCK_INVALID")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise WorkspaceError("WORKSPACE_BUSY") from None
            probe = os.open(self.area / "workspace.lock", os.O_RDWR | os.O_NOFOLLOW)
            try:
                try:
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    pass
                else:
                    raise WorkspaceError("WORKSPACE_LOCK_UNSUPPORTED")
            finally:
                os.close(probe)
            self._locked = True
            try:
                yield self
            finally:
                self._locked = False
        finally:
            os.close(fd)

    def write_bytes(self, relative, raw):
        if not self._locked or type(raw) is not bytes:
            raise WorkspaceError("WORKSPACE_WRITER_REQUIRED")
        path = self.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        safe_path(path)
        if path.exists():
            raise WorkspaceError("FACT_ALREADY_EXISTS")
        temp = path.with_name("." + uuid.uuid4().hex + ".tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        # Sole writer and fresh UUID namespace; never overwrite historical facts.
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return relative

    def read_bytes(self, relative):
        path = self.path(relative)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise WorkspaceError("WORKSPACE_FILE_INVALID")
            return stream.read()

    def write(self, relative, kind, payload):
        return self.write_bytes(relative, record_bytes(kind, payload))

    def read(self, relative, kind):
        try:
            return parse_record(self.read_bytes(relative), kind)
        except (OSError, ValueError):
            raise WorkspaceError("RECORD_UNREADABLE") from None

    def inventory(self, pattern):
        return tuple(
            sorted(
                p.relative_to(self.area).as_posix()
                for p in self.area.glob(pattern)
                if p.is_file()
            )
        )

    def status(self, run_id):
        prefix = "runs/" + run_id
        summary = self.path(prefix + "/summary.json")
        if summary.exists():
            return self.read(prefix + "/summary.json", "summary")["status"]
        recovery = self.path(prefix + "/recovery.json")
        if recovery.exists():
            return self.read(prefix + "/recovery.json", "recovery")["status"]
        return "RUNNING"
