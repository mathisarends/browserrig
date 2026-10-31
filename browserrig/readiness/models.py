from browserrig.core.kinds import ReadinessPhase, ReadinessStage, ReadinessStatus
from browserrig.core.options import Options


class ReadinessReport(Options):
    id: str
    target_id: str
    document_id: str
    phase: ReadinessPhase
    stage: ReadinessStage = ReadinessStage.ONGOING
    status: ReadinessStatus
    duration: float
    reason: str = ""
    timed_out: bool = False
