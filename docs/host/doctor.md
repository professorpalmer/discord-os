# Host doctor

`discord-os host doctor` checks LaunchAgent / workspace / pid / gateway coherence.

## Notify

`--notify` used to FAIL-post to the host channel (Wave 6 P1b). As of 0.5.87
it only refreshes Need / digest state. It never posts.

```bash
discord-os host doctor --notify           # no Discord post
discord-os host doctor --notify --verbose # still no Discord post
```

It also names the Puppetmaster CLI and version that would cook, and says whether
the [Puppetmaster job inbox](../jobs/pm-inbox.md) is on (`OK pm-inbox off …` or
`OK pm-inbox on channel=… state_dirs=N`). Off is OK — the inbox is opt-in.

Slash/voice **WARN** lines stay on stderr.
See [status](status.md) — liveness Need plus the RO status digest.
