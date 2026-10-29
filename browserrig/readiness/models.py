from browserrig.browser.config import Options
from browserrig.browser.models import Geometry
from browserrig.kinds import ReadinessPhase, ReadinessStatus
from browserrig.observation.config import ObservationKind


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
