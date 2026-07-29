"""Skill-grounded content drafting without direct publication side effects."""

from __future__ import annotations

from fastfunnel.domain.store import Store
from fastfunnel.skills import effective_instructions, skill_for_company


class ContentService:
    def __init__(self, store: Store):
        self.store = store

    def create_draft(
        self,
        *,
        company_id: str,
        actor_id: str,
        goal: str,
        channel: str,
    ) -> str:
        company = self.store.company_for_user(company_id=company_id)
        skill = skill_for_company(self.store, company_id, "social")
        if not skill or not skill.enabled:
            raise RuntimeError("The social skill is disabled for this workspace")
        context = {
            "company": company["name"],
            "domain": company["domain"],
            "channel": channel,
            "goal": goal.strip(),
        }
        # The effective prompt is composed and auditable even when no model key is
        # configured. The deterministic fallback keeps local/self-hosted use useful.
        prompt = effective_instructions(skill, context)
        title = f"{channel.title()} · {goal.strip()[:90]}"
        body = (
            f"{goal.strip()}\n\n"
            f"At {company['name']}, we focus on practical implementation: clear ownership, "
            "measurable outcomes, and systems that teams can inspect and improve.\n\n"
            "What would make this most useful in your organization?"
        )
        item_id = self.store.create_content(
            title,
            body,
            channel,
            company_id=company_id,
            actor_id=actor_id,
        )
        with self.store.connect() as conn:
            organization_id = conn.execute(
                "SELECT organization_id FROM companies WHERE id=?", (company_id,)
            ).fetchone()["organization_id"]
            Store._audit(
                conn,
                organization_id,
                company_id,
                actor_id,
                "content.generated",
                "content",
                item_id,
                {
                    "skill_id": skill.id,
                    "skill_overlay_version": skill.version,
                    "prompt_length": len(prompt),
                    "channel": channel,
                },
            )
        return item_id
