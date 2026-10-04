"""Product platform infrastructure kept outside the optimization core."""

from scheduler.platform.database import PlatformDatabase, PlatformDatabaseSettings
from scheduler.platform.auth import (
    AuthenticatedUser,
    AuthenticationError,
    AuthService,
    CsrfValidationError,
    IssuedSession,
    PasswordHasher,
    UserProvisionResult,
)
from scheduler.platform.jobs import (
    JobCreateResult,
    JobLeaseLost,
    JobNotFound,
    JobQueueFull,
    SolveJob,
    SolveJobStore,
)
from scheduler.platform.model_usage import (
    ModelQuotaExceeded,
    ModelUsageStore,
    QuotaLimits,
    UsageReservation,
)
from scheduler.platform.store import (
    OrganizationRecord,
    PlatformStore,
    RevisionConflict,
    TenantNotFound,
    WorkspaceRecord,
)

__all__ = [
    "OrganizationRecord",
    "AuthenticatedUser",
    "AuthenticationError",
    "AuthService",
    "CsrfValidationError",
    "IssuedSession",
    "PasswordHasher",
    "UserProvisionResult",
    "JobCreateResult",
    "JobLeaseLost",
    "JobNotFound",
    "JobQueueFull",
    "ModelQuotaExceeded",
    "ModelUsageStore",
    "PlatformDatabase",
    "PlatformDatabaseSettings",
    "PlatformStore",
    "QuotaLimits",
    "SolveJob",
    "SolveJobStore",
    "UsageReservation",
    "RevisionConflict",
    "TenantNotFound",
    "WorkspaceRecord",
]
