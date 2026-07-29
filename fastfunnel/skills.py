from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from fastfunnel.config import ROOT
from fastfunnel.domain.store import Store, new_id, now_iso

SKILLS_ROOT = ROOT / "third_party" / "marketingskills" / "skills"


@dataclass(frozen=True)
class Skill:
    id: str
    title: str
    status: str
    path: Path
    summary: str
    upstream_text: str = ""
    overlay_instructions: str = ""
    enabled: bool = True
    version: int = 0


SIDE_EFFECT_SKILLS = {
    "directory-submissions",
    "emails",
    "image",
    "influencer-marketing",
    "prospecting",
    "public-relations",
    "sms",
    "social",
    "video",
}


def discover_skills(
    store: Store | None = None, company_id: str | None = None
) -> list[Skill]:
    overlays: dict[str, dict] = {}
    if store and company_id:
        with store.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM skill_overlays WHERE company_id=?", (company_id,)
            ).fetchall()
        overlays = {row["skill_id"]: dict(row) for row in rows}
    skills = []
    if not SKILLS_ROOT.exists():
        return skills
    for directory in sorted(path for path in SKILLS_ROOT.iterdir() if path.is_dir()):
        skill_file = directory / "SKILL.md"
        summary = "Bundled upstream marketing skill."
        if skill_file.exists():
            for line in skill_file.read_text(errors="replace").splitlines():
                if line.startswith("description:"):
                    summary = line.split(":", 1)[1].strip().strip('"')
                    break
        upstream_text = skill_file.read_text(errors="replace") if skill_file.exists() else ""
        overlay = overlays.get(directory.name, {})
        status = "stub" if directory.name in SIDE_EFFECT_SKILLS else "prompt-only"
        if overlay and not overlay["enabled"]:
            status = "disabled"
        elif overlay:
            status = "customized"
        skills.append(
            Skill(
                id=directory.name,
                title=directory.name.replace("-", " ").title(),
                status=status,
                path=skill_file,
                summary=summary[:240],
                upstream_text=upstream_text,
                overlay_instructions=overlay.get("instructions", ""),
                enabled=bool(overlay.get("enabled", 1)),
                version=int(overlay.get("version", 0)),
            )
        )
    return skills


def skill_for_company(store: Store, company_id: str, skill_id: str) -> Skill | None:
    return next(
        (skill for skill in discover_skills(store, company_id) if skill.id == skill_id),
        None,
    )


def save_overlay(
    store: Store,
    company_id: str,
    skill_id: str,
    instructions: str,
    *,
    enabled: bool,
    actor_id: str,
) -> Skill:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", skill_id):
        raise ValueError("Invalid skill id")
    if not (SKILLS_ROOT / skill_id / "SKILL.md").exists():
        raise LookupError("Unknown upstream skill")
    if len(instructions) > 50_000:
        raise ValueError("Overlay instructions are too long")
    timestamp = now_iso()
    with store.connect() as conn:
        conn.execute(
            """INSERT INTO skill_overlays
               (id, company_id, skill_id, enabled, instructions, updated_by,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(company_id, skill_id) DO UPDATE SET
                 enabled=excluded.enabled,
                 instructions=excluded.instructions,
                 version=skill_overlays.version+1,
                 updated_by=excluded.updated_by,
                 updated_at=excluded.updated_at""",
            (
                new_id("sko"),
                company_id,
                skill_id,
                int(enabled),
                instructions.strip(),
                actor_id,
                timestamp,
                timestamp,
            ),
        )
        company = conn.execute("SELECT organization_id FROM companies WHERE id=?", (company_id,)).fetchone()
        Store._audit(
            conn,
            company["organization_id"],
            company_id,
            actor_id,
            "skill.overlay.updated",
            "skill",
            skill_id,
            {"enabled": enabled, "instruction_length": len(instructions)},
        )
    skill = skill_for_company(store, company_id, skill_id)
    if not skill:
        raise LookupError("Skill disappeared after update")
    return skill


def effective_instructions(skill: Skill, context: dict | None = None) -> str:
    """Compose immutable upstream instructions with editable tenant context."""
    context_text = json.dumps(context or {}, sort_keys=True, indent=2)
    overlay = skill.overlay_instructions or "No tenant-specific additions."
    return (
        f"{skill.upstream_text.rstrip()}\n\n"
        "## FastFunnel tenant overlay\n\n"
        f"{overlay}\n\n"
        "## Grounded workspace context\n\n"
        f"```json\n{context_text}\n```\n"
    )


def upstream() -> dict:
    path = ROOT / "third_party" / "marketingskills" / "UPSTREAM.json"
    return json.loads(path.read_text()) if path.exists() else {}
