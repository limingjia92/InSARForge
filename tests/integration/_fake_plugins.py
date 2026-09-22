"""Six explicit synthetic families and thread-safe, test-only controls.

No business superclass, native backend, scientific constants or filesystem I/O.
Call records retain immutable request/result values for adapter conformance tests.
"""

from collections import Counter
from dataclasses import dataclass, field
from threading import Event, Lock

from insarforge.contracts.context import ExecutionContext
from insarforge.contracts.errors import ExecutionError, RetryableExecutionError
from insarforge.contracts.identity import PluginDescriptor, PluginKind
from insarforge.contracts.plugins import (
    AcquireRequest,
    AnalysisRequest,
    CorrectionRequest,
    InspectionRequest,
    ProcessingRequest,
    QCRequest,
    SearchRequest,
)
from insarforge.contracts.records import (
    AccessStatus,
    AcquisitionMetadata,
    CatalogEntry,
    CatalogSnapshot,
    ProviderAvailability,
    ProviderDelivery,
    QCReport,
    QCStatus,
)
from insarforge.contracts.values import freeze_json, validate_identifier
from insarforge.products.models import ProductDraft
from insarforge.products.semantics import SemanticStatus, SemanticValue

OPERATIONS = ("inspect", "search", "acquire", "process", "correct", "analyze", "assess")


def known(value):
    return SemanticValue(SemanticStatus.KNOWN, freeze_json(value), None, ())


@dataclass(frozen=True)
class FakeConfig:
    variant: str = "synthetic:default"

    def __post_init__(self):
        validate_identifier(self.variant)


def descriptor(kind):
    return PluginDescriptor(
        kind, "synthetic:" + kind.value, 1, "1", "Synthetic " + kind.value, ()
    )


@dataclass(frozen=True)
class Call:
    sequence: int
    stage: str
    operation: str
    task_id: str | None
    ordinal: int
    request: object = None
    result: object = None


class CallJournal:
    def __init__(self):
        self._lock = Lock()
        self._calls = []
        self._counts = Counter()

    def record(self, stage, operation, task_id=None, *, request=None, result=None):
        key = (stage, operation, task_id)
        with self._lock:
            self._counts[key] += 1
            ordinal = self._counts[key]
            self._calls.append(
                Call(
                    len(self._calls) + 1,
                    stage,
                    operation,
                    task_id,
                    ordinal,
                    request,
                    result,
                )
            )
            return ordinal

    def snapshot(self):
        with self._lock:
            return tuple(self._calls)

    def count(self, stage, operation, task_id=None):
        with self._lock:
            return self._counts[(stage, operation, task_id)]


@dataclass(frozen=True)
class Failure:
    operation: str
    task_id: str
    ordinal: int
    retryable: bool

    def __post_init__(self):
        if self.operation not in OPERATIONS:
            raise ValueError("unknown operation")
        validate_identifier(self.task_id)
        if type(self.ordinal) is not int or self.ordinal < 1:
            raise ValueError("positive invocation ordinal required")
        if type(self.retryable) is not bool:
            raise TypeError("retryable must be bool")


class HoldPoint:
    """One-shot hold for exact (operation, task) participants; timeouts are guards."""

    def __init__(self, participants, timeout=10):
        participants = tuple(participants)
        if not participants or len(set(participants)) != len(participants):
            raise ValueError("distinct participants required")
        for operation, task_id in participants:
            if operation not in OPERATIONS:
                raise ValueError("unknown operation")
            validate_identifier(task_id)
        if timeout <= 0:
            raise ValueError("positive deadlock timeout required")
        self.participants = frozenset(participants)
        self.timeout = timeout
        self.all_entered = Event()
        self.release = Event()
        self._seen = set()
        self._lock = Lock()

    def enter(self, operation, task_id):
        key = (operation, task_id)
        if key not in self.participants:
            return
        with self._lock:
            if key in self._seen:
                raise ExecutionError("SYNTHETIC_HOLD_REUSED")
            self._seen.add(key)
            if self._seen == self.participants:
                self.all_entered.set()
        if not self.release.wait(self.timeout):
            raise ExecutionError("SYNTHETIC_HOLD_TIMEOUT")


@dataclass(frozen=True)
class Controls:
    journal: CallJournal = field(default_factory=CallJournal)
    failures: tuple[Failure, ...] = ()
    hold: HoldPoint | None = None

    def __post_init__(self):
        failures = tuple(self.failures)
        if any(type(f) is not Failure for f in failures):
            raise TypeError("Failure values required")
        keys = [(f.operation, f.task_id, f.ordinal) for f in failures]
        if len(set(keys)) != len(keys):
            raise ValueError("conflicting failure rules")
        object.__setattr__(self, "failures", failures)

    def before_invoke(self, operation, context):
        ordinal = self.journal.record("invoke", operation, context.task_id)
        if self.hold is not None:
            self.hold.enter(operation, context.task_id)
        for failure in self.failures:
            if (failure.operation, failure.task_id, failure.ordinal) == (
                operation,
                context.task_id,
                ordinal,
            ):
                error = RetryableExecutionError if failure.retryable else ExecutionError
                raise error("SYNTHETIC_INJECTED_FAILURE")


