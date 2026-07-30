"""Versioned business models and cohort-safe event analytics."""

from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from fastfunnel.domain.funnels import FunnelStage, sankey_spec
from fastfunnel.domain.store import Store, new_id, now_iso

BUSINESS_PACKS: dict[str, dict[str, Any]] = {
    "mmg": {
        "organization_id": "org_mmg",
        "company_id": "co_mmg",
        "organization": "My Medical Gateway",
        "company": "MMG Hospital Lead Generation",
        "domain": "mymedicalgateway.com",
        "model_key": "mmg_hospital_lead_gen",
        "description": "Hospital lead acquisition and patient lifecycle.",
        "events": (
            ("sign_in", "Signed in", "Sign in", "No downstream journey"),
            ("journey_started", "Journey started", "Journey", "Did not view a package"),
            ("package_viewed", "Package viewed", "Package", "Did not request a quote"),
            ("quote_requested", "Quote requested", "Quote", "No deposit"),
            ("deposit_paid", "Deposit paid", "Deposit", "Diagnostics pending"),
            ("diagnostics_approved", "Diagnostics approved", "Diagnostics", "Balance unpaid"),
            ("balance_paid", "Balance paid", "Balance", "Treatment pending"),
            ("treatment_completed", "Treatment completed", "Complete", "Not completed"),
        ),
        "probabilities": (1.0, 0.82, 0.67, 0.39, 0.20, 0.14, 0.09, 0.06),
        "currency": "GBP",
    },
    "fastoffice": {
        "organization_id": "org_fastoffice",
        "company_id": "co_fastoffice",
        "organization": "FastOffice",
        "company": "FastOffice Suite Growth",
        "domain": "office.fastsme.com",
        "model_key": "fastoffice_growth",
        "description": "Suite sign-in, product adoption and subscription growth.",
        "events": (
            ("sign_in", "Signed in", "Sign in", "No product opened"),
            ("product_opened", "Product opened", "Product", "No artifact created"),
            ("artifact_created", "Artifact created", "Activated", "No checkout"),
            ("checkout_started", "Checkout started", "Checkout", "No subscription"),
            ("subscription_active", "Subscription active", "Subscribed", "No payment"),
            ("payment_succeeded", "Payment succeeded", "Paid", "No renewal"),
            ("subscription_renewed", "Subscription renewed", "Renewed", "Not renewed"),
        ),
        "probabilities": (1.0, 0.78, 0.52, 0.19, 0.13, 0.12, 0.08),
        "currency": "GBP",
    },
    "tendly": {
        "organization_id": "org_tendly",
        "company_id": "co_tendly",
        "organization": "Tendly",
        "company": "Tendly GTM",
        "domain": "tendly.eu",
        "model_key": "tendly_gtm",
        "description": "Tender intelligence acquisition, activation and revenue.",
        "events": (
            ("sign_in", "Signed in", "Sign in", "No profile completion"),
            ("profile_completed", "Profile completed", "Profile", "No tender search"),
            ("tender_searched", "Tender searched", "Search", "No tender saved"),
            ("tender_saved", "Tender or alert saved", "Saved", "No checkout"),
            ("checkout_started", "Checkout started", "Checkout", "No subscription"),
            ("subscription_active", "Subscription active", "Subscribed", "No payment"),
            ("payment_succeeded", "Payment succeeded", "Paid", "No renewal"),
            ("subscription_renewed", "Subscription renewed", "Renewed", "Not renewed"),
        ),
        "probabilities": (1.0, 0.76, 0.61, 0.38, 0.17, 0.13, 0.12, 0.08),
        "currency": "EUR",
    },
}

CITY_FIXTURES = (
    ("GB", "England", "London", "SW1", 51.5072, -0.1276),
    ("GB", "England", "Manchester", "M1", 53.4808, -2.2426),
    ("GB", "Scotland", "Edinburgh", "EH1", 55.9533, -3.1883),
    ("EE", "Harju", "Tallinn", "101", 59.4370, 24.7536),
    ("FI", "Uusimaa", "Helsinki", "001", 60.1699, 24.9384),
    ("PL", "Mazowieckie", "Warsaw", "00", 52.2297, 21.0122),
)


