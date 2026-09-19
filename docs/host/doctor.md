# Host doctor

`discord-os host doctor` checks LaunchAgent / workspace / pid / gateway coherence.

## Notify

`--notify` used to FAIL-post to the host channel (Wave 6 P1b). As of 0.5.87
it only refreshes Need / digest state. It never posts.

```bash
discord-os host doctor --notify           # no Discord post
discord-os host doctor --notify --verbose # still no Discord post
```

Slash/voice **WARN** lines stay on stderr.
See [liveness](liveness.md) and [status-digest](status-digest.md).
