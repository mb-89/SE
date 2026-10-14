#!/bin/sh
# Prints the trees the plugin draws for /se help and /se help issue pull from se's real answers, as the test kit mounts them, for a PR body.
set -eu
cd "$(dirname "$0")/../.."
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
go build -o "$tmp/se" ./src/cmd/se
mkdir "$tmp/plugin"
cp -r src/plugin/.claude-plugin src/plugin/hooks src/plugin/types "$tmp/plugin/"
mkdir "$tmp/plugin/tests"
help=$("$tmp/se" --session --workspace "$tmp" help)
next=$("$tmp/se" --session --workspace "$tmp" help issue pull)
cat > "$tmp/plugin/tests/trees.test.ts" <<EOF
import { mock, test } from 'claude-code/testing'

const replies: Record<string, string> = { help: $(printf '%s' "$help" | jq -Rs .), 'help issue pull': $(printf '%s' "$next" | jq -Rs .) }

const outline = (node: unknown, depth = 0): string[] => {
  if (typeof node === 'string') return [\`\${'  '.repeat(depth)}"\${node}"\`]
  const el = node as { type: string; props?: Record<string, unknown>; children?: unknown[] }
  const shown = Object.entries(el.props ?? {}).map(([k, v]) => \`\${k}=\${JSON.stringify(v)}\`).join(' ')
  return [\`\${'  '.repeat(depth)}<\${el.type}\${shown ? ' ' + shown : ''}>\`, ...(el.children ?? []).flatMap(c => outline(c, depth + 1))]
}

test('trees', async (\$, on) => {
  mock.env(on, {})
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('command.register', (_, e) => ({ value: { command: e.name } }))
  on('fs.exists', () => ({ value: true }))
  on('session.root', () => ({ value: '/work' }))
  on('process.run', (_, e) => {
    const words = [...e.argv].slice(4).join(' ')
    return { value: { exitCode: 0, stdout: replies[words] ?? '{"text":""}', stderr: '' } }
  })
  await \$.session.start({ cwd: '/work', surface: null, isInteractive: false })
  for (const args of Object.keys(replies)) {
    const said = await \$.command.run({ command: 'se', args } as never)
    for (const surface of ['terminal', 'desktop'] as const) {
      const ui = await \$.ui.mount({ plugin: 'se', surface, component: 'CommandOutput', requestId: args, props: { command: 'se', args, text: said?.text ?? '', isErrored: false } })
      console.log([\`/se \${args} on \${surface}\`, ...outline(await ui.drawn())].join('\n'))
      await ui.unmount()
    }
  }
})
EOF
claude plugin test "$tmp/plugin"
