from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from src.agent.memory_models import (
    MemoryCategory,
    MemoryProposalRecord,
    MemoryRecord,
)


_FORBIDDEN_PATTERNS = (
    re.compile(r"\b(?:password|contraseña|token|jwt|secret|api[_ -]?key)\b", re.I),
    re.compile(r"\b(?:ssn|dni|nif|passport|pasaporte)\b", re.I),
    re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
    re.compile(r"(?:\+?\d[\d ()-]{8,}\d)"),
)
_LOCATION_TERMS = re.compile(
    r"\b(?:direcci[oó]n|domicilio|address|c[oó]digo postal|postal code|"
    r"calle|street|n[uú]mero de puerta|unit number|warehouse aisle|"
    r"pasillo|estanter[ií]a|muelle|loading dock|internal route|ruta interna)\b",
    re.I,
)
_STREET_ADDRESS = re.compile(
    r"\b\d{1,6}\s+[\w.'-]+(?:\s+[\w.'-]+){0,4}\s+"
    r"(?:street|st\.?|road|rd\.?|avenue|ave\.?|calle|avenida|carrera|boulevard|blvd\.?)\b",
    re.I,
)
_INCIDENT_SINGLE_PACKAGE = re.compile(
    r"\b(?:tracking|paquete|parcel|shipment|env[ií]o)\s*(?:#|n[uú]mero|id|code)?\s*[A-Z0-9-]{5,}\b",
    re.I,
)
_CONTRACT_TERMS = re.compile(
    r"\b(?:contrato|negociaci[oó]n|contract|renewal terms|tarifa negociada|"
    r"confidencial|confidential|margen|margin|deal value)\b",
    re.I,
)
_REPEAT_TERMS = re.compile(r"\b(?:recurrente|recurrent|patr[oó]n|pattern|varios tickets|\d+ tickets|repetid[oa])\b", re.I)
_CARRIER_ROUTE_TERMS = re.compile(r"\b(?:carrier|transportista|cobertura|coverage|ruta|route|opera|operar|zona|region)\b", re.I)
_INCIDENT_TERMS = re.compile(r"\b(?:incidencia|incidentes|retrasos|delay|huelga|strike|alerta)\b", re.I)
_B2B_REPORT_TERMS = re.compile(r"\b(?:cliente b2b|cliente|reporte|informe|report|m[eé]tricas|devoluciones|env[ií]os)\b", re.I)
_AUDIT_REDACTIONS = (
    (re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"), "[EMAIL REDACTADO]"),
    (re.compile(r"(?:\+?\d[\d ()-]{8,}\d)"), "[TELÉFONO REDACTADO]"),
    (re.compile(r"(?i)(password|contraseña|token|jwt|secret|api[_ -]?key)\s*[:=]?\s*\S+"), r"\1 [REDACTADO]"),
)


def _database_url() -> str:
    url = os.getenv("SQL_URL", "").strip()
    if not url:
        raise RuntimeError("SQL_URL es obligatorio para la memoria del agente.")
    return url.replace("postgresql+psycopg2://", "postgresql://", 1).replace(
        "postgresql+psycopg://", "postgresql://", 1
    )


def validate_memory_text(
    content: str,
    *,
    category: MemoryCategory | str | None = None,
    repetition_count: int | None = None,
) -> str:
    normalized = " ".join(content.split())
    if not 5 <= len(normalized) <= 500:
        raise ValueError("La memoria debe tener entre 5 y 500 caracteres.")
    if any(pattern.search(normalized) for pattern in _FORBIDDEN_PATTERNS):
        raise ValueError("El contenido incluye información no permitida para memoria.")
    if _LOCATION_TERMS.search(normalized) or _STREET_ADDRESS.search(normalized):
        raise ValueError("No se permite guardar ubicaciones sensibles B2B, B2C o internas.")
    if _CONTRACT_TERMS.search(normalized):
        raise ValueError("No se permite guardar información contractual o comercial negociada.")
    if _INCIDENT_SINGLE_PACKAGE.search(normalized) and not _REPEAT_TERMS.search(normalized):
        raise ValueError("Una incidencia aislada de un paquete no es memorizable.")
    if category is None:
        raise ValueError("La propuesta debe pertenecer a una categoría de memoria TrackFlow.")
    category = MemoryCategory(category)
    if category == MemoryCategory.CARRIER_RULE and not _CARRIER_ROUTE_TERMS.search(normalized):
        raise ValueError("La regla de carrier debe indicar carrier/ruta/cobertura.")
    if category == MemoryCategory.RECURRING_INCIDENT:
        if not _INCIDENT_TERMS.search(normalized):
            raise ValueError("El contexto debe describir una incidencia recurrente.")
        if not _REPEAT_TERMS.search(normalized) and (repetition_count or 0) < 2:
            raise ValueError("Una incidencia requiere evidencia de recurrencia.")
    if category == MemoryCategory.B2B_REPORT_PREFERENCE and not _B2B_REPORT_TERMS.search(normalized):
        raise ValueError("La preferencia debe ser sobre reportes recurrentes B2B.")
    return normalized


def _sanitize_audit_message(message: str) -> str:
    sanitized = message[:1000]
    for pattern, replacement in _AUDIT_REDACTIONS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


class PostgresAgentMemoryStore:
    """Private episodic memory and audit trail; never accesses the RAG store."""

    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    @classmethod
    async def connect(cls) -> "PostgresAgentMemoryStore":
        connection = await AsyncConnection.connect(
            _database_url(), autocommit=True, prepare_threshold=None, row_factory=dict_row
        )
        store = cls(connection)
        await store.setup()
        store._owned_connection = connection
        return store

    async def setup(self) -> None:
        await self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_memory_proposals (
                id UUID PRIMARY KEY,
                user_id TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT,
                memory_key TEXT,
                country TEXT,
                repetition_count INTEGER,
                reason TEXT NOT NULL,
                source_message TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('pending','approved','rejected','discarded','expired')),
                created_at TIMESTAMPTZ NOT NULL,
                resolved_at TIMESTAMPTZ,
                decision TEXT,
                decision_message TEXT,
                edited_content TEXT,
                expires_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        await self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_approved_memories (
                id UUID PRIMARY KEY,
                user_id TEXT NOT NULL,
                proposal_id UUID NOT NULL UNIQUE REFERENCES agent_memory_proposals(id),
                content TEXT NOT NULL,
                category TEXT,
                memory_key TEXT,
                approved_at TIMESTAMPTZ NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        # Additive migration for databases created by the initial preference-only version.
        await self._connection.execute(
            "ALTER TABLE agent_memory_proposals ADD COLUMN IF NOT EXISTS category TEXT"
        )
        await self._connection.execute(
            "ALTER TABLE agent_memory_proposals ADD COLUMN IF NOT EXISTS memory_key TEXT"
        )
        await self._connection.execute(
            "ALTER TABLE agent_memory_proposals ADD COLUMN IF NOT EXISTS country TEXT"
        )
        await self._connection.execute(
            "ALTER TABLE agent_memory_proposals ADD COLUMN IF NOT EXISTS repetition_count INTEGER"
        )
        await self._connection.execute(
            "ALTER TABLE agent_approved_memories ADD COLUMN IF NOT EXISTS category TEXT"
        )
        await self._connection.execute(
            "ALTER TABLE agent_approved_memories ADD COLUMN IF NOT EXISTS memory_key TEXT"
        )
        await self._connection.execute(
            "UPDATE agent_approved_memories SET memory_key='legacy:' || id::text WHERE category IS NULL OR memory_key IS NULL"
        )
        await self._connection.execute(
            "UPDATE agent_memory_proposals SET memory_key='legacy:' || id::text WHERE category IS NULL OR memory_key IS NULL"
        )
        # Legacy preference-only entries are retained for audit but excluded from retrieval.
        await self._connection.execute(
            "UPDATE agent_memory_proposals SET status='discarded', resolved_at=now(), decision='reject', "
            "decision_message='Propuesta antigua retirada durante migración; rechazo por defecto' "
            "WHERE status='pending' AND category IS NULL"
        )
        await self._connection.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS one_pending_agent_memory_per_user
               ON agent_memory_proposals (user_id) WHERE status = 'pending'"""
        )
        await self._connection.execute(
            """CREATE TABLE IF NOT EXISTS agent_memory_decisions (
                id UUID PRIMARY KEY,
                proposal_id UUID NOT NULL REFERENCES agent_memory_proposals(id),
                user_id TEXT NOT NULL,
                outcome TEXT NOT NULL CHECK (outcome IN ('approved','rejected','edited','uncertain','expired')),
                decision_message TEXT NOT NULL,
                decided_at TIMESTAMPTZ NOT NULL
            )"""
        )
        await self._connection.execute(
            """INSERT INTO agent_memory_decisions
               (id,proposal_id,user_id,outcome,decision_message,decided_at)
               SELECT gen_random_uuid(), p.id, p.user_id,
                      CASE WHEN p.decision='approve' OR p.status='approved' THEN 'approved'
                          WHEN p.decision='reject' OR p.status='rejected' THEN 'rejected'
                          WHEN p.status='expired' THEN 'expired'
                           ELSE 'uncertain' END,
                      'Resultado migrado; mensaje original no retenido.',
                      COALESCE(p.resolved_at,p.created_at)
               FROM agent_memory_proposals p
               WHERE p.status <> 'pending'
                 AND NOT EXISTS (SELECT 1 FROM agent_memory_decisions d WHERE d.proposal_id=p.id)"""
        )
        await self._connection.execute("DROP INDEX IF EXISTS one_memory_per_user_key")
        await self._connection.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS one_memory_per_user_memory_key
                ON agent_approved_memories(user_id, memory_key)"""
        )
        await self._connection.execute(
            "CREATE INDEX IF NOT EXISTS agent_memory_user_expiry ON agent_approved_memories(user_id, expires_at)"
        )
        await self.cleanup_expired()

    async def cleanup_expired(self) -> None:
        """Expire pending proposals and memories globally; retain audit rows."""
        now = datetime.now(UTC)
        await self._connection.execute(
                """WITH expired AS (
                      UPDATE agent_memory_proposals SET status='expired', resolved_at=%s,
                      decision='reject', decision_message='Silencio: rechazo por defecto al vencer'
                      WHERE status='pending' AND expires_at <= %s RETURNING id,user_id
                    )
                    INSERT INTO agent_memory_decisions
                    (id,proposal_id,user_id,outcome,decision_message,decided_at)
                    SELECT gen_random_uuid(), id, user_id, 'rejected',
                    'Silencio: rechazo por defecto al vencer', %s FROM expired
                    ON CONFLICT DO NOTHING""",
                (now, now, now),
        )
        await self._connection.execute(
            "DELETE FROM agent_approved_memories WHERE expires_at <= %s", (now,)
        )

    async def expire_stale(self, user_id: str) -> None:
        now = datetime.now(UTC)
        await self._connection.execute(
            """WITH expired AS (
                 UPDATE agent_memory_proposals SET status='expired', resolved_at=%s,
                 decision='reject', decision_message='Silencio: rechazo por defecto al vencer'
                 WHERE user_id=%s AND status='pending' AND expires_at <= %s RETURNING id,user_id
               )
               INSERT INTO agent_memory_decisions
               (id,proposal_id,user_id,outcome,decision_message,decided_at)
               SELECT gen_random_uuid(), id, user_id, 'rejected',
               'Silencio: rechazo por defecto al vencer', %s FROM expired
               ON CONFLICT DO NOTHING""",
            (now, user_id, now, now),
        )
        await self._connection.execute(
            "DELETE FROM agent_approved_memories WHERE user_id=%s AND expires_at <= %s",
            (user_id, now),
        )

    async def pending(self, user_id: str) -> MemoryProposalRecord | None:
        await self.expire_stale(user_id)
        cursor = await self._connection.execute(
            """SELECT id,user_id,content,category,memory_key,repetition_count,source_message,created_at FROM agent_memory_proposals
               WHERE user_id=%s AND status='pending' ORDER BY created_at DESC LIMIT 1""",
            (user_id,),
        )
        row = await cursor.fetchone()
        return MemoryProposalRecord.model_validate(row) if row else None

    async def memories(self, user_id: str) -> list[MemoryRecord]:
        await self.expire_stale(user_id)
        cursor = await self._connection.execute(
                """SELECT id,content,category,memory_key,approved_at,expires_at FROM agent_approved_memories
                    WHERE user_id=%s AND category IS NOT NULL AND expires_at > %s
                    ORDER BY approved_at DESC LIMIT 20""",
            (user_id, datetime.now(UTC)),
        )
        return [MemoryRecord.model_validate(row) async for row in cursor]

    async def propose(
        self,
        user_id: str,
        content: str,
        reason: str,
        source_message: str,
        *,
        category: MemoryCategory | str,
        memory_key: str,
        country: str | None = None,
        repetition_count: int | None = None,
    ) -> UUID:
        safe_content = validate_memory_text(
            content, category=category, repetition_count=repetition_count
        )
        safe_category = MemoryCategory(category)
        safe_key = " ".join(memory_key.split())[:160]
        safe_country = " ".join(country.split())[:40] if country else None
        if (not safe_key or _LOCATION_TERMS.search(safe_key) or _STREET_ADDRESS.search(safe_key)
            or _FORBIDDEN_PATTERNS[2].search(safe_key)
            or _FORBIDDEN_PATTERNS[3].search(safe_key)):
            raise ValueError("La clave no puede contener una ubicación sensible.")
        key_parts = safe_key.casefold().split(":")
        if safe_category == MemoryCategory.CARRIER_RULE:
            key_parts = safe_key.casefold().split(":")
            if len(key_parts) < 4 or key_parts[0] != "carrier" or key_parts[2] != "country" \
                    or not safe_country or key_parts[3].casefold() != safe_country.casefold():
                raise ValueError("La clave de carrier debe consolidar carrier + país (y zona opcional).")
        elif safe_category == MemoryCategory.B2B_REPORT_PREFERENCE and not safe_key.casefold().startswith("b2b_report:"):
            raise ValueError("La clave de preferencia debe estar aislada por cuenta B2B.")
        elif safe_category == MemoryCategory.RECURRING_INCIDENT and not safe_key.casefold().startswith("incident_pattern:"):
            raise ValueError("La clave de incidente debe identificar un patrón recurrente, no un ticket.")
        safe_reason = " ".join(reason.split())[:300]
        if not safe_reason or any(pattern.search(safe_reason) for pattern in _FORBIDDEN_PATTERNS) \
            or _LOCATION_TERMS.search(safe_reason) or _STREET_ADDRESS.search(safe_reason) \
            or _CONTRACT_TERMS.search(safe_reason):
            raise ValueError("Propuesta inválida.")
        proposal_id = uuid4()
        now = datetime.now(UTC)
        try:
            await self._connection.execute(
            """INSERT INTO agent_memory_proposals
                             (id,user_id,content,category,memory_key,country,repetition_count,reason,source_message,status,created_at,expires_at)
                             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s)""",
                (proposal_id, user_id, safe_content, safe_category.value, safe_key,
                         safe_country, repetition_count, safe_reason,
                 "Propuesta originada en interacción autenticada; texto original no retenido.", now,
             now + timedelta(days=int(os.getenv("AGENT_MEMORY_PROPOSAL_TTL_DAYS", "7")))),
            )
        except Exception as error:
            if getattr(error, "sqlstate", None) == "23505":
                raise ValueError("Ya existe una propuesta pendiente.") from error
            raise
        return proposal_id

    async def resolve(
        self,
        proposal: MemoryProposalRecord,
        *,
        decision: str,
        decision_message: str,
        explicit_confirmation: bool = False,
        edited_content: str | None = None,
    ) -> bool:
        now = datetime.now(UTC)
        if decision not in {"approve", "reject", "edit", "uncertain"}:
            decision = "reject"
        if decision == "uncertain":
            decision = "reject"
        if decision == "approve" and (not explicit_confirmation or edited_content is not None):
            decision = "reject"
        approved_content = None
        if decision == "approve":
            approved_content = validate_memory_text(
                proposal.content,
                category=proposal.category,
                repetition_count=proposal.repetition_count,
            )
        status = {
            "approve": "approved",
            "reject": "rejected",
            "edit": "discarded",
            "uncertain": "discarded",
        }.get(decision, "discarded")
        async with self._connection.transaction():
            cursor = await self._connection.execute(
                """UPDATE agent_memory_proposals SET status=%s, resolved_at=%s, decision=%s,
                   decision_message=%s, edited_content=%s WHERE id=%s AND status='pending'""",
                (status, now, decision,
                 "Respuesta clasificada; texto original no retenido.",
                 None, proposal.id),
            )
            if cursor.rowcount != 1:
                return False
            if status == "approved":
                await self._connection.execute(
                          """INSERT INTO agent_approved_memories
                              (id,user_id,proposal_id,content,category,memory_key,approved_at,expires_at)
                              VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                              ON CONFLICT (user_id,memory_key) DO UPDATE SET
                              proposal_id=EXCLUDED.proposal_id, content=EXCLUDED.content,
                              category=EXCLUDED.category, approved_at=EXCLUDED.approved_at,
                              expires_at=EXCLUDED.expires_at""",
                          (uuid4(), proposal.user_id, proposal.id, approved_content,
                            proposal.category.value, proposal.memory_key, now,
                     now + timedelta(days=int(os.getenv("AGENT_MEMORY_TTL_DAYS", "180")))),
                )
                await self._connection.execute(
                    """DELETE FROM agent_approved_memories WHERE user_id=%s AND id NOT IN (
                       SELECT id FROM agent_approved_memories WHERE user_id=%s
                       ORDER BY approved_at DESC LIMIT 20)""",
                    (proposal.user_id, proposal.user_id),
                )
            outcome = {
                "approve": "approved", "reject": "rejected", "edit": "edited"
            }.get(decision, "uncertain")
            await self._connection.execute(
                """INSERT INTO agent_memory_decisions
                   (id,proposal_id,user_id,outcome,decision_message,decided_at)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (uuid4(), proposal.id, proposal.user_id, outcome,
                 "Respuesta clasificada; texto original no retenido.", now),
            )
        return True

    async def aclose(self) -> None:
        connection = getattr(self, "_owned_connection", None)
        if connection is not None:
            await connection.close()