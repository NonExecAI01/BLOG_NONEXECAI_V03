# Claude Enterprise — Board Governance Reference

**Last verified:** 2026-07-03 | **Type:** enterprise-agent | **Provider:** Anthropic

## Governance summary

Claude Enterprise is Anthropic's workforce deployment tier for frontier models with centralized identity, configurable retention, and a Compliance API for audit and content retrieval. Boards should treat it as **material third-party AI infrastructure** when adopted at scale, not as individual SaaS experimentation.

## Board oversight questions

- Has management mapped Claude Enterprise to the corporate AI use policy and acceptable-use rules?
- Who owns Compliance API monitoring and escalation to audit/risk?
- How often do we review Anthropic Risk Reports under RSP v3.0 for vendor risk?

## Enterprise controls

SSO, SCIM, role-based permissions, audit logs, Compliance API (`/v1/compliance/*`), configurable retention, no default training on customer data.

## Official documentation

- [Claude Enterprise](https://www.anthropic.com/product/enterprise)
- [Compliance API](https://platform.claude.com/docs/en/manage-claude/compliance-api)
- [Transparency Hub](https://www.anthropic.com/transparency/voluntary-commitments)

## Related pillars

- Agents & models governance
- Third-party AI oversight
- Regulatory watch (EU AI Act deployer duties)
