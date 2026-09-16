# Forum lane deepen (no auto-tags)

Forum-as-realm + tags-as-tickets reuse **JobPool only**.

```bash
# Refresh status↔tag map from tags that already exist on the forum.
# Never creates Discord available_tags.
discord-os add forum-tags --channel-id FORUM_ID
```

HARD lock: `modify_channel` refuses any PATCH that includes `available_tags`.
Missing status tags → soft-skip sync (or spoken Need when required); add tags
manually in Discord.
