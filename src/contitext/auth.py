"""Local bearer-token authentication and project authorization."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
from types import MappingProxyType
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from contitext.models import Project, ProjectACL


class AuthenticationError(RuntimeError):
    """Raised when a bearer credential is absent or unknown."""


class ProjectNotFoundError(RuntimeError):
    """Used for both unknown and unauthorized projects."""


@dataclass(frozen=True)
class PrincipalIdentity:
    principal_id: UUID
    name: str


@dataclass(frozen=True)
class _StoredCredential:
    token_hash: bytes
    identity: PrincipalIdentity


class TokenStore:
    """Resolve local bearer credentials while retaining hashes only."""

    def __init__(self, credentials: Mapping[bytes, PrincipalIdentity]) -> None:
        self._credentials = MappingProxyType(dict(credentials))

    @classmethod
    def from_json(cls, raw: str) -> "TokenStore":
        try:
            parsed: Any = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AuthenticationError("invalid CONTITEXT_AUTH_TOKENS JSON") from exc
        if not isinstance(parsed, dict) or not parsed:
            raise AuthenticationError("at least one local bearer credential is required")

        credentials: dict[bytes, PrincipalIdentity] = {}
        for plaintext, details in parsed.items():
            if not isinstance(plaintext, str) or not plaintext:
                raise AuthenticationError("bearer credentials must be non-empty strings")
            if not isinstance(details, dict):
                raise AuthenticationError("credential metadata must be an object")
            try:
                identity = PrincipalIdentity(
                    principal_id=UUID(str(details["principal_id"])),
                    name=str(details["name"]),
                )
            except (KeyError, ValueError) as exc:
                raise AuthenticationError("credential metadata requires principal_id and name") from exc
            digest = hashlib.sha256(plaintext.encode("utf-8")).digest()
            if digest in credentials:
                raise AuthenticationError("duplicate bearer credential")
            credentials[digest] = identity
        return cls(credentials)

    def resolve(self, bearer_token: str) -> PrincipalIdentity:
        candidate = hashlib.sha256(bearer_token.encode("utf-8")).digest()
        for digest, identity in self._credentials.items():
            if hmac.compare_digest(candidate, digest):
                return identity
        raise AuthenticationError("invalid bearer credential")

    def __repr__(self) -> str:
        return f"TokenStore(credentials={len(self._credentials)}, plaintext=redacted)"

    def hashed_credentials(self):
        """Trusted migration input; never includes plaintext tokens."""
        return tuple(self._credentials.items())


ROLE_LEVEL = {"reader": 1, "writer": 2, "owner": 3}


def require_project_access(
    session: Session,
    principal_id: UUID,
    project_id: str,
    minimum_role: str = "reader",
) -> str:
    """Return the granted role or raise the non-enumerating not-found error."""
    if minimum_role not in ROLE_LEVEL:
        raise ValueError(f"unknown required role: {minimum_role}")
    role = session.execute(
        select(ProjectACL.role)
        .join(Project, Project.id == ProjectACL.project_id)
        .where(
            ProjectACL.project_id == project_id,
            ProjectACL.principal_id == principal_id,
        )
    ).scalar_one_or_none()
    if role is None or ROLE_LEVEL[role] < ROLE_LEVEL[minimum_role]:
        raise ProjectNotFoundError("project not found")
    return role