class SemanticModelService:
    def __init__(self, store: Store):
        self.store = store

    def seed_business_organizations(self, admin_email: str) -> list[str]:
        """Create three isolated organisations for the configured platform admin."""
        user = self.store.user_for_email(admin_email)
        created = now_iso()
        company_ids: list[str] = []
        with self.store.connect() as conn:
            for pack_key, pack in BUSINESS_PACKS.items():
                conn.execute(
                    """INSERT OR IGNORE INTO organizations
                       (id, name, slug, created_at) VALUES (?, ?, ?, ?)""",
                    (
                        pack["organization_id"],
                        pack["organization"],
                        pack_key,
                        created,
                    ),
                )
                profile = {
                    "website": f"https://{pack['domain']}",
                    "business_pack": pack_key,
                    "approval_policy": "bounded_autonomy_admin_approval",
                }
                conn.execute(
                    """INSERT OR IGNORE INTO companies
                       (id, organization_id, name, domain, profile_json, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        pack["company_id"],
                        pack["organization_id"],
                        pack["company"],
                        pack["domain"],
                        json.dumps(profile),
                        created,
                    ),
                )
                conn.execute(
                    """INSERT OR IGNORE INTO memberships
                       (organization_id, user_id, role) VALUES (?, ?, 'admin')""",
                    (pack["organization_id"], user["id"]),
                )
                conn.execute(
                    """INSERT OR IGNORE INTO workspace_memberships
                       (company_id, user_id, role, created_at)
                       VALUES (?, ?, 'admin', ?)""",
                    (pack["company_id"], user["id"], created),
                )
                company_ids.append(pack["company_id"])
        for pack_key, pack in BUSINESS_PACKS.items():
            self.seed_business_pack(pack_key, pack, user["id"])
        return company_ids

    def seed_business_pack(self, pack_key: str, pack: dict[str, Any], actor_id: str) -> None:
        timestamp = now_iso()
        model_id = f"sem_{pack_key}_v1"
        funnel_id = f"fnl_{pack_key}_growth"
        dashboard_id = f"dsh_{pack_key}_overview"
        with self.store.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO semantic_models
                   (id, company_id, model_key, name, description, version,
                    status, definition_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 1, 'active', ?, ?, ?)""",
                (
                    model_id,
                    pack["company_id"],
                    pack["model_key"],
                    pack["company"],
                    pack["description"],
                    json.dumps(
                        {
                            "activation_event": "sign_in",
                            "attribution": {
                                "default": "first_touch",
                                "available": ["first_touch", "last_non_direct"],
                            },
                            "privacy": {"minimum_geo_cohort": 10, "pii": "hmac_only"},
                        }
                    ),
                    timestamp,
                    timestamp,
                ),
            )
            conn.execute(
                "UPDATE funnel_definitions SET is_default=0 WHERE company_id=?",
                (pack["company_id"],),
            )
            conn.execute(
                """INSERT OR IGNORE INTO funnel_definitions
                   (id, company_id, name, slug, description, is_default,
                    observation_window_days, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 1, 30, ?, ?)""",
                (
                    funnel_id,
                    pack["company_id"],
                    f"{pack['company']} lifecycle",
                    f"{pack_key}-lifecycle",
                    pack["description"],
                    timestamp,
                    timestamp,
                ),
            )
            for position, (event_name, name, short_name, dropoff) in enumerate(
                pack["events"]
            ):
                conn.execute(
                    """INSERT OR IGNORE INTO funnel_stages
                       (id, funnel_id, position, name, short_name, dropoff_name,
                        predicate_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        f"fst_{pack_key}_{position}",
                        funnel_id,
                        position,
                        name,
                        short_name,
                        dropoff,
                        json.dumps(
                            {
                                "event_name": event_name,
                                "subject_type": "account",
                                "ordered": True,
                            }
                        ),
                    ),
                )
            conn.execute(
                """INSERT OR IGNORE INTO dashboard_definitions
                   (id, company_id, semantic_model_id, slug, name, description,
                    definition_json, is_default, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                (
                    dashboard_id,
                    pack["company_id"],
                    model_id,
                    "growth-overview",
                    f"{pack['company']} overview",
                    "Acquisition, activation, downstream events and geography.",
                    json.dumps(
                        {
                            "widgets": [
                                {"type": "kpi", "metric": "sign_in"},
                                {"type": "kpi", "metric": "sessions"},
                                {"type": "stacked_bar", "metric": "sessions", "dimension": "channel"},
                                {"type": "sankey", "funnel": f"{pack_key}-lifecycle"},
                                {"type": "geo_bubble", "metric": "sign_in", "minimum_cohort": 10},
                            ]
                        }
                    ),
                    timestamp,
                    timestamp,
                ),
            )
        self._seed_synthetic(pack_key, pack, model_id)

    def _seed_synthetic(self, pack_key: str, pack: dict[str, Any], model_id: str) -> None:
        rng = random.Random(f"fastfunnel:{pack_key}:v1")
        now = datetime.now(UTC)
        with self.store.connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM event_facts WHERE company_id=? LIMIT 1",
                (pack["company_id"],),
            ).fetchone()
            if existing:
                return
            for index in range(420):
                subject = self.subject_key(pack["company_id"], f"synthetic-{index}")
                first = now - timedelta(days=index % 30, hours=index % 19)
                country, region, city, postal, latitude, longitude = CITY_FIXTURES[
                    index % len(CITY_FIXTURES)
                ]
                draw = rng.random()
                first_channel = ("Paid Search", "Organic Search", "Direct")[index % 3]
                for stage, ((event_name, *_labels), probability) in enumerate(
                    zip(pack["events"], pack["probabilities"], strict=True)
                ):
                    if draw > probability:
                        break
                    occurred = first + timedelta(hours=stage * (6 + index % 7))
                    channel = (
                        first_channel
                        if stage == 0
                        else "Organic Search"
                        if first_channel == "Direct" and stage == 1
                        else "Direct"
                    )
                    conn.execute(
                        """INSERT INTO event_facts
                           (id, company_id, semantic_model_id, source,
                            external_event_id, subject_type, subject_key, event_name,
                            occurred_at, channel, value, currency, country_code,
                            region, city, postal_area, latitude, longitude,
                            properties_json, ingested_at)
                           VALUES (?, ?, ?, 'synthetic', ?, 'account', ?, ?, ?, ?, ?,
                                   ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            new_id("evt"),
                            pack["company_id"],
                            model_id,
                            f"{pack_key}-{index}-{stage}",
                            subject,
                            event_name,
                            occurred.isoformat(),
                            channel,
                            29.0 if event_name == "payment_succeeded" else None,
                            pack["currency"],
                            country,
                            region,
                            city,
                            postal,
                            latitude,
                            longitude,
                            json.dumps(
                                {
                                    "synthetic": True,
                                    "pack": pack_key,
                                    "age_band": ("18-34", "35-54", "55+")[index % 3],
                                    "gender": ("female", "male", "unknown")[index % 3],
                                }
                            ),
                            now_iso(),
                        ),
                    )
            for day in range(30):
                metric_date = (now.date() - timedelta(days=day)).isoformat()
                for metric_name, base in (
                    ("impressions", 5100),
                    ("clicks", 330),
                    ("sessions", 270),
                    ("spend", 420),
                ):
                    for channel_index, channel in enumerate(
                        ("Paid Search", "Organic Search", "Direct")
                    ):
                        conn.execute(
                            """INSERT INTO metric_facts_v2
                               (id, company_id, semantic_model_id, source, metric_date,
                                metric_name, value, currency, channel, dimensions_json,
                                ingested_at)
                               VALUES (?, ?, ?, 'synthetic', ?, ?, ?, ?, ?, '{}', ?)""",
                            (
                                new_id("mtr"),
                                pack["company_id"],
                                model_id,
                                metric_date,
                                metric_name,
                                round(base * (1 + (day % 5) / 10) / (channel_index + 1), 2),
                                pack["currency"] if metric_name == "spend" else "",
                                channel,
                                now_iso(),
                            ),
                        )

    @staticmethod
    def subject_key(company_id: str, source_identifier: str) -> str:
        return hashlib.sha256(f"{company_id}:{source_identifier}".encode()).hexdigest()

    def cohort_funnel(
        self,
        *,
        company_id: str,
        funnel_id: str | None = None,
        days: int = 30,
    ) -> dict[str, Any]:
        days = min(max(int(days), 1), 365)
        with self.store.connect() as conn:
            funnel = (
                conn.execute(
                    "SELECT * FROM funnel_definitions WHERE id=? AND company_id=?",
                    (funnel_id, company_id),
                ).fetchone()
                if funnel_id
                else conn.execute(
                    """SELECT * FROM funnel_definitions WHERE company_id=?
                       ORDER BY is_default DESC, created_at LIMIT 1""",
                    (company_id,),
                ).fetchone()
            )
            if not funnel:
                raise LookupError("No funnel exists for this workspace")
            rows = conn.execute(
                "SELECT * FROM funnel_stages WHERE funnel_id=? ORDER BY position",
                (funnel["id"],),
            ).fetchall()
            predicates = [json.loads(row["predicate_json"]) for row in rows]
            if not predicates or not all("event_name" in item for item in predicates):
                raise ValueError("Funnel does not use semantic event predicates")
            since = (datetime.now(UTC) - timedelta(days=days)).isoformat()
            events = conn.execute(
                """SELECT subject_key, event_name, occurred_at FROM event_facts
                   WHERE company_id=? AND occurred_at>=?
                   ORDER BY subject_key, occurred_at""",
                (company_id, since),
            ).fetchall()
        by_subject: dict[str, list[tuple[str, datetime]]] = defaultdict(list)
        for event in events:
            by_subject[event["subject_key"]].append(
                (event["event_name"], datetime.fromisoformat(event["occurred_at"]))
            )
        counts = [0] * len(rows)
        window = timedelta(days=int(funnel["observation_window_days"]))
        for subject_events in by_subject.values():
            previous: datetime | None = None
            cohort_start: datetime | None = None
            for position, predicate in enumerate(predicates):
                matched = next(
                    (
                        occurred
                        for name, occurred in subject_events
                        if name == predicate["event_name"]
                        and (previous is None or occurred >= previous)
                        and (cohort_start is None or occurred <= cohort_start + window)
                    ),
                    None,
                )
                if not matched:
                    break
                cohort_start = cohort_start or matched
                previous = matched
                counts[position] += 1
        stages = [
            FunnelStage(row["name"], row["short_name"], row["dropoff_name"], counts[index])
            for index, row in enumerate(rows)
        ]
        result = sankey_spec(stages)
        result.update(
            {
                "definition": dict(funnel),
                "stages": stages,
                "days": days,
                "since": since,
                "calculation": "ordered_distinct_subject_cohort",
            }
        )
        return result

    def geography(
        self,
        *,
        company_id: str,
        days: int = 30,
        minimum_cohort: int = 10,
    ) -> list[dict[str, Any]]:
        since = (datetime.now(UTC) - timedelta(days=max(1, days))).isoformat()
        minimum_cohort = max(10, int(minimum_cohort))
        with self.store.connect() as conn:
            rows = conn.execute(
                """SELECT country_code, region, city, postal_area,
                          AVG(latitude) latitude, AVG(longitude) longitude,
                          COUNT(DISTINCT subject_key) people
                   FROM event_facts
                   WHERE company_id=? AND event_name='sign_in' AND occurred_at>=?
                   GROUP BY country_code, region, city, postal_area
                   HAVING COUNT(DISTINCT subject_key)>=?
                   ORDER BY people DESC""",
                (company_id, since, minimum_cohort),
            ).fetchall()
        return [dict(row) for row in rows]

    def attribution(self, *, company_id: str, days: int = 30) -> dict[str, Any]:
        """Attribute converted subjects by first touch and last non-direct touch."""
        since = (datetime.now(UTC) - timedelta(days=max(1, days))).isoformat()
        with self.store.connect() as conn:
            final_stage = conn.execute(
                """SELECT funnel_stages.predicate_json
                   FROM funnel_definitions
                   JOIN funnel_stages
                     ON funnel_stages.funnel_id=funnel_definitions.id
                   WHERE funnel_definitions.company_id=?
                   ORDER BY funnel_definitions.is_default DESC,
                            funnel_definitions.created_at,
                            funnel_stages.position DESC
                   LIMIT 1""",
                (company_id,),
            ).fetchone()
            if not final_stage:
                return {
                    "default_model": "first_touch",
                    "comparison_model": "last_non_direct",
                    "conversion_event": "",
                    "channels": [],
                }
            conversion_event = json.loads(final_stage["predicate_json"]).get(
                "event_name"
            )
            if not conversion_event:
                return {
                    "default_model": "first_touch",
                    "comparison_model": "last_non_direct",
                    "conversion_event": "",
                    "channels": [],
                }
            rows = conn.execute(
                """SELECT subject_key, event_name, occurred_at, channel
                   FROM event_facts
                   WHERE company_id=? AND occurred_at>=?
                   ORDER BY subject_key, occurred_at""",
                (company_id, since),
            ).fetchall()
        by_subject: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_subject[row["subject_key"]].append(dict(row))
        first_touch: dict[str, int] = defaultdict(int)
        last_non_direct: dict[str, int] = defaultdict(int)
        for events in by_subject.values():
            conversion = next(
                (event for event in events if event["event_name"] == conversion_event),
                None,
            )
            if not conversion:
                continue
            touches = [
                event["channel"].strip() or "Unattributed"
                for event in events
                if event["occurred_at"] <= conversion["occurred_at"]
            ]
            if not touches:
                touches = ["Unattributed"]
            first_touch[touches[0]] += 1
            non_direct = [
                channel for channel in touches if channel.lower() != "direct"
            ]
            last_non_direct[(non_direct or touches)[-1]] += 1
        channels = sorted(set(first_touch) | set(last_non_direct))
        return {
            "default_model": "first_touch",
            "comparison_model": "last_non_direct",
            "conversion_event": conversion_event,
            "channels": [
                {
                    "channel": channel,
                    "first_touch": first_touch[channel],
                    "last_non_direct": last_non_direct[channel],
                }
                for channel in channels
            ],
        }

    def overview(self, *, company_id: str, days: int = 30) -> dict[str, Any]:
        since_date = (datetime.now(UTC).date() - timedelta(days=max(1, days))).isoformat()
        since_time = f"{since_date}T00:00:00+00:00"
        with self.store.connect() as conn:
            event_rows = conn.execute(
                """SELECT event_name, COUNT(DISTINCT subject_key) people
                   FROM event_facts WHERE company_id=? AND occurred_at>=?
                   GROUP BY event_name""",
                (company_id, since_time),
            ).fetchall()
            series_rows = conn.execute(
                """SELECT metric_date, channel, SUM(value) value
                   FROM metric_facts_v2
                   WHERE company_id=? AND metric_name='sessions' AND metric_date>=?
                   GROUP BY metric_date, channel ORDER BY metric_date""",
                (company_id, since_date),
            ).fetchall()
            metric_rows = conn.execute(
                """SELECT metric_name, SUM(value) value
                   FROM metric_facts_v2
                   WHERE company_id=? AND metric_date>=?
                   GROUP BY metric_name""",
                (company_id, since_date),
            ).fetchall()
            demographic_rows = conn.execute(
                """SELECT properties_json FROM event_facts
                   WHERE company_id=? AND event_name='sign_in' AND occurred_at>=?""",
                (company_id, since_time),
            ).fetchall()
        demographics: dict[str, dict[str, int]] = {
            "age_band": defaultdict(int),
            "gender": defaultdict(int),
        }
        for row in demographic_rows:
            properties = json.loads(row["properties_json"])
            for dimension, values in demographics.items():
                value = str(properties.get(dimension) or "unknown")
                values[value] += 1
        return {
            "events": {row["event_name"]: int(row["people"]) for row in event_rows},
            "metrics": {row["metric_name"]: float(row["value"]) for row in metric_rows},
            "series": [dict(row) for row in series_rows],
            "geography": self.geography(company_id=company_id, days=days),
            "attribution": self.attribution(company_id=company_id, days=days),
            "demographics": {
                key: dict(values) for key, values in demographics.items()
            },
        }
