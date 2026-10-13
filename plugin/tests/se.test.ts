import type { On } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

const ROOT = '/work'
const LOG = `${ROOT}/.se/.runtime/logs/s1.jsonl`

// The world beneath the plugin: a workspace whose files live in memory.
function world(on: On, env: Record<string, string> = {}): Map<string, string> {
  const files = new Map<string, string>()
  mock.env(on, env)
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('command.register', ($, e) => ({ value: { command: e.name } }))
  on('session.root', () => ({ value: ROOT }))
  on('session.id', () => ({ value: 's1' }))
  on('fs.write', ($, e) => {
    files.set(e.path, e.text)
    return { value: undefined }
  })
  on('fs.read', ($, e) => {
    const text = files.get(e.path)
    return text === undefined ? { deny: `ENOENT: ${e.path}` } : { value: text }
  })
  on('attribution.text', ($, e) => ({ text: e.text }))
  return files
}

const starts = { cwd: ROOT, surface: null, isInteractive: false }

function rows(files: Map<string, string>): { event: string }[] {
  return (files.get(LOG) ?? '')
    .split('\n')
    .filter(Boolean)
    .map(line => JSON.parse(line))
}

test('off by default: events pass and nothing is written', async ($, on) => {
  const files = world(on)
  await $.session.start(starts)
  await $.attribution.text({ kind: 'commit', text: 'probe' })
  expect([...files.keys()]).toEqual([])
})

test('/se-on creates the runtime folder and logs what follows', async ($, on) => {
  const files = world(on)
  await $.session.start(starts)
  const said = await $.command.run({ command: 'se-on', args: '' } as never)
  expect(said?.text ?? '').toContain('SE is on')
  expect(files.get(`${ROOT}/.se/.runtime/.gitignore`)).toBe('*\n')
  await $.attribution.text({ kind: 'commit', text: 'probe' })
  expect(rows(files).map(row => row.event)).toContain('attribution.text')
})

test('/se-off stops the logging', async ($, on) => {
  const files = world(on)
  await $.session.start(starts)
  await $.command.run({ command: 'se-on', args: '' } as never)
  await $.command.run({ command: 'se-off', args: '' } as never)
  const before = rows(files).length
  await $.attribution.text({ kind: 'commit', text: 'probe' })
  await $.attribution.text({ kind: 'commit', text: 'probe' })
  expect(rows(files).length).toBe(before)
})

test('SE_DEFAULT=on starts the session logging', async ($, on) => {
  const files = world(on, { SE_DEFAULT: 'on' })
  await $.session.start(starts)
  await $.attribution.text({ kind: 'commit', text: 'probe' })
  expect(files.get(`${ROOT}/.se/.runtime/.gitignore`)).toBe('*\n')
  expect(rows(files).map(row => row.event)).toContain('attribution.text')
})

test('every row lands, none overwrites another', async ($, on) => {
  const files = world(on)
  await $.session.start(starts)
  await $.command.run({ command: 'se-on', args: '' } as never)
  const before = rows(files).length
  await Promise.all(Array.from({ length: 20 }, () => $.attribution.text({ kind: 'commit', text: 'probe' })))
  expect(rows(files).filter(row => row.event === 'attribution.text').length).toBe(20)
  expect(rows(files).length).toBeGreaterThanOrEqual(before + 20)
})
