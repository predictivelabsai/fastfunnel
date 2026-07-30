"""Skill-grounded content drafting without direct publication side effects."""

from __future__ import annotations

from fastfunnel.domain.models import ModelGateway
from fastfunnel.domain.store import Store
from fastfunnel.skills import effective_instructions, skill_for_company


class ContentService:
    def __init__(self, store: Store, model_gateway: ModelGateway | None = None):
        self.store = store
        self.model_gateway = model_gateway or ModelGateway(store)

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
        prompt = effective_instructions(skill, context)
        title = f"{channel.title()} · {goal.strip()[:90]}"
        body = self.model_gateway.invoke(
            company_id=company_id,
            messages=(
                (
                    "system",
                    (
                        f"{prompt}\n\n"
                        "Draft one publication-ready social post. Return only the post body; "
                        "do not add analysis, labels, or markdown fences."
                    ),
                ),
                (
                    "human",
                    f"Create a {channel} post for this goal: {goal.strip()}",
                ),
            ),
        )
        if not body:
            raise RuntimeError("The configured model returned an empty draft")
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
