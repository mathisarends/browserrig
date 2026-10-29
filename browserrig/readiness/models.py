from browserrig.core.geometry import Geometry
from browserrig.core.kinds import ObservationKind, ReadinessPhase, ReadinessStatus
from browserrig.core.options import Options


class ReadinessReport(Options):
    id: str
    target_id: str
    document_id: str
    mode: ObservationKind
    phase: ReadinessPhase
    status: ReadinessStatus
    duration: float
    reason: str = ""
    geometry: Geometry | None = None
