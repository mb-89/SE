import type { On } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

const ROOT = '/work'
const DAEMON = { address: '127.0.0.1:4100', token: 'tok' }

type World = {
  // Every argv the plugin ran, and every event it posted.
  ran: string[][]
  posts: { url: string; auth: string; event: string; session: string }[]
  // Where the fake daemon answers now; null while it is down.
  live: string | null
  built: boolean
  // What `se start` says on stderr when it fails; null while it starts.
  startFails: string | null
  endpointFile: string | null
}

// The world beneath the plugin: a workspace, an se binary and its daemon, all in memory.
function world(on: On, env: Record<string, string> = {}): World {
  const w: World = { ran: [], posts: [], live: null, built: true, startFails: null, endpointFile: null }
  mock.env(on, env)
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('command.register', ($, e) => ({ value: { command: e.name } }))
  on('command.run', { command: 'reload-plugins' }, () => ({ text: 'reloaded' }))
  on('session.root', () => ({ value: ROOT }))
  on('session.id', () => ({ value: 's1' }))
  on('fs.exists', ($, e) => ({ value: e.path.endsWith('/bin/se') ? w.built : false }))
  on('fs.read', ($, e) =>
    e.path === `${ROOT}/.se/.runtime/daemon.json` && w.endpointFile !== null
      ? { value: w.endpointFile }
      : { deny: `ENOENT: ${e.path}` },
  )
  on('process.run', ($, e) => {
    const argv = [...e.argv]
    w.ran.push(argv)
    const verb = argv[0] === 'go' ? 'build' : argv[1]
    if (verb === 'build') w.built = true
    if (verb === 'start' && w.startFails !== null) {
      return { value: { exitCode: 1, stdout: '', stderr: w.startFails } }
    }
    if (verb === 'start') {
      w.live = DAEMON.address
      return { value: { exitCode: 0, stdout: JSON.stringify(DAEMON), stderr: '' } }
    }
    if (verb === 'update') {
      return { value: { exitCode: 0, stdout: '{"from":"aaa","to":"bbb"}', stderr: '' } }
    }
    return { value: { exitCode: 0, stdout: '', stderr: '' } }
  })
  on('http.fetch', ($, e) => {
    if (w.live === null || e.url !== `http://${w.live}/event`) return { deny: 'connection refused' }
    const body = JSON.parse(String(e.init?.body ?? '{}'))
    w.posts.push({
      url: e.url,
      auth: String(e.init?.headers?.authorization ?? ''),
      event: body.event,
      session: body.session,
    })
    return { value: { status: 200, ok: true, headers: {}, text: '{}' } }
  })
  on('attribution.text', ($, e) => ({ text: e.text }))
  return w
}

const starts = { cwd: ROOT, surface: null, isInteractive: false }
const run = (command: string) => ({ command, args: '' }) as never
const probe = { kind: 'commit', text: 'probe' } as const
const verbs = (w: World) => w.ran.map(argv => (argv[0] === 'go' ? 'build' : argv[1]))
const posted = (w: World) => w.posts.map(p => p.event)

test('off by default: events pass, nothing starts, nothing is posted', async ($, on) => {
  const w = world(on)
  await $.session.start(starts)
  const out = await $.attribution.text(probe)
  expect(out.text).toBe('probe')
  expect(w.ran).toEqual([])
  expect(w.posts).toEqual([])
})

test('/se-on starts the daemon and forwards what follows', async ($, on) => {
  const w = world(on)
  await $.session.start(starts)
  const said = await $.command.run(run('se-on'))
  expect(said?.text ?? '').toContain('SE is on.')
  const start = w.ran.find(argv => argv[1] === 'start') ?? []
  expect(start[0]).toMatch(/\/bin\/se$/)
  expect(start.slice(1)).toEqual(['start', '--workspace', ROOT])
  await $.attribution.text(probe)
  expect(w.posts.find(p => p.event === 'attribution.text')).toEqual({
    url: `http://${DAEMON.address}/event`,
    auth: `Bearer ${DAEMON.token}`,
    event: 'attribution.text',
    session: 's1',
  })
})

test('/se-off stops forwarding', async ($, on) => {
  const w = world(on)
  await $.session.start(starts)
  await $.command.run(run('se-on'))
  await $.command.run(run('se-off'))
  const before = w.posts.length
  await $.attribution.text(probe)
  expect(w.posts.length).toBe(before)
})

test('SE_DEFAULT=on starts the session switched on', async ($, on) => {
  const w = world(on, { SE_DEFAULT: 'on' })
  await $.session.start(starts)
  expect(verbs(w).filter(v => v === 'start').length).toBe(1)
  // The start's own events waited for the daemon, and reached it.
  expect(posted(w)).toContain('process.run')
  await $.attribution.text(probe)
  expect(posted(w)).toContain('attribution.text')
})

test('a missing se is built from the checkout before it starts', async ($, on) => {
  const w = world(on)
  w.built = false
  await $.session.start(starts)
  await $.command.run(run('se-on'))
  expect(verbs(w).slice(0, 2)).toEqual(['build', 'start'])
})

test('/se-on says so when the daemon does not start', async ($, on) => {
  const w = world(on)
  w.startFails = 'no room'
  await $.session.start(starts)
  const said = await $.command.run(run('se-on'))
  expect(said?.text ?? '').toContain('did not start: no room')
})

test('a daemon that moved is found again through daemon.json', async ($, on) => {
  const w = world(on)
  await $.session.start(starts)
  await $.command.run(run('se-on'))
  // The daemon restarts under the debugger, on a new port with a new token.
  w.live = '127.0.0.1:4200'
  w.endpointFile = JSON.stringify({ address: '127.0.0.1:4200', token: 'tok2' })
  await $.attribution.text(probe)
  expect(w.posts.at(-1)?.url).toBe('http://127.0.0.1:4200/event')
  expect(w.posts.at(-1)?.auth).toBe('Bearer tok2')
})

test('a daemon that is down never holds the event up', async ($, on) => {
  const w = world(on)
  await $.session.start(starts)
  await $.command.run(run('se-on'))
  w.live = null
  const out = await $.attribution.text({ kind: 'commit', text: 'still here' })
  expect(out.text).toBe('still here')
})

test('/se-update updates, restarts the daemon and reloads', async ($, on) => {
  const w = world(on)
  await $.session.start(starts)
  await $.command.run(run('se-on'))
  w.ran = []
  const said = await $.command.run(run('se-update'))
  expect(said?.text ?? '').toContain('aaa → bbb')
  expect(verbs(w)).toEqual(['update', 'stop', 'start'])
})
