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

## Local changes

Two deliberate deviations from upstream. Re-apply both after any update.

**1. `design/` is renamed to `ux-design/`.** Claude Code ships a built-in skill
called `design`, and the built-in wins the name — upstream's skill was
unreachable. The directory and the `name:` field in its `SKILL.md` both say
`ux-design`, so it loads as `/ux-design`.

**2. Script paths in `ux-design/` are repo-relative.** Upstream points at
`~/.claude/skills/design/scripts/...`, a path that only exists for a
user-level install. The 48 references across 5 files now read
`.claude/skills/ux-design/scripts/...` and resolve from the repo root.

## Updating

    claude plugin marketplace update ui-ux-pro-max-skill
    cp -R ~/.claude/plugins/marketplaces/ui-ux-pro-max-skill/.claude/skills/. .claude/skills/
    # re-apply the two local changes above:
    rm -rf .claude/skills/ux-design
    mv .claude/skills/design .claude/skills/ux-design
    sed -i 's/^name: design$/name: ux-design/' .claude/skills/ux-design/SKILL.md
    grep -rl '~/\.claude/skills/design/' .claude/skills/ux-design \
      | xargs sed -i 's|~/\.claude/skills/design/|.claude/skills/ux-design/|g'

Otherwise do not hand-edit these files — local changes are lost on the next
update unless they are recorded here.
