import enum


class ClaimStatus(str, enum.Enum):
    submitted = "submitted"
    processing = "processing"
    paused_awaiting_vehicle_confirmation = "paused_awaiting_vehicle_confirmation"
    authenticity_failed = "authenticity_failed"
    review_required = "review_required"
    estimate_ready = "estimate_ready"
    closed = "closed"


class AuthenticityVerdict(str, enum.Enum):
    pending = "pending"
    clear = "clear"
    flagged = "flagged"


class PipelineEventStatus(str, enum.Enum):
    started = "started"
    passed = "passed"
    failed = "failed"
    warning = "warning"


class DamageType(str, enum.Enum):
    dent = "dent"
    scratch = "scratch"
    crack = "crack"
    glass_shatter = "glass_shatter"
    lamp_broken = "lamp_broken"
    tire_flat = "tire_flat"


class Severity(str, enum.Enum):
    minor = "minor"
    moderate = "moderate"
    severe = "severe"


class FraudSignalType(str, enum.Enum):
    transactional = "transactional"
    soft_fraud = "soft_fraud"
    organised_fraud_graph = "organised_fraud_graph"
