# Evaluations of SE's skills

Data for two evaluations a person runs by hand. Nothing in SE runs them: no CI job, hook, script
or `se.toml` entry. `tests/test_eval_data.py` checks only the data's shape and starts no model.

- `triggers/<skill>.json`: about twenty labelled prompts per skill, each `{"query",
  "should_trigger", "split"}`. A near-miss shares a word with the skill's description but needs
  something else. The split into `train` and `validation` is fixed in the data.
- `outcomes/<case>/`: one case per skill in the layout `claude plugin eval` reads, a `prompt.md`
  and `graders/<name>.md`. Every grader is `regex` or `tool_used`; none calls a judge.

## What a run needs

Claude Code 2.1.269 or later and git 2.31 or later. Every run counts against the subscription's
usage and needs no other key.

Run from a checkout on a branch other than `main` (the start never moves a development checkout), or from a `main` checkout that is up to date with origin. SE's start hook runs in every with-plugin run and uses the network, while the cases do not.

The GitHub state each case needs is fixed text in its prompt, as the GitHub tools returned it, so
both arms see the same input and no mock layer is needed: SE's Claude plugin declares no MCP
server (`.claude-plugin/plugin.json`), and no case needs a GitHub tool, Bash or the network.

## Outcome cases

From the checkout root:

```sh
claude plugin eval . --eval-dir tests/evals/outcomes --allow-tools Write --no-publish
```

Each case also runs without the plugin; the report shows WITH, W/OUT and Δ. The `skill-fired`
grader shows the plugin's skill fired and is not scored; the other graders score both arms.
The same with a smaller model, the only difference:

```sh
claude plugin eval . --eval-dir tests/evals/outcomes --allow-tools Write --no-publish --model <a smaller model>
```

Each run writes its report under `tests/evals/outcomes/results/`, which git ignores.

## Trigger loop

Pick the entries with `jq`; `validation` instead of `train` picks the rest:

```sh
jq 'map(select(.split=="train"))' tests/evals/triggers/<skill>.json
```

Run each query three times, each from an empty folder:

```sh
claude -p "$query" --plugin-dir <checkout> --output-format stream-json --verbose
```

A run fired when any `tool_use` named `Skill` has an `input.skill` matching `^(se:)?<skill>$`;
`--output-format json` returns only the final result and shows no tool call. A query whose trigger
rate is above 0.5 counts as fired. Change the skill's description on the train entries only, and
pick the best description on the validation entries.
