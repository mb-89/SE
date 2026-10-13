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
  // What the fake se answers a session call, by the words typed after /se.
  replies: Record<string, unknown>
  // What se answers the update at session start; a string is what it fails with on stderr.
  startUpdate: unknown
  reloads: number
  toasts: string[]
  // The commit git says the plugin's checkout is at.
  head: string
  // Where the update at session start moves the checkout, if anywhere.
  movesTo: string | null
  // The environment each se session call was given, by its words.
  envs: Record<string, Record<string, string>>
  // Every pane the plugin opened, by id and title.
  opened: { id: string; title?: string }[]
  // Every line the plugin logged to the transcript.
  logs: string[]
}

const HELP = '/se <command>\n\n  /se help   list the commands'

// The world beneath the plugin: a workspace, an se binary and its daemon, all in memory.
function world(on: On, env: Record<string, string> = {}): World {
  const w: World = {
    ran: [],
    posts: [],
    live: null,
    built: true,
    startFails: null,
    endpointFile: null,
    startUpdate: { text: '' },
    reloads: 0,
    toasts: [],
    head: 'aaa111',
    movesTo: null,
    envs: {},
    opened: [],
    logs: [],
    replies: {
      '': { text: HELP },
      on: { text: 'SE is on.', active: true, endpoint: DAEMON },
      off: { text: 'SE is off.', active: false },
      update: { text: 'SE updated aaa → bbb. Its daemon restarted.', endpoint: DAEMON, reload: true },
      status: { text: 'No SE daemon answers for /work.' },
      ui: { text: "SE's control panel is open.", panel: { buttons: ['issue next', 'status'] } },
    },
  }
  mock.env(on, env)
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('command.register', ($, e) => ({ value: { command: e.name } }))
  on('command.run', { command: 'reload-plugins' }, () => {
    w.reloads++
    return { text: 'reloaded' }
  })
  on('ui.toast', ($, e) => {
    w.toasts.push(e.text)
    return { value: undefined }
  })
  on('ui.open', ($, e) => {
    w.opened.push({ id: e.id, title: e.title })
    return { value: { isPlaced: true } }
  })
  on('ui.log', ($, e) => {
    w.logs.push(e.text)
    return { value: undefined }
  })
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
    if (argv[0] === 'git') {
      return { value: { exitCode: w.head ? 0 : 128, stdout: w.head ? `${w.head}\n` : '', stderr: '' } }
    }
    w.ran.push(argv)
    if (argv[1] === '--session') w.envs[argv.slice(4).join(' ')] = { ...(e.init?.env ?? {}) }
    const verb = argv[0] === 'go' ? 'build' : argv[1]
    if (verb === 'build') w.built = true
    if (verb === '--session' && argv[4] === 'update' && argv[5] === '--session-start') {
      if (w.movesTo) w.head = w.movesTo
      if (typeof w.startUpdate === 'string') return { value: { exitCode: 1, stdout: '', stderr: w.startUpdate } }
      return { value: { exitCode: 0, stdout: JSON.stringify(w.startUpdate), stderr: '' } }
    }
    if (verb === '--session') {
      const words = argv.slice(4).join(' ')
      if (words === 'on') w.live = DAEMON.address
      const reply = w.replies[words] ?? { text: `${HELP}\n\nse has no command "${words}".` }
      return { value: { exitCode: 0, stdout: JSON.stringify(reply), stderr: '' } }
    }
    if (verb === 'start' && w.startFails !== null) {
      return { value: { exitCode: 1, stdout: '', stderr: w.startFails } }
    }
    if (verb === 'start') {
      w.live = DAEMON.address
      return { value: { exitCode: 0, stdout: JSON.stringify(DAEMON), stderr: '' } }
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
const se = (args: string) => ({ command: 'se', args }) as never
const probe = { kind: 'commit', text: 'probe' } as const
// The update at session start shows as UPDATE; the session's other calls, by what was typed.
const UPDATE = '/se update --session-start'
const verbs = (w: World) =>
  w.ran.map(argv =>
    argv[0] === 'go'
      ? 'build'
      : argv[5] === '--session-start'
        ? UPDATE
        : argv[1] === '--session'
          ? `/se ${argv.slice(4).join(' ')}`.trim()
          : argv[1],
  )
const posted = (w: World) => w.posts.map(p => p.event)

test('off by default: events pass, nothing starts, nothing is posted', async ($, on) => {
  const w = world(on)
  await $.session.start(starts)
  const out = await $.attribution.text(probe)
  expect(out.text).toBe('probe')
  // The update at session start runs whether or not SE is on; nothing else does.
  expect(verbs(w)).toEqual([UPDATE])
  expect(w.posts).toEqual([])
})

test('/se on hands its words to se and forwards what follows', async ($, on) => {
  const w = world(on)
  await $.session.start(starts)
  const said = await $.command.run(se('on'))
  expect(said?.text ?? '').toContain('SE is on.')
  const call = w.ran.find(argv => argv[4] === 'on') ?? []
  expect(call[0]).toMatch(/\/bin\/se$/)
  expect(call.slice(1)).toEqual(['--session', '--workspace', ROOT, 'on'])
  await $.attribution.text(probe)
  expect(w.posts.find(p => p.event === 'attribution.text')).toEqual({
    url: `http://${DAEMON.address}/event`,
    auth: `Bearer ${DAEMON.token}`,
    event: 'attribution.text',
    session: 's1',
  })
})

test('/se off stops forwarding', async ($, on) => {
  const w = world(on)
  await $.session.start(starts)
  await $.command.run(se('on'))
  await $.command.run(se('off'))
  const before = w.posts.length
  await $.attribution.text(probe)
  expect(w.posts.length).toBe(before)
})

test('a bare /se shows the help se answers', async ($, on) => {
  const w = world(on)
  await $.session.start(starts)
  const said = await $.command.run(se(''))
  expect(said?.text).toBe(HELP)
  expect(verbs(w)).toEqual([UPDATE, '/se'])
})

test('the plugin knows no command: any words go to se as typed', async ($, on) => {
  const w = world(on)
  await $.session.start(starts)
  const said = await $.command.run(se('  frob   --now '))
  expect(said?.text ?? '').toContain('se has no command "frob --now".')
  expect(w.ran.at(-1)?.slice(4)).toEqual(['frob', '--now'])
  // A reply without effects switches nothing.
  await $.attribution.text(probe)
  expect(w.posts).toEqual([])
})

test('a se that does not answer says so', async ($, on) => {
  const w = world(on)
  w.replies.status = 'not json'
  await $.session.start(starts)
  const said = await $.command.run(se('status'))
  expect(said?.text ?? '').toContain('se did not answer')
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

test('a missing se is built from the checkout before it runs', async ($, on) => {
  const w = world(on)
  w.built = false
  await $.session.start(starts)
  await $.command.run(se('on'))
  expect(verbs(w).slice(0, 3)).toEqual(['build', UPDATE, '/se on'])
})

test('a missing se is built before the default start too', async ($, on) => {
  const w = world(on, { SE_DEFAULT: 'on' })
  w.built = false
  await $.session.start(starts)
  expect(verbs(w).slice(0, 3)).toEqual(['build', UPDATE, 'start'])
})

test('SE_DEFAULT=on says nothing when the daemon does not start, and passes events', async ($, on) => {
  const w = world(on, { SE_DEFAULT: 'on' })
  w.startFails = 'no room'
  await $.session.start(starts)
  const out = await $.attribution.text({ kind: 'commit', text: 'still here' })
  expect(out.text).toBe('still here')
  expect(w.posts).toEqual([])
})

test('a daemon that moved is found again through daemon.json', async ($, on) => {
  const w = world(on)
  await $.session.start(starts)
  await $.command.run(se('on'))
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
  await $.command.run(se('on'))
  w.live = null
  const out = await $.attribution.text({ kind: 'commit', text: 'still here' })
  expect(out.text).toBe('still here')
})

test('/se update applies the new endpoint and reloads once it has answered', async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on)
  await $.session.start(starts)
  await $.command.run(se('on'))
  w.ran = []
  w.live = '127.0.0.1:4300'
  w.replies.update = {
    text: 'SE updated aaa → bbb. Its daemon restarted.',
    endpoint: { address: '127.0.0.1:4300', token: 'tok3' },
    reload: true,
  }
  const said = await $.command.run(se('update'))
  expect(said?.text ?? '').toContain('aaa → bbb')
  expect(said?.text ?? '').toContain('The plugins reload now.')
  expect(verbs(w)).toEqual(['/se update'])
  await clock.settle()
  expect(w.reloads).toBe(1)
  await $.attribution.text(probe)
  expect(w.posts.at(-1)?.auth).toBe('Bearer tok3')
})

test('/se restart moves the session to the daemon se answers, without a reload', async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on)
  await $.session.start(starts)
  await $.command.run(se('on'))
  w.ran = []
  // The old daemon is gone; the restarted one answers on a new port with a new token.
  w.live = '127.0.0.1:4400'
  w.replies.restart = {
    text: "SE's daemon restarted at 127.0.0.1:4400 (pid 7). The daemon runs se built from this checkout.",
    endpoint: { address: '127.0.0.1:4400', token: 'tok4' },
  }
  const said = await $.command.run(se('restart'))
  expect(said?.text ?? '').toContain('built from this checkout')
  expect(verbs(w)).toEqual(['/se restart'])
  await clock.settle()
  expect(w.reloads).toBe(0)
  await $.attribution.text(probe)
  expect(w.posts.at(-1)?.url).toBe('http://127.0.0.1:4400/event')
  expect(w.posts.at(-1)?.auth).toBe('Bearer tok4')
})