def business(journal, operation, expected, request, context, result):
    if type(request) is not expected:
        raise TypeError("exact family request required")
    journal.record(
        "business", operation, context.task_id, request=request, result=result
    )
    return result


def draft(config, operation, parameters):
    return ProductDraft(
        "synthetic:product",
        "synthetic:profile",
        1,
        (),
        (),
        (),
        (),
        {
            "synthetic:payload": known(
                {
                    "variant": config.variant,
                    "operation": operation,
                    "parameters": parameters,
                }
            )
        },
        {},
    )


@dataclass(frozen=True)
class FakeMission:
    config: FakeConfig
    journal: CallJournal
    descriptor: PluginDescriptor = field(
        default_factory=lambda: descriptor(PluginKind.MISSION), init=False
    )

    def inspect(
        self, request: InspectionRequest, context: ExecutionContext
    ) -> AcquisitionMetadata:
        result = AcquisitionMetadata(
            "synthetic:inspection",
            "synthetic:acquisition",
            1,
            request.source.artifact,
            self.descriptor.ref,
            {"synthetic:variant": known(self.config.variant)},
            (),
            {},
        )
        return business(
            self.journal, "inspect", InspectionRequest, request, context, result
        )


@dataclass(frozen=True)
class FakeProvider:
    config: FakeConfig
    journal: CallJournal
    descriptor: PluginDescriptor = field(
        default_factory=lambda: descriptor(PluginKind.PROVIDER), init=False
    )

    def search(
        self, request: SearchRequest, context: ExecutionContext
    ) -> CatalogSnapshot:
        result = CatalogSnapshot(
            "synthetic:catalog",
            "synthetic:catalog",
            1,
            self.descriptor.ref,
            request.query_schema_id,
            request.query_schema_version,
            request.selectors,
            (
                CatalogEntry(
                    "synthetic:entry",
                    AccessStatus(
                        ProviderAvailability.AVAILABLE,
                        ProviderDelivery.DIRECT,
                        False,
                        None,
                    ),
                    {"variant": self.config.variant},
                    (),
                ),
            ),
            {},
        )
        return business(self.journal, "search", SearchRequest, request, context, result)

    def acquire(
        self, request: AcquireRequest, context: ExecutionContext
    ) -> ProductDraft:
        return business(
            self.journal,
            "acquire",
            AcquireRequest,
            request,
            context,
            draft(self.config, "acquire", request.parameters),
        )


@dataclass(frozen=True)
class FakeProcessor:
    config: FakeConfig
    journal: CallJournal
    descriptor: PluginDescriptor = field(
        default_factory=lambda: descriptor(PluginKind.PROCESSOR), init=False
    )

    def process(
        self, request: ProcessingRequest, context: ExecutionContext
    ) -> tuple[ProductDraft, ...]:
        return business(
            self.journal,
            "process",
            ProcessingRequest,
            request,
            context,
            (draft(self.config, "process", request.parameters),),
        )


@dataclass(frozen=True)
class FakeCorrection:
    config: FakeConfig
    journal: CallJournal
    descriptor: PluginDescriptor = field(
        default_factory=lambda: descriptor(PluginKind.CORRECTION), init=False
    )

    def correct(
        self, request: CorrectionRequest, context: ExecutionContext
    ) -> tuple[ProductDraft, ...]:
        return business(
            self.journal,
            "correct",
            CorrectionRequest,
            request,
            context,
            (draft(self.config, "correct", request.parameters),),
        )


@dataclass(frozen=True)
class FakeAnalyzer:
    config: FakeConfig
    journal: CallJournal
    descriptor: PluginDescriptor = field(
        default_factory=lambda: descriptor(PluginKind.ANALYZER), init=False
    )

    def analyze(
        self, request: AnalysisRequest, context: ExecutionContext
    ) -> tuple[ProductDraft, ...]:
        return business(
            self.journal,
            "analyze",
            AnalysisRequest,
            request,
            context,
            (draft(self.config, "analyze", request.parameters),),
        )


@dataclass(frozen=True)
class FakeQC:
    config: FakeConfig
    journal: CallJournal
    descriptor: PluginDescriptor = field(
        default_factory=lambda: descriptor(PluginKind.QC), init=False
    )

    def assess(self, request: QCRequest, context: ExecutionContext) -> QCReport:
        result = QCReport(
            "synthetic:qc",
            "synthetic:qc",
            1,
            QCStatus.NOT_EVALUATED,
            request.metric_profile_id,
            "1",
            request.target_refs,
            (),
            (),
            {},
        )
        return business(self.journal, "assess", QCRequest, request, context, result)
