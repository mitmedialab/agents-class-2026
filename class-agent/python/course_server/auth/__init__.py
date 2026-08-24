"""Access-code authentication and session services."""

from .exceptions import (
    InvalidCredentials,
    InvalidSession,
    LoginRateLimited,
    UserAlreadyExists,
    UserNotFound,
)
from .models import (
    AnonymousSessionRecord,
    AuthSessionRecord,
    IssuedAccessCode,
    SessionCredential,
    SessionPolicy,
    StoredUser,
    User,
    UserRole,
)
from .security import Argon2AccessCodeHasher, generate_access_code
from .service import AuthenticationService, UserAdminService
from .store import AuthStore, InMemoryAuthStore

__all__ = [
    "AnonymousSessionRecord",
    "Argon2AccessCodeHasher",
    "AuthSessionRecord",
    "AuthStore",
    "AuthenticationService",
    "InMemoryAuthStore",
    "InvalidCredentials",
    "InvalidSession",
    "IssuedAccessCode",
    "LoginRateLimited",
    "SessionCredential",
    "SessionPolicy",
    "StoredUser",
    "User",
    "UserAdminService",
    "UserAlreadyExists",
    "UserNotFound",
    "UserRole",
    "generate_access_code",
]
