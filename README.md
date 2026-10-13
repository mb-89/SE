# SE

## Install

    ./RUNME.sh

That installs the SE plugin for your user, so every Claude session on this
machine has `/se-on` and `/se-off`. While SE is on, every event of the session
is logged under `.se/.runtime/logs/` in the workspace.

On a cloud box, set these in the environment's variables:

    CLAUDE_CODE_PLUGIN_DIRS=/home/user/SE/plugin
    SE_DEFAULT=on

## Check

    sh ./tests/check.sh
