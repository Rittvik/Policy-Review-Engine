"""Local append-only review snapshots; no appeal adjudication or external calls."""

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import json

from pydantic import AwareDatetime, ValidationError, model_validator

from .decisions import Decision, FrozenModel
from .schemas import Claim, Nonblank


class ReviewStoreError(Exception):
    """Storage is unavailable, incompatible, or contains an invalid record."""


class DuplicateReviewError(ReviewStoreError):
    """A review ID already exists; use a new ID for a new review attempt."""


class ReviewLinkError(ReviewStoreError):
    """A prior-review link is absent or belongs to a different claim scope."""


class ReviewRecord(FrozenModel):
    claim: Claim
    decision: Decision
    recorded_at: AwareDatetime
    previous_review_id: Nonblank | None = None
    supplemental_input_json: Nonblank | None = None

    @model_validator(mode="after")
    def identities_match(self):
        context = self.decision.context
        if (context.claim_id, context.review_id) != (self.claim.claim_id, self.claim.review_id):
            raise ValueError("Decision identity must match the saved claim snapshot")
        if self.previous_review_id == self.claim.review_id:
            raise ValueError("A review cannot link to itself")
        if self.supplemental_input_json is not None:
            if not isinstance(json.loads(self.supplemental_input_json), dict):
                raise ValueError("Supplemental review input must be a JSON object")
        return self


_VERSION = 1
_APPLICATION_ID = 0x434C4D53  # CLMS; avoids treating another SQLite file as this store.
_SCHEMA = (
    """CREATE TABLE reviews (
        review_id TEXT PRIMARY KEY NOT NULL,
        claim_id TEXT NOT NULL,
        insurer TEXT NOT NULL,
        plan_name TEXT NOT NULL,
        member_id TEXT NOT NULL,
        previous_review_id TEXT REFERENCES reviews(review_id),
        record_json TEXT NOT NULL,
        CHECK (previous_review_id IS NULL OR previous_review_id != review_id)
    )""",
    "CREATE INDEX review_scope ON reviews(insurer, plan_name, member_id, claim_id)",
    """CREATE TRIGGER reviews_no_update BEFORE UPDATE ON reviews
       BEGIN SELECT RAISE(ABORT, 'Review records are append-only'); END""",
    """CREATE TRIGGER reviews_no_delete BEFORE DELETE ON reviews
       BEGIN SELECT RAISE(ABORT, 'Review records are append-only'); END""",
)


def _scope(claim: Claim) -> tuple[str, str, str, str]:
    return claim.insurer, claim.plan_name, claim.member_id, claim.claim_id