test('a restart whose build failed shows why, and still moves to the daemon', async ($, on) => {
  const w = world(on)
  await $.session.start(starts)
  await $.command.run(se('on'))
  w.live = '127.0.0.1:4500'
  w.replies.restart = {
    text: "SE's daemon restarted at 127.0.0.1:4500 (pid 8). This checkout's se does not build, so the daemon runs the installed se (/se/src/plugin/bin/se):\ngo build: exit status 1\n./x.go:3: undefined: y",
    endpoint: { address: '127.0.0.1:4500', token: 'tok5' },
  }
  const said = await $.command.run(se('restart'))
  expect(said?.text ?? '').toContain('does not build')
  expect(said?.text ?? '').toContain('undefined: y')
  await $.attribution.text(probe)
  expect(w.posts.at(-1)?.auth).toBe('Bearer tok5')
})

test('session start updates the checkout the plugin came from, then reloads once start has answered', async ($, on) => {
  const w = world(on, { SE_DEFAULT: 'on' })
  const clock = mock.clock(on)
  w.startUpdate = { text: 'SE updated aaa → bbb.', reload: true }
  await $.session.start(starts)
  const update = w.ran.find(argv => argv[5] === '--session-start') ?? []
  expect(update.slice(1, 6)).toEqual(['--session', '--workspace', ROOT, 'update', '--session-start'])
  expect(update[6]).toBe('--repo')
  expect(update[7]).toMatch(/\/\.\.$/)
  // The update comes before the daemon starts, so the daemon is the new se's.
  expect(verbs(w).slice(0, 2)).toEqual([UPDATE, 'start'])
  expect(w.toasts).toEqual(['SE updated aaa → bbb. The plugins reload now.'])
  expect(w.reloads).toBe(0)
  await clock.settle()
  expect(w.reloads).toBe(1)
})

