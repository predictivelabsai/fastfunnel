from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages


class AgencyState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    company_id: str
    goal: str
    observations: list[str]
    proposals: list[dict]
    approved_actions: list[dict]
    status: str


def observe(state: AgencyState) -> dict:
    """Deterministic placeholder for governed data collection."""
    return {
        "observations": [
            "Integration health and campaign data must be fresh before acting.",
            "No external write is permitted without a matching policy decision.",
        ],
        "status": "observed",
    }


def plan(state: AgencyState) -> dict:
    """Produce proposals only; execution is a separate policy-gated workflow."""
    goal = state.get("goal", "Improve qualified invoice-finance leads")
    return {
        "proposals": [
            {
                "type": "content.create",
                "risk": "low",
                "summary": f"Draft a founder-led LinkedIn post supporting: {goal}",
                "requires_approval": False,
            },
            {
                "type": "campaign.budget.change",
                "risk": "high",
                "summary": "Review paid-search pacing; propose a bounded budget adjustment.",
                "requires_approval": True,
            },
        ],
        "status": "awaiting_policy",
    }


def policy_gate(state: AgencyState) -> dict:
    """Allow low-risk drafts; hold publication/spend for admin approval."""
    approved = [
        proposal
        for proposal in state.get("proposals", [])
        if not proposal.get("requires_approval")
    ]
    return {"approved_actions": approved, "status": "bounded"}


def build_agency_graph():
    graph = StateGraph(AgencyState)
    graph.add_node("observe", observe)
    graph.add_node("plan", plan)
    graph.add_node("policy_gate", policy_gate)
    graph.add_edge(START, "observe")
    graph.add_edge("observe", "plan")
    graph.add_edge("plan", "policy_gate")
    graph.add_edge("policy_gate", END)
    return graph.compile()
