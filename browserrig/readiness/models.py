from browserrig.core import Options, ReadinessPhase, ReadinessStage, ReadinessStatus


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
