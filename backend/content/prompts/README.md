# Prompt texts and pictures

This folder is the team's editable copy of the prompt library's starting set (ADR-036).
The app never reads it directly: the command below copies it into the database.

- `prompts.json`: every prompt (key, type, text, language, script, Hindi/English meaning,
  topics, source and licence). `note` is for the people editing the file and is not stored.
  `retire` lists keys of old prompts to stop showing.
- `images/*.webp`: the pictures used by image prompts. `images/source/*.svg` are the
  drawings they were made from (original, no people shown, CC BY 4.0).

Load into the database (each picture goes to object storage, its key onto the prompt row):

```bash
uv run python -m app.cli load-prompts --as <admin or reviewer>            # as drafts
uv run python -m app.cli load-prompts --as <admin> --approve              # already checked
```

Loading again only adds prompts whose key is new. To change a prompt already in the database,
make a new version in the prompt library (`POST /admin/prompts/{id}/versions`), because
recordings keep the exact version they were made with.

The ten Mundari sentences (`read-unr-deva-*`) are drafts written by the team and must be checked
by a Mundari speaker before real collection (Q-G17).