test('a checkout that is current says nothing and does not reload', async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on)
  await $.session.start(starts)
  await clock.settle()
  expect(w.toasts).toEqual([])
  expect(w.reloads).toBe(0)
})

test('a checkout that is no clean main is left alone, noted in one line', async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on)
  w.startUpdate = { text: 'SE left its checkout as it is: /me/SE/src/plugin/../.. is on topic, not main; the installed SE updates from main alone.' }
  await $.session.start(starts)
  await clock.settle()
  expect(w.toasts).toEqual([w.startUpdate.text])
  expect(w.reloads).toBe(0)
})

test('a failed update does not block session start: the session goes on and says so', async ($, on) => {
  const w = world(on, { SE_DEFAULT: 'on' })
  const clock = mock.clock(on)
  w.startUpdate = 'fatal: unable to access origin\nCould not resolve host'
  await $.session.start(starts)
  await clock.settle()
  expect(w.toasts.length).toBe(1)
  expect(w.toasts[0]).toContain('SE did not update itself')
  expect(w.toasts[0]).not.toContain('\n')
  expect(w.reloads).toBe(0)
  // The session started on, as asked, with the SE it has.
  expect(verbs(w)).toContain('start')
  await $.attribution.text(probe)
  expect(posted(w)).toContain('attribution.text')
})

test('/se status tells se the commit the hooks were loaded from, and their checkout', async ($, on) => {
  const w = world(on)
  await $.session.start(starts)
  await $.command.run(se('status'))
  expect(w.envs.status?.SE_HOOKS_COMMIT).toBe('aaa111')
  expect(w.envs.status?.SE_PLUGIN_CHECKOUT).toMatch(/\/\.\.$/)
})

test('the hooks keep the commit they loaded from when the update moves the checkout, until they load again', async ($, on) => {
  const w = world(on)
  w.movesTo = 'bbb222'
  await $.session.start(starts)
  await $.command.run(se('status'))
  expect(w.envs.status?.SE_HOOKS_COMMIT).toBe('aaa111')
  // A reload runs session.start again: the hooks are now the checkout's.
  w.movesTo = null
  await $.session.start(starts)
  await $.command.run(se('status'))
  expect(w.envs.status?.SE_HOOKS_COMMIT).toBe('bbb222')
})

