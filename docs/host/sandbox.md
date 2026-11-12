# Worker sandbox

The gate hook decides which tool calls a worker may run. The sandbox limits
what the worker process can touch after that. Every child process (the shell
tool, git, python) inherits it.

On macOS, Discord OS starts each local agentic worker under
`/usr/bin/sandbox-exec` with a profile built for that job. It is on by default.

| The worker can | The worker cannot |
|---|---|
| Read the system, your repos, and its own checkout | Read the contents of `~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.netrc`, `~/.config/gh`, shell rc files, keychains, or `~/.pmharness/state` |
| Write in its checkout, temp, and tool caches | Read or write the Discord OS workspace (`.env`, the SQLite store, the key vault) |
| Write its own Puppetmaster state and its own gate folder | Write anywhere else in your home, or in `.git/hooks` of its checkout |
| Use the network (it needs its model provider) | |

A denied read or write fails with `Operation not permitted`. The job keeps
running and the worker sees the error.

## Settings

| Setting | Effect |
|---|---|
| `DISCORD_OS_SANDBOX=0` | Turn the sandbox off. Workers then run as you, and the gate hook is the only limit. |
| `DISCORD_OS_SANDBOX_DENY_READ=/path/a,/path/b` | Hide more paths from workers. |

`discord-os host doctor` reports the sandbox state.

## Limits

- macOS only. On Linux, workers run without a sandbox, and `doctor` says so.
- The sandbox covers local agentic workers. A cook on an SSH host runs under
  that host's own controls.
- A worker can see that a hidden file exists (`stat`), but not its contents.
  SQLite needs `stat` on every parent folder of the Puppetmaster store.
