# Cloud boxes: SE in a cloud environment

Reader: whoever sets up or changes a cloud environment that runs SE.

A cloud environment that runs SE gets it from its setup script:

```sh
#!/bin/bash
set -u
rm -rf /opt/se
git clone --depth 1 https://github.com/mb-89/SE /opt/se \
  && sh /opt/se/src/build.sh \
  || echo "SE setup failed; sessions start without SE"
/opt/se/src/plugin/bin/se fleet plugins --into /opt/se-plugins \
  || echo "SE's outside plugins failed; sessions start without them"
exit 0
```

and from these environment variables:

    CLAUDE_CODE_PLUGIN_DIRS=/opt/se/src/plugin:/opt/se-plugins
    SE_DEFAULT=on

SE lives in `/opt/se` and not in the session's own checkout: every session of
the environment has `/opt/se`, whatever repos are attached to it, and a box
working on SE never runs the plugin code it is editing. `SE_DEFAULT=on` starts
every session switched on. The fan-out's own variables are in
[spec/issues.md](issues.md#fan-out).

The setup script's result is cached, so `/opt/se` can be many commits behind
when a session starts. The plugin therefore updates its own checkout at every
session start, whether or not SE is on: a clean `main` is pulled from
`origin/main` (a shallow clone too), `se` is rebuilt if anything changed, and,
in a local session, the plugin reloads once `session.start` has answered. A
remote session (`CLAUDE_CODE_REMOTE=true`, a cloud box) is not asked to
reload: it refuses `/reload-plugins`, and the new `se` runs at once anyway. A checkout that is not a
clean `main`, such as a person's working clone, is left as it is, and a failed
pull or build never holds the session up; either is said in one line.

## The outside plugins

SE runs plugins and skills others built, each pinned to a commit in the
reuse config of [src/index/wiring.yaml](../src/index/wiring.yaml);
`se fleet plugins` fetches them into `/opt/se-plugins`. A cloud box gets
plugins only through `CLAUDE_CODE_PLUGIN_DIRS`, which takes several folders
(`:` between them), and a folder there that is no plugin itself loads each
plugin inside it. So the variable names `/opt/se-plugins` once, and adding or
moving a plugin changes the config, not the environment. A folder that is
missing is skipped, and SE still loads.

SE's plugin manifest does not declare them as `dependencies` (the plugins
reference: each resolved in a marketplace, or satisfied by a loaded folder).
A declared dependency that is not loaded disables SE itself, and a version
range pins to a release tag, never a commit, which the official marketplace
does not tag.

## Hooks on cloud boxes

Changes to `src/plugin/hooks` reach cloud boxes only when the environment's setup
script is changed, which rebuilds its cache. `/reload-plugins` is refused over
a remote connection, and the update at session start loads a new `se` at once
but not the hooks module that is already running; whether watching the plugin
folder (`CLAUDE_CODE_PLUGIN_DIR_WATCH=1`) reloads them has not been seen on a
box (#28). New behaviour therefore belongs in `se`, not in the hooks.
`/se status` names the commits the loaded hooks, the plugin's checkout and the
running `se` came from, and whether they agree: one line where they agree;
where they disagree, a short line per commit and the remedy, a new session,
once.