class ReviewStore:
    """One local SQLite file, short transactions, no update/delete API.

    These are application-level immutability guarantees, not tamper-proof storage.
    A file owner can modify the database/schema. Recorded time is a save timestamp,
    not proof of when a denial was communicated or an appeal was received.
    """

    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connection(create=True) as db:
                db.execute("BEGIN IMMEDIATE")
                version = db.execute("PRAGMA user_version").fetchone()[0]
                application = db.execute("PRAGMA application_id").fetchone()[0]
                objects = db.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
                if version == 0 and application == 0 and not objects:
                    for statement in _SCHEMA:
                        db.execute(statement)
                    db.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
                    db.execute(f"PRAGMA user_version = {_VERSION}")
                else:
                    self._check_schema(db)
        except OSError as exc:
            raise ReviewStoreError("Could not create the local review store directory") from exc

    @contextmanager
    def _connection(self, *, create=False):
        db = None
        try:
            # Opening an existing store must not silently recreate a deleted file.
            uri = self.path.as_uri() + ("?mode=rwc" if create else "?mode=rw")
            db = sqlite3.connect(uri, uri=True, timeout=5)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            with db:
                if not create:
                    self._check_schema(db)
                yield db
        except sqlite3.Error as exc:
            raise ReviewStoreError("SQLite review operation failed; no successful save is implied") from exc
        finally:
            if db is not None:
                db.close()

    @staticmethod
    def _check_schema(db):
        if (db.execute("PRAGMA user_version").fetchone()[0] != _VERSION
                or db.execute("PRAGMA application_id").fetchone()[0] != _APPLICATION_ID):
            raise ReviewStoreError("Unrecognized review database or unsupported schema version")
        names = {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
        if not {"reviews", "review_scope", "reviews_no_update", "reviews_no_delete"} <= names:
            raise ReviewStoreError("Review database schema is incomplete")

    @staticmethod
    def _decode(row) -> ReviewRecord:
        try:
            record = ReviewRecord.model_validate_json(row["record_json"])
        except ValidationError as exc:
            raise ReviewStoreError("Stored review snapshot failed validation") from exc
        if (record.claim.review_id != row["review_id"]
                or _scope(record.claim) != tuple(row[name] for name in ("insurer", "plan_name", "member_id", "claim_id"))
                or record.previous_review_id != row["previous_review_id"]):
            raise ReviewStoreError("Stored review metadata does not match its snapshot")
        return record

    def save(self, claim: Claim, decision: Decision, *, previous_review_id: str | None = None,
             supplemental_input_json: str | None = None) -> ReviewRecord:
        """Atomically insert a validated snapshot. Existing IDs are never overwritten.

        The caller supplies a decision produced for this claim. This validates
        identity/schema, not independent re-adjudication of that decision.
        A link establishes lineage only; appeal eligibility is a separate rule.
        """
        record = ReviewRecord.model_validate(dict(
            claim=claim.model_dump(), decision=decision.model_dump(),
            recorded_at=datetime.now(timezone.utc), previous_review_id=previous_review_id,
            supplemental_input_json=supplemental_input_json,
        ))
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM reviews WHERE review_id = ?", (record.claim.review_id,)).fetchone():
                raise DuplicateReviewError("Review ID already exists; the original record was retained")
            if record.previous_review_id is not None:
                row = db.execute("SELECT * FROM reviews WHERE review_id = ?", (record.previous_review_id,)).fetchone()
                if row is None:
                    raise ReviewLinkError("The referenced prior review does not exist")
                if _scope(self._decode(row).claim) != _scope(record.claim):
                    raise ReviewLinkError("Prior review must belong to the same claim, member, insurer, and plan")
            db.execute(
                "INSERT INTO reviews (review_id, insurer, plan_name, member_id, claim_id, previous_review_id, record_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (record.claim.review_id, *_scope(record.claim), record.previous_review_id, record.model_dump_json()),
            )
        return record

    def get(self, review_id: str) -> ReviewRecord | None:
        """Read a review by its globally unique ID, returning None when absent."""
        with self._connection() as db:
            row = db.execute("SELECT * FROM reviews WHERE review_id = ?", (review_id,)).fetchone()
            return None if row is None else self._decode(row)

    def history(self, *, insurer: str, plan_name: str, member_id: str, claim_id: str | None = None) -> tuple[ReviewRecord, ...]:
        """Return member/policy history, optionally restricted to a stable claim ID."""
        with self._connection() as db:
            query = "SELECT * FROM reviews WHERE insurer = ? AND plan_name = ? AND member_id = ?"
            parameters = (insurer, plan_name, member_id)
            if claim_id is not None:
                query += " AND claim_id = ?"
                parameters += (claim_id,)
            rows = db.execute(
                query + " ORDER BY rowid", parameters,
            ).fetchall()
            return tuple(self._decode(row) for row in rows)

    def count(self) -> int:
        """Return the total number of saved reviews in the store."""
        with self._connection() as db:
            return db.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]

    def recent(self, limit: int = 30, offset: int = 0) -> tuple[ReviewRecord, ...]:
        """Return saved reviews ordered newest first with optional pagination offset."""
        with self._connection() as db:
            rows = db.execute(
                "SELECT * FROM reviews ORDER BY rowid DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return tuple(self._decode(row) for row in rows)

    def clear(self) -> int:
        """Clear all review records by resetting the store, returning the count of deleted records."""
        deleted_count = 0
        try:
            if self.path.exists():
                try:
                    deleted_count = self.count()
                except Exception:
                    deleted_count = 0
                self.path.unlink()
            for suffix in ("-wal", "-shm", "-journal"):
                sidecar = self.path.with_name(self.path.name + suffix)
                if sidecar.exists():
                    try:
                        sidecar.unlink()
                    except OSError:
                        pass
            self.__init__(self.path)
            return deleted_count
        except OSError as exc:
            raise ReviewStoreError("Failed to clear review history database") from exc


