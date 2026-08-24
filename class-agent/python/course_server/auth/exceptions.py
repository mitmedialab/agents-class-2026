"""Authentication exceptions safe for application-layer handling."""


class AuthenticationError(Exception):
    """Base class for expected authentication failures."""


class InvalidCredentials(AuthenticationError):
    """Username or access code was invalid without revealing which one."""


class LoginRateLimited(AuthenticationError):
    """Too many failed attempts occurred within the configured window."""


class InvalidSession(AuthenticationError):
    """A session token was unknown, expired, revoked, or no longer usable."""


class UserAlreadyExists(AuthenticationError):
    """A unique username or email is already registered."""


class UserNotFound(AuthenticationError):
    """An administrative operation referenced an unknown user."""
