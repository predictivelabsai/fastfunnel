from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from fastfunnel.config import ROOT

SKILLS_ROOT = ROOT / "third_party" / "marketingskills" / "skills"


@dataclass(frozen=True)
class Skill:
    id: str
    title: str
    status: str
    path: Path
    summary: str


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


def discover_skills() -> list[Skill]:
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
        status = "stub" if directory.name in SIDE_EFFECT_SKILLS else "prompt-only"
        skills.append(
            Skill(
                id=directory.name,
                title=directory.name.replace("-", " ").title(),
                status=status,
                path=skill_file,
                summary=summary[:240],
            )
        )
    return skills


def upstream() -> dict:
    path = ROOT / "third_party" / "marketingskills" / "UPSTREAM.json"
    return json.loads(path.read_text()) if path.exists() else {}
