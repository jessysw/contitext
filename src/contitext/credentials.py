"""Trusted-operator credential lifecycle and per-request database authentication."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import secrets
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from contitext.auth import AuthenticationError, PrincipalIdentity, TokenStore
from contitext.models import Credential, CredentialAudit, Principal


def digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class DatabaseTokenStore:
    """No identity cache: each new request observes committed revocation."""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    def resolve(self, token: str) -> PrincipalIdentity:
        if not token:
            raise AuthenticationError("invalid bearer credential")
        try:
            with self.session_factory() as session:
                principal = session.execute(
                    select(Principal).join(Credential, Credential.principal_id == Principal.id)
                    .where(Credential.token_hash == digest(token), Credential.revoked_at.is_(None),
                           (Credential.expires_at.is_(None) | (Credential.expires_at > func.clock_timestamp())))
                ).scalar_one_or_none()
                if principal is None:
                    raise AuthenticationError("invalid bearer credential")
                return PrincipalIdentity(principal.id, principal.name)
        except SQLAlchemyError:
            raise AuthenticationError("credential authentication unavailable; check database and migrations") from None

    def __repr__(self):
        return "DatabaseTokenStore(plaintext=redacted, cache=disabled)"


def metadata(item: Credential) -> dict:
    return {
        "credential_id": str(item.id), "principal_id": str(item.principal_id),
        "name": item.name, "created_at": item.created_at.astimezone(timezone.utc).isoformat(),
        "expires_at": item.expires_at.astimezone(timezone.utc).isoformat() if item.expires_at else None,
        "revoked_at": item.revoked_at.astimezone(timezone.utc).isoformat() if item.revoked_at else None,
    }


def audit(session, item: Credential, action: str, related_id: UUID | None = None):
    session.add(CredentialAudit(id=uuid4(), credential_id=item.id,
                                action=action, related_credential_id=related_id))


def issue(session, principal_id: UUID, name: str, *, expires_at=None) -> tuple[Credential, str]:
    if not name.strip():
        raise ValueError("credential name must not be empty")
    if session.get(Principal, principal_id) is None:
        raise ValueError("principal does not exist")
    if expires_at is not None and expires_at <= datetime.now(timezone.utc):
        raise ValueError("credential expiry must be in the future")
    token = "ctx_" + secrets.token_urlsafe(32)
    item = Credential(id=uuid4(), principal_id=principal_id, name=name.strip(),
                      token_hash=digest(token), expires_at=expires_at)
    session.add(item)
    session.flush()
    audit(session, item, "issued")
    return item, token


def locked(session, credential_id: UUID) -> Credential:
    item = session.scalar(select(Credential).where(Credential.id == credential_id).with_for_update())
    if item is None:
        raise ValueError("credential does not exist")
    return item


def revoke(session, credential_id: UUID) -> tuple[Credential, bool]:
    item = locked(session, credential_id)
    changed = item.revoked_at is None
    if changed:
        item.revoked_at = datetime.now(timezone.utc)
        audit(session, item, "revoked")
    return item, changed


def rotate(session, credential_id: UUID, *, expires_at=None) -> tuple[Credential, str]:
    previous = locked(session, credential_id)
    now = datetime.now(timezone.utc)
    if previous.revoked_at is not None or (previous.expires_at is not None and previous.expires_at <= now):
        raise ValueError("cannot rotate an inactive credential; issue a new credential")
    replacement, token = issue(session, previous.principal_id, previous.name,
                               expires_at=expires_at or previous.expires_at)
    previous.revoked_at = now
    audit(session, previous, "rotated", replacement.id)
    return replacement, token


def import_config(session, raw: str) -> dict:
    # Parse through the existing validator; only hash/identity pairs leave it.
    store = TokenStore.from_json(raw)
    imported = existing = 0
    for token_hash, identity in store.hashed_credentials():
        if session.get(Principal, identity.principal_id) is None:
            raise ValueError("configuration credential refers to an unprovisioned principal")
        item_id = uuid4()
        inserted = session.execute(insert(Credential).values(
            id=item_id, principal_id=identity.principal_id,
            name="Imported configuration credential", token_hash=token_hash.hex(),
        ).on_conflict_do_nothing(index_elements=[Credential.token_hash]).returning(Credential.id)).scalar_one_or_none()
        if inserted:
            audit(session, session.get(Credential, inserted), "imported")
            imported += 1
        else:
            item = session.scalar(select(Credential).where(Credential.token_hash == token_hash.hex()))
            if item.principal_id != identity.principal_id:
                raise ValueError("credential is already assigned to another principal")
            # In particular, never reset revoked_at or expiry on an existing row.
            existing += 1
    return {"imported": imported, "existing": existing}


def positive_seconds(value):
    import argparse
    try:
        seconds = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("expiry must be a positive number of seconds") from None
    if not 1 <= seconds <= 315360000:
        raise argparse.ArgumentTypeError("expiry must be between 1 and 315360000 seconds")
    return seconds


def add_arguments(commands):
    parser = commands.add_parser("credential", help="Manage credentials with trusted database access.")
    actions = parser.add_subparsers(dest="action", required=True)
    listing = actions.add_parser("list", help="List metadata only; never tokens or hashes.")
    listing.add_argument("--principal", type=UUID)
    issuance = actions.add_parser("issue", help="Issue one token to a new private file.")
    issuance.add_argument("principal_id", type=UUID)
    issuance.add_argument("--name", required=True)
    renewal = actions.add_parser("rotate", help="Atomically replace a credential and revoke its old token.")
    renewal.add_argument("credential_id", type=UUID)
    for action in (issuance, renewal):
        action.add_argument("--output", type=Path, required=True, help="New 0600 dotenv file; never overwrite.")
        action.add_argument("--expires-in", type=positive_seconds, metavar="SECONDS")
    actions.add_parser("revoke", help="Revoke a token without deleting history.").add_argument("credential_id", type=UUID)
    actions.add_parser("audit", help="Show credential lifecycle metadata.").add_argument("credential_id", type=UUID)
    actions.add_parser("import-config", help="Import configured token hashes without reviving revoked credentials.")


def manage(args, session_factory) -> dict:
    created_path = None
    created_stat = None
    try:
        with session_factory.begin() as session:
            if args.action == "list":
                query = select(Credential).order_by(Credential.created_at, Credential.id)
                if args.principal:
                    query = query.where(Credential.principal_id == args.principal)
                return {"credentials": [metadata(item) for item in session.scalars(query)]}
            if args.action == "import-config":
                return import_config(session, os.environ.get("CONTITEXT_AUTH_TOKENS", ""))
            if args.action == "audit":
                if session.get(Credential, args.credential_id) is None:
                    raise ValueError("credential does not exist")
                rows = session.scalars(select(CredentialAudit).where(CredentialAudit.credential_id == args.credential_id)
                                       .order_by(CredentialAudit.created_at, CredentialAudit.id))
                return {"audit": [{"event_id": str(row.id), "action": row.action,
                                   "created_at": row.created_at.astimezone(timezone.utc).isoformat(),
                                   "related_credential_id": str(row.related_credential_id) if row.related_credential_id else None}
                                  for row in rows]}
            if args.action == "revoke":
                item, changed = revoke(session, args.credential_id)
                return {**metadata(item), "changed": changed}
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=args.expires_in)) if args.expires_in else None
            if args.action == "issue":
                item, token = issue(session, args.principal_id, args.name, expires_at=expires_at)
            else:
                item, token = rotate(session, args.credential_id, expires_at=expires_at)
            # Delivery precedes commit. Failure rolls back issue/rotation, preserving
            # the old token. The output contains only client config, not DB access.
            fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created_path = args.output
            created_stat = os.fstat(fd)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write("# Private client credential. Do not commit or share.\n")
                stream.write(f"CONTITEXT_MCP_TOKEN='{token}'\n")
                stream.flush()
                os.fsync(stream.fileno())
            result = {**metadata(item), "configuration": str(args.output.resolve())}
        return result
    except BaseException:
        # Do not remove a file someone else replaced after we created it.
        if created_path is not None:
            try:
                current = created_path.lstat()
                if (current.st_dev, current.st_ino) == (created_stat.st_dev, created_stat.st_ino):
                    created_path.unlink()
            except OSError:
                pass
        raise
