"""Tenant-grounded advisory agency backed by the configured model gateway."""

from __future__ import annotations

import json

from fastfunnel.domain.models import ModelGateway
from fastfunnel.domain.store import Store, new_id, now_iso


class AgencyService:
    """Persist conversations and plans without bypassing governed write services."""

    def __init__(
        self,
        store: Store,
        model_gateway: ModelGateway | None = None,
    ):
        self.store = store
        self.model_gateway = model_gateway or ModelGateway(store)

    def _workspace_context(self, company_id: str, actor_id: str) -> dict:
        with self.store.connect() as conn:
            company = conn.execute(
                """SELECT companies.* FROM companies
                   JOIN memberships
                     ON memberships.organization_id=companies.organization_id
                   WHERE companies.id=? AND memberships.user_id=?""",
                (company_id, actor_id),
            ).fetchone()
            if not company:
                raise PermissionError("Workspace membership required")
            metric_rows = conn.execute(
                """SELECT metric, ROUND(SUM(value), 2) AS value
                   FROM marketing_facts
                   WHERE company_id=?
                   GROUP BY metric""",
                (company_id,),
            ).fetchall()
            content_rows = conn.execute(
                """SELECT status, COUNT(*) AS count
                   FROM content_items
                   WHERE company_id=?
                   GROUP BY status""",
                (company_id,),
            ).fetchall()
            campaign_rows = conn.execute(
                """SELECT status, COUNT(*) AS count
                   FROM campaigns
                   WHERE company_id=?
                   GROUP BY status""",
                (company_id,),
            ).fetchall()
            pending_actions = conn.execute(
                """SELECT COUNT(*) FROM action_requests
                   WHERE company_id=? AND status='awaiting_approval'""",
                (company_id,),
            ).fetchone()[0]
            latest_sync = conn.execute(
                """SELECT provider, status, rows_written, finished_at
                   FROM sync_runs
                   WHERE company_id=?
                   ORDER BY started_at DESC LIMIT 1""",
                (company_id,),
            ).fetchone()
        return {
            "company": {
                "name": company["name"],
                "domain": company["domain"],
                "timezone": company["timezone"],
                "reporting_currency": company["reporting_currency"],
                "profile": json.loads(company["profile_json"]),
            },
            "metrics": {row["metric"]: row["value"] for row in metric_rows},
            "content": {row["status"]: row["count"] for row in content_rows},
            "campaigns": {row["status"]: row["count"] for row in campaign_rows},
            "pending_external_approvals": pending_actions,
            "latest_sync": dict(latest_sync) if latest_sync else None,
        }

    @staticmethod
    def _system_message(context: dict) -> str:
        return (
            "You are FastFunnel's marketing operations copilot. Work only on content "
            "creation, social publishing preparation, paid-media analysis, funnel "
            "analysis, and KPI measurement. Use the workspace facts below and clearly "
            "label any inference. Never claim that you published content, changed spend, "
            "or mutated an external provider. External writes must be proposed through "
            "FastFunnel's approval and idempotent action workflow. Do not request or "
            "repeat API keys. Give concise, specific, executable advice.\n\n"
            f"Workspace facts:\n{json.dumps(context, sort_keys=True)}"
        )

    def history(
        self,
        *,
        company_id: str,
        actor_id: str,
        limit: int = 20,
    ) -> list[dict]:
        self._workspace_context(company_id, actor_id)
        with self.store.connect() as conn:
            rows = conn.execute(
                """SELECT role, content, created_at
                   FROM agency_messages
                   WHERE company_id=? AND user_id=?
                   ORDER BY created_at DESC LIMIT ?""",
                (company_id, actor_id, max(1, min(int(limit), 100))),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def runs(
        self,
        *,
        company_id: str,
        actor_id: str,
        limit: int = 5,
    ) -> list[dict]:
        self._workspace_context(company_id, actor_id)
        with self.store.connect() as conn:
            rows = conn.execute(
                """SELECT id, goal, status, result, created_at
                   FROM agency_runs
                   WHERE company_id=?
                   ORDER BY created_at DESC LIMIT ?""",
                (company_id, max(1, min(int(limit), 20))),
            ).fetchall()
        return [dict(row) for row in rows]

    def chat(self, *, company_id: str, actor_id: str, message: str) -> str:
        message = message.strip()
        if not 2 <= len(message) <= 4000:
            raise ValueError("Message must contain 2 to 4,000 characters")
        context = self._workspace_context(company_id, actor_id)
        history = self.history(company_id=company_id, actor_id=actor_id, limit=10)
        messages = [("system", self._system_message(context))]
        messages.extend((item["role"], item["content"]) for item in history)
        messages.append(("human", message))
        response = self.model_gateway.invoke(company_id=company_id, messages=messages)
        if not response:
            raise RuntimeError("The configured model returned an empty response")

        created = now_iso()
        with self.store.connect() as conn:
            company = conn.execute(
                "SELECT organization_id FROM companies WHERE id=?", (company_id,)
            ).fetchone()
            conn.execute(
                """INSERT INTO agency_messages
                   (id, company_id, user_id, role, content, created_at)
                   VALUES (?, ?, ?, 'human', ?, ?)""",
                (new_id("msg"), company_id, actor_id, message, created),
            )
            assistant_id = new_id("msg")
            conn.execute(
                """INSERT INTO agency_messages
                   (id, company_id, user_id, role, content, created_at)
                   VALUES (?, ?, ?, 'assistant', ?, ?)""",
                (assistant_id, company_id, actor_id, response, now_iso()),
            )
            Store._audit(
                conn,
                company["organization_id"],
                company_id,
                actor_id,
                "agency.responded",
                "agency_message",
                assistant_id,
                {"input_characters": len(message), "output_characters": len(response)},
            )
        return response

    def create_plan(self, *, company_id: str, actor_id: str, goal: str) -> str:
        goal = goal.strip()
        if not 5 <= len(goal) <= 1000:
            raise ValueError("Goal must contain 5 to 1,000 characters")
        context = self._workspace_context(company_id, actor_id)
        prompt = (
            f"Create a practical 30-day marketing operations plan for this goal: {goal}\n"
            "Return five short sections: Outcome, Evidence, Content, Distribution, "
            "Measurement. Include weekly actions, owners as roles rather than invented "
            "people, and measurable thresholds. Mark every external write as requiring "
            "the governed approval workflow."
        )
        result = self.model_gateway.invoke(
            company_id=company_id,
            messages=[
                ("system", self._system_message(context)),
                ("human", prompt),
            ],
        )
        if not result:
            raise RuntimeError("The configured model returned an empty response")
        run_id = new_id("run")
        with self.store.connect() as conn:
            company = conn.execute(
                "SELECT organization_id FROM companies WHERE id=?", (company_id,)
            ).fetchone()
            conn.execute(
                """INSERT INTO agency_runs
                   (id, company_id, actor_id, goal, status, result, created_at)
                   VALUES (?, ?, ?, ?, 'ready', ?, ?)""",
                (run_id, company_id, actor_id, goal, result, now_iso()),
            )
            Store._audit(
                conn,
                company["organization_id"],
                company_id,
                actor_id,
                "agency.plan.created",
                "agency_run",
                run_id,
                {"goal_characters": len(goal), "external_writes": 0},
            )
        return run_id
