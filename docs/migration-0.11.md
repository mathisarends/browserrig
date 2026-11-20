# Migrate from 0.10.x to 0.11.0

[Migration guides](migrations.md) · [Release notes](../CHANGELOG.md#0110-2026-11-20)

## Upgrade Harnessed

BrowserRig 0.11 pins Harnessed and its provider, MCP and OpenTelemetry extras to
0.23.0. Harnessed 0.23 opens existing 0.22 session stores in place. Conversation
snapshots stay at format 3, checkpoints at format 4, and audit envelopes at version 7.
For stores from earlier releases, follow the
[0.10 migration guide](migration-0.10.md#upgrade-harnessed) first.

In a staged rollout, upgrade checkpoint and audit readers to 0.23 before
upgrading writers. Harnessed 0.22 readers reject compaction events that include
the new `accepted_note_keys` field. BrowserRig's `TaskMemory` now uses native
Harnessed handover notes for compaction with its existing configuration.

See the [Harnessed 0.23.0 release notes](https://github.com/mathisarends/harnessed/releases/tag/v0.23.0).

## Configure input and viewer feedback

Existing `InputPacing` and `Choreography` configurations work as before.
`InputPacing` now lets you supply an independent typing or pointer planner while
the configured motor handles the other input behavior. `Choreography` now lets
you choose which contributions reach browser viewers. See
[input pacing](browser-composition.md#browser-owned-presentation) and
[choreography contributions](browser-choreography.md#select-what-viewers-see).
