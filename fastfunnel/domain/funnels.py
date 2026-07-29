"""Configurable cohort funnel calculation and Sankey presentation contract."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FunnelStage:
    name: str
    short_name: str
    dropoff_name: str
    count: int


def clamp_cumulative(values: list[int]) -> list[int]:
    """Return non-negative cumulative counts that can form a conserved flow."""
    clamped = [max(0, int(value)) for value in values]
    for index in range(1, len(clamped)):
        clamped[index] = min(clamped[index], clamped[index - 1])
    return clamped


def sankey_spec(stages: list[FunnelStage]) -> dict:
    """Build a conserved progression/drop-off graph independent of the renderer."""
    if len(stages) < 2:
        raise ValueError("A funnel requires at least two stages")
    values = clamp_cumulative([stage.count for stage in stages])
    stage_count = len(stages)
    drops = [values[index] - values[index + 1] for index in range(stage_count - 1)]
    stage_x = [index / (stage_count - 1) * 0.82 for index in range(stage_count)]
    drop_x = [stage_x[index] + 0.12 for index in range(stage_count - 1)]

    labels = [
        f"{stage.short_name}<br>{values[index]:,}" for index, stage in enumerate(stages)
    ]
    labels.extend(
        f"{stages[index].dropoff_name}<br>{drops[index]:,}"
        for index in range(stage_count - 1)
        if drops[index]
    )
    connected_drops = [index for index, value in enumerate(drops) if value]
    drop_node = {
        stage_index: stage_count + offset
        for offset, stage_index in enumerate(connected_drops)
    }
    terminal_index = len(labels)
    if sum(drops):
        labels.append(f"Did not convert<br>{sum(drops):,}")

    sources: list[int] = []
    targets: list[int] = []
    link_values: list[int] = []
    details: list[str] = []
    colors: list[str] = []
    for index in range(stage_count - 1):
        progressed = values[index + 1]
        dropped = drops[index]
        rate = progressed / values[index] * 100 if values[index] else 0
        if progressed:
            sources.append(index)
            targets.append(index + 1)
            link_values.append(progressed)
            details.append(f"Progressed · {rate:.1f}% of {stages[index].name.lower()}")
            colors.append("rgba(37,99,235,0.32)")
        if dropped:
            sources.extend((index, drop_node[index]))
            targets.extend((drop_node[index], terminal_index))
            link_values.extend((dropped, dropped))
            details.extend(
                (
                    f"Drop-off · {100 - rate:.1f}% of {stages[index].name.lower()}",
                    f"Did not progress after {stages[index].name.lower()}",
                )
            )
            colors.extend(("rgba(234,88,12,0.24)", "rgba(234,88,12,0.12)"))

    node_x = stage_x + [drop_x[index] for index in connected_drops]
    drop_y = [0.58, 0.68, 0.77, 0.85, 0.91]
    node_y = [0.10] * stage_count + [drop_y[index] for index in connected_drops]
    node_colors = ["#2563eb"] * (stage_count - 1) + ["#059669"]
    node_colors += ["#ea580c"] * len(connected_drops)
    if sum(drops):
        node_x.append(0.98)
        node_y.append(0.88)
        node_colors.append("#c2410c")

    return {
        "values": values,
        "step_conversion": [
            None,
            *[
                values[index] / values[index - 1] * 100
                if values[index - 1]
                else None
                for index in range(1, stage_count)
            ],
        ],
        "overall_conversion": [
            value / values[0] * 100 if values[0] else None for value in values
        ],
        "trace": {
            "type": "sankey",
            "arrangement": "fixed",
            "orientation": "h",
            "node": {
                "label": labels,
                "x": node_x,
                "y": node_y,
                "pad": 18,
                "thickness": 18,
                "color": node_colors,
                "line": {"color": "white", "width": 1},
                "hovertemplate": "%{label}<extra></extra>",
            },
            "link": {
                "source": sources,
                "target": targets,
                "value": link_values,
                "color": colors,
                "customdata": details,
                "hovertemplate": (
                    "%{source.label} → %{target.label}<br>%{value:,} people"
                    "<br>%{customdata}<extra></extra>"
                ),
            },
        },
    }
