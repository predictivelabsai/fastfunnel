"""Policy, approval, idempotency, execution, and audit for external mutations."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastfunnel.domain.store import Store, new_id, now_iso
from fastfunnel.domain.workspace import SecretVault
from fastfunnel.integrations.execution import provider_for

WRITE_ACTIONS = {
    "content.publish",
    "conversion.upload",
    "audience.sync",
    "campaign.create",
    "campaign.update",
    "campaign.budget.change",
}
APPROVAL_REQUIRED = WRITE_ACTIONS


class ActionService:
    def __init__(self, store: Store):
        self.store = store

    def propose(
        self,
        *,
        company_id: str,
        actor_id: str,
        action_type: str,
        provider: str,
        object_type: str,
        object_id: str | None,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> dict:
        if action_type not in WRITE_ACTIONS:
            raise ValueError(f"Unknown governed action: {action_type}")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        payload_hash = hashlib.sha256(canonical.encode()).hexdigest()
        request_id = new_id("act")
        timestamp = now_iso()
        approval_id = new_id("apr")
        with self.store.connect() as conn:
            existing = conn.execute(
                """SELECT * FROM action_requests
                   WHERE company_id=? AND idempotency_key=?""",
                (company_id, idempotency_key),
            ).fetchone()
            if existing:
                if existing["payload_hash"] != payload_hash:
                    raise ValueError("Idempotency key was already used with another payload")
                return dict(existing)
            company = conn.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
            membership = conn.execute(
                """SELECT 1 FROM memberships WHERE organization_id=? AND user_id=?""",
                (company["organization_id"], actor_id),
            ).fetchone()
            if not membership:
                raise PermissionError("Actor is not a member of this tenant")
            conn.execute(
                """INSERT INTO approvals
                   (id, company_id, action_type, object_type, object_id, payload_json,
                    payload_hash, status, requested_by, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                (
                    approval_id,
                    company_id,
                    action_type,
                    object_type,
                    object_id or "",
                    canonical,
                    payload_hash,
                    actor_id,
                    timestamp,
                ),
            )
            conn.execute(
                """INSERT INTO action_requests
                   (id, company_id, actor_id, action_type, provider, object_type,
                    object_id, payload_json, payload_hash, idempotency_key, risk,
                    status, approval_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'high', 'awaiting_approval',
                           ?, ?, ?)""",
                (
                    request_id,
                    company_id,
                    actor_id,
                    action_type,
                    provider,
                    object_type,
                    object_id,
                    canonical,
                    payload_hash,
                    idempotency_key,
                    approval_id,
                    timestamp,
                    timestamp,
                ),
            )
            Store._audit(
                conn,
                company["organization_id"],
                company_id,
                actor_id,
                "action.proposed",
                object_type,
                object_id,
                {
                    "action_request_id": request_id,
                    "action_type": action_type,
                    "provider": provider,
                    "payload_hash": payload_hash,
                },
            )
            return dict(
                conn.execute("SELECT * FROM action_requests WHERE id=?", (request_id,)).fetchone()
            )

    def approve(self, request_id: str, *, reviewer_id: str) -> str:
        timestamp = now_iso()
        with self.store.connect() as conn:
            request = conn.execute(
                """SELECT action_requests.*, companies.organization_id
                   FROM action_requests JOIN companies
                     ON companies.id=action_requests.company_id
                   WHERE action_requests.id=?""",
                (request_id,),
            ).fetchone()
            if not request or request["status"] != "awaiting_approval":
                raise LookupError("Action is not awaiting approval")
            membership = conn.execute(
                """SELECT role FROM memberships
                   WHERE organization_id=? AND user_id=?""",
                (request["organization_id"], reviewer_id),
            ).fetchone()
            if not membership or membership["role"] not in {"admin", "reviewer"}:
                raise PermissionError("Reviewer permission required")
            conn.execute(
                """UPDATE approvals SET status='approved', decided_by=?, decided_at=?
                   WHERE id=? AND payload_hash=?""",
                (
                    reviewer_id,
                    timestamp,
                    request["approval_id"],
                    request["payload_hash"],
                ),
            )
            conn.execute(
                """UPDATE action_requests SET status='approved', updated_at=?
                   WHERE id=?""",
                (timestamp, request_id),
            )
            job_id = new_id("job")
            conn.execute(
                """INSERT INTO job_queue
                   (id, company_id, job_type, payload_json, idempotency_key,
                    status, available_at, created_at)
                   VALUES (?, ?, 'action.execute', ?, ?, 'pending', ?, ?)""",
                (
                    job_id,
                    request["company_id"],
                    json.dumps({"action_request_id": request_id}),
                    f"execute:{request['id']}:{request['payload_hash']}",
                    timestamp,
                    timestamp,
                ),
            )
            Store._audit(
                conn,
                request["organization_id"],
                request["company_id"],
                reviewer_id,
                "action.approved",
                request["object_type"],
                request["object_id"],
                {"action_request_id": request_id, "payload_hash": request["payload_hash"]},
            )
        return job_id

    def execute(self, request_id: str) -> dict:
        with self.store.connect() as conn:
            request = conn.execute(
                """SELECT action_requests.*, companies.organization_id
                   FROM action_requests JOIN companies
                     ON companies.id=action_requests.company_id
                   WHERE action_requests.id=?""",
                (request_id,),
            ).fetchone()
            if not request:
                raise LookupError("Unknown action request")
            previous = conn.execute(
                """SELECT * FROM action_executions WHERE action_request_id=?
                   AND status='succeeded'""",
                (request_id,),
            ).fetchone()
            if previous:
                return json.loads(previous["provider_receipt_json"])
            if request["status"] != "approved":
                raise PermissionError("A payload-bound approval is required")
            approval = conn.execute(
                "SELECT * FROM approvals WHERE id=?", (request["approval_id"],)
            ).fetchone()
            if (
                not approval
                or approval["status"] != "approved"
                or approval["payload_hash"] != request["payload_hash"]
            ):
                raise PermissionError("Approval does not match action payload")
            identity = conn.execute(
                """SELECT * FROM provider_identities
                   WHERE company_id=? AND user_id=? AND provider=? AND status='connected'""",
                (request["company_id"], request["actor_id"], request["provider"]),
            ).fetchone()
            if not identity:
                raise RuntimeError(f"No connected {request['provider']} identity")
            attempt = conn.execute(
                "SELECT COUNT(*) FROM action_executions WHERE action_request_id=?",
                (request_id,),
            ).fetchone()[0] + 1
            execution_id = new_id("exe")
            conn.execute(
                """INSERT INTO action_executions
                   (id, action_request_id, provider, status, attempt, started_at)
                   VALUES (?, ?, ?, 'running', ?, ?)""",
                (execution_id, request_id, request["provider"], attempt, now_iso()),
            )
        try:
            payload = json.loads(request["payload_json"])
            tool = payload.pop("tool")
            api_key = SecretVault(self.store).provider_key(
                request["company_id"], request["provider"]
            )
            result = provider_for(request["provider"], api_key=api_key).execute(
                external_user_id=identity["external_user_id"],
                connected_account_id=identity["connected_account_id"],
                tool=tool,
                arguments=payload,
            )
            receipt = result.receipt
            with self.store.connect() as conn:
                conn.execute(
                    """UPDATE action_executions SET status='succeeded',
                       provider_receipt_json=?, finished_at=? WHERE id=?""",
                    (json.dumps(receipt), now_iso(), execution_id),
                )
                conn.execute(
                    """UPDATE action_requests SET status='succeeded', updated_at=?
                       WHERE id=?""",
                    (now_iso(), request_id),
                )
                if request["object_type"] == "content" and request["object_id"]:
                    conn.execute(
                        """UPDATE content_items SET status='published', updated_at=?
                           WHERE id=? AND company_id=?""",
                        (now_iso(), request["object_id"], request["company_id"]),
                    )
                Store._audit(
                    conn,
                    request["organization_id"],
                    request["company_id"],
                    request["actor_id"],
                    "action.executed",
                    request["object_type"],
                    request["object_id"],
                    {"action_request_id": request_id, "provider": request["provider"]},
                )
            return receipt
        except Exception as exc:
            with self.store.connect() as conn:
                conn.execute(
                    """UPDATE action_executions SET status='failed', error=?, finished_at=?
                       WHERE id=?""",
                    (str(exc), now_iso(), execution_id),
                )
                conn.execute(
                    """UPDATE action_requests SET status='failed', updated_at=?
                       WHERE id=?""",
                    (now_iso(), request_id),
                )
            raise