test('hooks whose checkout git cannot read tell se no commit', async ($, on) => {
  const w = world(on)
  w.head = ''
  await $.session.start(starts)
  await $.command.run(se('status'))
  expect(w.envs.status?.SE_HOOKS_COMMIT).toBe('')
})

test('a missing se is built with the commit it is built from', async ($, on) => {
  const w = world(on)
  w.built = false
  await $.session.start(starts)
  const build = w.ran.find(argv => argv[0] === 'go') ?? []
  expect(build.slice(0, 4)).toEqual(['go', 'build', '-ldflags', '-X main.commit=aaa111'])
})

const SURFACES = ['terminal', 'desktop', 'vscode', 'mobile'] as const
const PANE = {
  plugin: 'se',
  component: 'Pane',
  requestId: 'se-ui',
  props: {
    title: 'SE',
    isFocused: false,
    bodyColumns: 40,
    placement: 'inline',
    scroll: { offset: 0, bodyRows: 10 },
    view: {},
  },
} as const

test('/se ui opens a pane titled SE that draws on every surface', async ($, on) => {
  const w = world(on)
  await $.session.start(starts)
  const said = await $.command.run(se('ui'))
  expect(said?.text).toBe("SE's control panel is open.")
  expect(w.opened).toEqual([{ id: 'se-ui', title: 'SE' }])
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...PANE, surface })
    const drawn = await ui.drawn()
    expect(drawn).toMatchObject({ type: 'Box', props: { flexWrap: 'wrap', width: 40 } })
    const buttons = await ui.findAll({ type: 'Button' })
    // The toggle first, top left; then se's buttons in the order it named them.
    expect(buttons.map(b => b.props.label)).toEqual(['SE off', 'issue next', 'status'])
    await ui.unmount()
  }
})

test('pressing the toggle runs /se on and /se off, and switches the flag', async ($, on) => {
  const w = world(on)
  await $.session.start(starts)
  await $.command.run(se('ui'))
  const ui = await $.ui.mount({ ...PANE, surface: 'mobile' })
  expect((await ui.find({ key: 'toggle' }))?.props).toMatchObject({ label: 'SE off', dimColor: true })
  await ui.press({ key: 'toggle' })
  expect(verbs(w).at(-1)).toBe('/se on')
  expect(w.logs).toEqual(['SE is on.'])
  // The flag is on: what follows is forwarded.
  await $.attribution.text(probe)
  expect(posted(w)).toContain('attribution.text')
  expect((await ui.find({ key: 'toggle' }))?.props).toMatchObject({ label: 'SE on', variant: 'primary' })
  await ui.press({ key: 'toggle' })
  expect(verbs(w).at(-1)).toBe('/se off')
  expect((await ui.find({ key: 'toggle' }))?.props.label).toBe('SE off')
  // The flag is off: nothing more is forwarded.
  const before = w.posts.length
  await $.attribution.text(probe)
  expect(w.posts.length).toBe(before)
})

test('/se off typed in the prompt redraws the toggle', async ($, on) => {
  const w = world(on)
  await $.session.start(starts)
  await $.command.run(se('on'))
  await $.command.run(se('ui'))
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ key: 'toggle' }))?.props.label).toBe('SE on')
  await $.command.run(se('off'))
  expect((await ui.find({ key: 'toggle' }))?.props.label).toBe('SE off')
  expect(w.opened.length).toBe(1)
})

test('a command se offers as a button appears, and pressing it runs /se <name>', async ($, on) => {
  const w = world(on)
  await $.session.start(starts)
  await $.command.run(se('ui'))
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })
  expect(await ui.find({ key: 'run issue next' })).toBeDefined()
  w.ran = []
  await ui.press({ key: 'run status' })
  expect(verbs(w)).toEqual(['/se status'])
  // Its answer is a line of the transcript, as the command's answer is.
  expect(w.logs).toEqual(['No SE daemon answers for /work.'])
})

test('a command se does not offer as a button does not appear', async ($, on) => {
  const w = world(on)
  await $.session.start(starts)
  await $.command.run(se('ui'))
  const ui = await $.ui.mount({ ...PANE, surface: 'vscode' })
  expect(await ui.find({ key: 'run issue new' })).toBeUndefined()
  expect(await ui.find({ type: 'Button', text: /issue new/ })).toBeUndefined()
  expect(w.opened.length).toBe(1)
})
