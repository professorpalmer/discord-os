# Host doctor

`discord-os host doctor` checks LaunchAgent / workspace / pid / gateway coherence.

## Notify (Wave 6 P1b)

```bash
discord-os host doctor --notify           # FAIL-only channel post
discord-os host doctor --notify --verbose # FAIL + WARN
```

Slash/voice **WARN** lines stay on stderr — they are not channel-posted.
See [liveness](liveness.md) and [status-digest](status-digest.md).
