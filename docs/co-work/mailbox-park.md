# External agent mailbox — PARKED

External agent mailbox does **not** ship. Thin map onto existing job threads
was considered for Wave 2; **park wins** — use JobPool threads +
`handoff`/`peer` instead of a second inbox plane.

Do not invent CRHQ-style satellite mailboxes here.
