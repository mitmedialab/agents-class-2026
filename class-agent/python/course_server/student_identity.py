"""Resolve student identity from the authenticated account, never tool arguments."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from agent_core import PrincipalContext

if TYPE_CHECKING:
    from course_server.agent.capabilities import ApplicantStore
    from course_server.application_access import ApplicationAccessPolicy
    from course_server.auth.store import AuthStore


class StudentIdentityPolicy:
    def __init__(
        self,
        auth: AuthStore | None = None,
        *,
        applicants: ApplicantStore | None = None,
        access: ApplicationAccessPolicy | None = None,
        repository_prefix: str | None = None,
    ) -> None:
        self._auth = auth
        self._applicants = applicants
        self._access = access
        self._repository_prefix = repository_prefix

    async def email(self, principal: PrincipalContext) -> str:
        if (
            not principal.authenticated
            or principal.user_id is None
            or "student" not in principal.roles
            or self._auth is None
        ):
            raise PermissionError("An active student account is required to identify classmates.")
        user = await self._auth.get_user_by_id(principal.user_id)
        if (
            user is None
            or user.id != principal.user_id
            or not user.active
            or user.role != "student"
        ):
            raise PermissionError("An active student account is required to identify classmates.")
        return str(user.email).strip().casefold()

    async def own_application_id(self, principal: PrincipalContext) -> UUID:
        email = await self.email(principal)
        if self._applicants is None or self._access is None:
            raise PermissionError("Accepted student identity is unavailable.")
        scope = self._access.scope(principal, accepted_only=True)
        matches: list[UUID] = []
        for application_id in sorted(scope or (), key=str):
            record = await self._applicants.read_application(application_id)
            fields = record.get("application")
            if (
                isinstance(fields, dict)
                and str(fields.get("email", "")).strip().casefold() == email
            ):
                matches.append(application_id)
        if len(matches) != 1:
            raise PermissionError(
                "Your login email must match exactly one accepted application for a personal "
                "profile read. Ask staff to check missing or duplicate accepted records."
            )
        return matches[0]

    async def project_candidates(self, principal: PrincipalContext) -> frozenset[str]:
        """Apply the course's prefix + first-name convention only to accepted applications."""
        email = await self.email(principal)
        if self._applicants is None or self._access is None or self._repository_prefix is None:
            raise PermissionError("Accepted student project identity is unavailable.")
        scope = self._access.scope(principal, accepted_only=True)
        if not scope:
            return frozenset()
        owners: dict[str, set[str]] = {}
        own_names: set[str] = set()
        for application_id in sorted(scope, key=str):
            record = await self._applicants.read_application(application_id)
            fields = record.get("application")
            if not isinstance(fields, dict):
                raise PermissionError("An accepted application is unavailable.")
            name = fields.get("name")
            applicant_email = fields.get("email")
            if (
                not isinstance(name, str)
                or not name.split()
                or not isinstance(applicant_email, str)
            ):
                continue
            applicant_email = applicant_email.strip().casefold()
            if not applicant_email:
                continue
            first_name = name.split()[0].casefold()
            owners.setdefault(first_name, set()).add(applicant_email)
            if applicant_email == email:
                own_names.add(first_name)
        if not own_names:
            raise PermissionError(
                "Your login email does not match an accepted application with a name. "
                "Ask staff to check the account and application email before website matching."
            )
        return frozenset(
            (self._repository_prefix + name).casefold()
            for name, emails in owners.items()
            if name not in own_names and len(emails) == 1
        )
