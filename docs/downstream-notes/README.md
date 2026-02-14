# Downstream Notes

This folder is for implementation guidance that belongs in downstream plugins
or downstream applications, not in core ACP/core plugin abstractions.

## Purpose

- Capture reusable downstream patterns and decisions.
- Keep core plugin scope clean while documenting extensibility paths.
- Provide implementation-ready notes without forcing immediate core changes.

## File Conventions

- One topic per file.
- Use kebab-case names:
  - `knowledge-pack-bm25.md`
  - `ops-case-routing-policy.md`
  - `billing-rating-overrides.md`
- Keep notes evergreen. If a note is obsolete, mark it `Status: deprecated`.

## Required Sections

Every downstream note should include:

1. `Context`
2. `Decision`
3. `Core vs Downstream Boundary`
4. `Implementation Sketch`
5. `Validation`
6. `Risks / Open Questions`

## Index

- `acp-derivatives-orchestration-matrix.md` - Planning matrix for ACP and
  ACP-derived core plugins, including core vs downstream ownership guidance.
- `audit-notes.md` - Consolidated index for all `audit`-related downstream
  notes.
- `billing-notes.md` - Consolidated index for all `billing`-related downstream
  notes.
- `channel-orchestration-notes.md` - Consolidated index for all
  `channel_orchestration`-related downstream notes.
- `downstream-plugin-authoring-guardrails.md` - Cross-cutting downstream
  guardrails for ACP-based plugin authoring (mixins, typing, partial-index
  migration ownership, formatting, and validation workflow).
- `knowledge-pack-notes.md` - Consolidated index for all
  `knowledge_pack`-related downstream notes.
- `ops-case-notes.md` - Consolidated index for all `ops_case`-related
  downstream notes.
- `ops-governance-notes.md` - Consolidated index for all
  `ops_governance`-related downstream notes.
- `ops-metering-notes.md` - Consolidated index for all `ops_metering`-related
  downstream notes.
- `ops-reporting-notes.md` - Consolidated index for all `ops_reporting`-related
  downstream notes.
- `ops-sla-notes.md` - Consolidated index for all `ops_sla`-related downstream
  notes.
- `ops-vpn-notes.md` - Consolidated index for all `ops_vpn`-related downstream
  notes.
- `ops-workflow-notes.md` - Consolidated index for all
  `ops_workflow`-related downstream notes.

## Template

Copy from `_template.md` when adding new notes.
