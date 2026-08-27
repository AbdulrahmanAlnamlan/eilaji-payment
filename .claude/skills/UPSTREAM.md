# Vendored skills

The seven skill directories here are a verbatim copy of the `.claude/skills/`
tree from the `ui-ux-pro-max` plugin.

| | |
|---|---|
| Source | https://github.com/nextlevelbuilder/ui-ux-pro-max-skill |
| Plugin | `ui-ux-pro-max@ui-ux-pro-max-skill` |
| Version | 2.13.0 |
| License | MIT (see `LICENSE`) |

They are committed so the skills work with no plugin install and no network
access. `../settings.json` also registers the upstream marketplace, so anyone
opening this project gets the plugin installed as well — vendoring is the
offline fallback, the plugin is the path to updates.

Fonts under `ui-styling/canvas-fonts/` are SIL Open Font License; each face
ships its own `*-OFL.txt` alongside the `.ttf`.

## Updating

    claude plugin marketplace update ui-ux-pro-max-skill
    cp -R ~/.claude/plugins/marketplaces/ui-ux-pro-max-skill/.claude/skills/. .claude/skills/

Do not hand-edit these files — local changes are lost on the next update.
