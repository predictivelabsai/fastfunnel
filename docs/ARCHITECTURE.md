# FastFunnel architecture

## Current vertical slice

FastFunnel currently provides a runnable local cockpit with:

- a Predictive Labs organization/company workspace and approving demo administrator;
- multi-user memberships and persisted email invitations;
- the complete pinned Marketing Skills catalog;
- a registry-driven integration catalog with honest implementation states;
- content creation, review, approval, and bounded scheduling;
- a LangGraph observe → plan → policy-gate agency workflow;
- audit events for seeded workspaces, content transitions, and invitations;
- deterministic demo capture and GIF scripts.

SQLite is the local profile. The schema already carries organization/company
keys, but production tenant isolation, OIDC sessions, Postgres row-level
security, durable jobs, live publication, and paid-media mutations remain future
milestones from the implementation plan.

## Mutation boundary

```text
FastHTML route / LangGraph node
  → domain command
  → tenant + role check
  → autonomy policy
  → exact-payload approval (when required)
  → idempotency lease
  → direct / Composio / Arcade / Buffer adapter
  → receipt + reconciliation
  → audit event
```

No provider write should bypass this boundary.

## Skill boundary

The upstream snapshot under `third_party/marketingskills` is immutable vendor
content. `fastfunnel.skills` discovers it dynamically. Company brand/product
context will be injected as a separate, versioned overlay.
