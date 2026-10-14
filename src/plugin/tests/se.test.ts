import type { On } from 'claude-code'
import { expect, type MockClock, mock, test } from 'claude-code/testing'

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
  // Every status line the plugin set; undefined is a cleared one.
  statuses: (string | undefined)[]
  // How long the fake se takes to answer, by the words typed after /se.
  takes: Record<string, number>
  // The clock beneath the plugin, which moves only when the test moves it.
  clock: MockClock
  // What se hook stop prints; a number is the exit code it fails with.
  verdict: unknown
}

const HELP = '/se <command>\n\n  /se help   list the commands'
// The help se answers as data beside its text (Help in src/cmd/se/help.go).
const OVERVIEW = {
  usage: '/se <command> [flags]',
  groups: [
    {
      name: 'Issues',
      commands: [{ name: 'issue pull', summary: 'name the next se issue', usage: '/se issue pull [--take [N]]' }],
    },
    {
      name: 'Session',
      commands: [
        { name: 'help', summary: 'list the commands, or show one', usage: '/se help [<command>]' },
        { name: 'on', summary: 'switch SE on', usage: '/se on' },
      ],
    },
  ],
  note: '/se help <command> shows its usage and flags.',
}
const ISSUE_PULL = {
  usage: '/se issue pull [--take [N]]',
  about: 'Name the next ready se issue.',
  flags: [
    { name: '--take', usage: 'claim the next ready issue' },
    { name: '--workspace DIR', usage: 'the workspace DIR the daemon serves' },
  ],
}

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
    statuses: [],
    takes: {},
    clock: mock.clock(on),
    verdict: { pass: 'no se issue was taken here' },
    replies: {
      '': { text: HELP },
      on: { text: 'SE is on.', active: true, endpoint: DAEMON },
      off: { text: 'SE is off.', active: false },
      update: { text: 'SE updated aaa → bbb. Its daemon restarted.', endpoint: DAEMON, reload: true },
      status: { text: 'No SE daemon answers for /work.' },
      ui: { text: "SE's control panel is open.", panel: { buttons: ['issue pull', 'status'] } },
      help: { text: HELP, help: OVERVIEW },
      'help issue pull': { text: '/se issue pull [--take [N]]\n```\n…\n```', help: ISSUE_PULL },
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
  on('ui.status', ($, e) => {
    w.statuses.push(e.text)
    return { value: undefined }
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
  on('process.run', async ($, e) => {
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
      const takes = w.takes['update --session-start']
      if (takes) await w.clock.sleep(takes)
      if (typeof w.startUpdate === 'string') return { value: { exitCode: 1, stdout: '', stderr: w.startUpdate } }
      return { value: { exitCode: 0, stdout: JSON.stringify(w.startUpdate), stderr: '' } }
    }
    if (verb === '--session') {
      const words = argv.slice(4).join(' ')
      const takes = w.takes[words]
      if (takes) await w.clock.sleep(takes)
      if (words === 'on') w.live = DAEMON.address
      const reply = w.replies[words] ?? { text: `${HELP}\n\nse has no command "${words}".` }
      return { value: { exitCode: 0, stdout: JSON.stringify(reply), stderr: '' } }
    }
    if (verb === 'hook' && argv[2] === 'stop') {
      if (typeof w.verdict === 'number') return { value: { exitCode: w.verdict, stdout: '', stderr: 'se: boom' } }
      return { value: { exitCode: 0, stdout: JSON.stringify(w.verdict), stderr: '' } }
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
  on('prompt.context', ($, e) => ({ blocks: e.blocks }))
  on('session.compact', () => ({ messages: [{ role: 'user', text: 'the summary', toolUses: [] }] }) as never)
  on('classic.Stop', () => ({}))
  on('classic.SubagentStop', () => ({}))
  on('prompt.submit', ($, e) => ({ text: e.text }) as never)
  // The engine's own output row: the text as it came.
  on('ui.render', { component: 'CommandOutput' }, ($, e) => ({ type: 'Text', children: [e.props.text] }) as never)
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

test('an se call past one second says it is working at one second, and holds nothing up', async ($, on) => {
  const w = world(on)
  const clock = w.clock
  w.takes.slow = 5000
  w.replies.slow = { text: 'slow is done.' }
  await $.session.start(starts)
  let said: { text?: string } | undefined
  const running = $.command.run(se('slow')).then(out => {
    said = out
  })
  await clock.advance(999)
  expect(w.statuses).toEqual([])
  expect(said).toBeUndefined()
  await clock.advance(1)
  await running
  // At one second the status line says what is working, and the command answers.
  expect(w.statuses).toEqual(['se: /se slow…'])
  expect(said?.text).toBe('/se slow is still working; its answer follows here.')
  // The session goes on meanwhile.
  expect((await $.attribution.text(probe)).text).toBe('probe')
  expect(w.logs).toEqual([])
  await clock.advance(4000)
  // se's answer follows in the transcript, and the status line clears.
  expect(w.logs).toEqual(['slow is done.'])
  expect(w.statuses).toEqual(['se: /se slow…', undefined])
})

test('an se call within one second answers as it is, with no status line', async ($, on) => {
  const w = world(on)
  const clock = w.clock
  w.takes.status = 999
  await $.session.start(starts)
  const running = $.command.run(se('status'))
  await clock.advance(999)
  expect((await running)?.text).toBe('No SE daemon answers for /work.')
  await clock.advance(5000)
  expect(w.statuses).toEqual([])
  expect(w.logs).toEqual([])
})

test('a slow update at session start does not hold the session up', async ($, on) => {
  const w = world(on, { SE_DEFAULT: 'on' })
  const clock = w.clock
  w.takes['update --session-start'] = 5000
  let started = false
  const starting = $.session.start(starts).then(() => {
    started = true
  })
  await clock.advance(999)
  expect(started).toBe(false)
  await clock.advance(1)
  await starting
  expect(started).toBe(true)
  expect(w.statuses).toEqual(['se: updating itself…'])
  // An event raised meanwhile waits for the daemon the setup starts.
  await $.attribution.text(probe)
  expect(posted(w)).toEqual([])
  await clock.advance(4000)
  expect(verbs(w)).toEqual([UPDATE, 'start'])
  expect(posted(w)).toContain('attribution.text')
  expect(w.statuses).toEqual(['se: updating itself…', undefined])
})

test('events raised while a slow setup leaves SE off are dropped', async ($, on) => {
  const w = world(on)
  const clock = w.clock
  w.takes['update --session-start'] = 5000
  const starting = $.session.start(starts)
  await clock.advance(1000)
  await starting
  await $.attribution.text(probe)
  await clock.advance(4000)
  await $.command.run(se('on'))
  expect(posted(w)).not.toContain('attribution.text')
})

test('while SE is on, each se call is a row of the daemon log with its duration', async ($, on) => {
  const w = world(on)
  await $.session.start(starts)
  await $.command.run(se('on'))
  await $.command.run(se('status'))
  expect(posted(w)).toContain('se.call')
})

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

test('a daemon that is gone is started again at most once a minute, by the plugin clock', async ($, on) => {
  const w = world(on)
  const clock = w.clock
  await $.session.start(starts)
  await $.command.run(se('on'))
  w.ran = []
  w.live = null
  w.startFails = 'no room'
  // The on counts as a start: the first try waits its minute.
  await clock.advance(59_999)
  await $.attribution.text(probe)
  expect(verbs(w)).toEqual([])
  await clock.advance(1)
  await $.attribution.text(probe)
  expect(verbs(w)).toEqual(['start'])
  await clock.advance(59_999)
  await $.attribution.text(probe)
  expect(verbs(w)).toEqual(['start'])
  await clock.advance(1)
  await $.attribution.text(probe)
  expect(verbs(w)).toEqual(['start', 'start'])
})

test('/se update applies the new endpoint and reloads once it has answered', async ($, on) => {
  const w = world(on)
  const clock = w.clock
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
  const clock = w.clock
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
  const clock = w.clock
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
  const clock = w.clock
  await $.session.start(starts)
  await clock.settle()
  expect(w.toasts).toEqual([])
  expect(w.reloads).toBe(0)
})

test('a checkout that is no clean main is left alone, noted in one line', async ($, on) => {
  const w = world(on)
  const clock = w.clock
  w.startUpdate = {
    text: 'SE left its checkout as it is: /me/SE/src/plugin/../.. is on topic, not main; the installed SE updates from main alone.',
  }
  await $.session.start(starts)
  await clock.settle()
  expect(w.toasts).toEqual([w.startUpdate.text])
  expect(w.reloads).toBe(0)
})

test('a failed update does not block session start: the session goes on and says so', async ($, on) => {
  const w = world(on, { SE_DEFAULT: 'on' })
  const clock = w.clock
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
    expect(buttons.map(b => b.props.label)).toEqual(['SE off', 'issue pull', 'status'])
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
  expect(await ui.find({ key: 'run issue pull' })).toBeDefined()
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

// A /se line's output row, as the transcript raises it for the words typed.
const output = (args: string, text: string, surface: (typeof SURFACES)[number]) =>
  ({
    plugin: 'se',
    surface,
    component: 'CommandOutput',
    requestId: `row ${args}`,
    props: { command: 'se', args, text, isErrored: false },
  }) as const

test('/se help draws its groups and two columns on every surface', async ($, on) => {
  world(on)
  await $.session.start(starts)
  const said = await $.command.run(se('help'))
  expect(said?.text).toBe(HELP)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount(output('help', HELP, surface))
    expect((await ui.find({ key: 'usage' }))?.text).toBe('/se <command> [flags]')
    expect((await ui.find({ key: 'group Issues' }))?.text).toContain('Issues')
    expect((await ui.find({ key: 'group Session' }))?.text).toContain('Session')
    const row = await ui.find({ key: 'command issue pull' })
    expect(row?.props.flexDirection).toBe('row')
    // Two columns: the name in a box as wide as every row's, the summary beside it.
    const [name, summary] = (row?.children ?? []) as { props: { width?: number } }[]
    expect(name?.props.width).toBe('issue pull'.length + 2)
    expect((await ui.find({ key: 'command on' }))?.children[0]).toMatchObject({ props: { width: 12 } })
    expect(JSON.stringify(summary)).toContain('name the next se issue')
    expect((await ui.find({ key: 'note' }))?.text).toBe('/se help <command> shows its usage and flags.')
    await ui.unmount()
  }
})

test('/se help <command> draws its usage and one row per flag on every surface', async ($, on) => {
  world(on)
  await $.session.start(starts)
  const said = await $.command.run(se('help issue pull'))
  for (const surface of SURFACES) {
    const ui = await $.ui.mount(output('help issue pull', said?.text ?? '', surface))
    expect((await ui.find({ key: 'usage' }))?.text).toBe('/se issue pull [--take [N]]')
    expect((await ui.find({ key: 'about' }))?.text).toBe('Name the next ready se issue.')
    expect((await ui.find({ key: 'flag --take' }))?.text).toContain('claim the next ready issue')
    expect((await ui.find({ key: 'flag --workspace DIR' }))?.children[0]).toMatchObject({
      props: { width: '--workspace DIR'.length + 2 },
    })
    expect(await ui.find({ key: 'group Issues' })).toBeUndefined()
    await ui.unmount()
  }
})

test('a /se answer that is no help is drawn as its text', async ($, on) => {
  world(on)
  await $.session.start(starts)
  await $.command.run(se('help'))
  const said = await $.command.run(se('status'))
  for (const surface of SURFACES) {
    const ui = await $.ui.mount(output('status', said?.text ?? '', surface))
    expect(await ui.find({ key: 'usage' })).toBeUndefined()
    expect(JSON.stringify(await ui.drawn())).toContain('No SE daemon answers for /work.')
    await ui.unmount()
    // An errored help row is drawn as its text too.
    const errored = await $.ui.mount({
      ...output('help', 'se help: failed', surface),
      props: { command: 'se', args: 'help', text: 'se help: failed', isErrored: true },
    })
    expect(await errored.find({ key: 'usage' })).toBeUndefined()
    await errored.unmount()
  }
})

test('a line that no longer answers help draws as its text', async ($, on) => {
  const w = world(on)
  await $.session.start(starts)
  await $.command.run(se('help'))
  w.replies.help = { text: 'se has moved on.' }
  await $.command.run(se('help'))
  const ui = await $.ui.mount(output('help', 'se has moved on.', 'desktop'))
  expect(await ui.find({ key: 'usage' })).toBeUndefined()
})

test('the context carries the guidance se answers, asked once, and again after a compaction', async ($, on) => {
  const w = world(on)
  w.replies['guidance --session-id s1'] = { text: 'the principles, and the skills handed over' }
  await $.session.start(starts)
  const blocks = async () => (await $.prompt.context({ blocks: [{ name: 'currentDate', text: 'today' }] })).blocks
  expect(await blocks()).toEqual([
    { name: 'currentDate', text: 'today' },
    { name: 'se-guidance', text: 'the principles, and the skills handed over' },
  ])
  await blocks()
  expect(verbs(w).filter(v => v.startsWith('/se guidance'))).toEqual(['/se guidance --session-id s1'])
  // SE is off: the guidance goes into the context all the same, and nothing is posted.
  expect(posted(w)).toEqual([])
  await $.session.compact({
    trigger: 'manual',
    messages: [{ role: 'user', text: 'all so far', toolUses: [] }],
  } as never)
  w.replies['guidance --session-id s1'] = { text: 'the skills handed over, again' }
  expect((await blocks()).at(-1)).toEqual({ name: 'se-guidance', text: 'the skills handed over, again' })
  expect(verbs(w).filter(v => v.startsWith('/se guidance'))).toHaveLength(2)
})

test('guidance se answers empty adds no block', async ($, on) => {
  const w = world(on)
  w.replies['guidance --session-id s1'] = { text: '' }
  await $.session.start(starts)
  expect((await $.prompt.context({ blocks: [] })).blocks).toEqual([])
})

// A cloud session no person attends, as a routine starts it.
const BOX = { CLAUDE_CODE_REMOTE: 'true', CLAUDE_CODE_SESSION_ATTENDED: '0' }
const hooked = (w: World) => w.ran.filter(argv => argv[1] === 'hook').map(argv => argv.slice(1).join(' '))

test('a box whose issue is not closed is refused its stop, with the reason se gives', async ($, on) => {
  const w = world(on, BOX)
  await $.session.start(starts)
  w.verdict = { block: '#3 is open with neither a PR from issue-3 nor a supersede.' }
  expect((await $.classic.Stop({ stop_hook_active: false })).block).toBe(
    '#3 is open with neither a PR from issue-3 nor a supersede.',
  )
  w.verdict = { pass: '#3 is closed' }
  expect((await $.classic.Stop({ stop_hook_active: true })).block).toBeUndefined()
  expect(hooked(w)).toEqual([`hook stop --workspace ${ROOT}`, `hook stop --workspace ${ROOT}`])
})

test('an interactive session is never refused, and runs no check', async ($, on) => {
  const w = world(on)
  await $.session.start(starts)
  w.verdict = { block: 'refused' }
  expect((await $.classic.Stop({ stop_hook_active: false })).block).toBeUndefined()
  expect(
    (
      await $.classic.SubagentStop({
        stop_hook_active: false,
        agent_id: 'a',
        agent_type: 'x',
        agent_transcript_path: '/t',
      })
    ).block,
  ).toBeUndefined()
  await $.prompt.submit({ text: 'hi', origin: { kind: 'composer' } } as never)
  expect(hooked(w)).toEqual([])
})

test('a box waiting on background work says so, and a sub-agent names its transcript', async ($, on) => {
  const w = world(on, BOX)
  await $.session.start(starts)
  await $.classic.Stop({ stop_hook_active: false, background_tasks: [{}] as never })
  w.verdict = { block: '#6 is open' }
  const sub = await $.classic.SubagentStop({
    stop_hook_active: false,
    agent_id: 'a',
    agent_type: 'x',
    agent_transcript_path: '/t/a.jsonl',
  })
  expect(sub.block).toBe('#6 is open')
  expect(hooked(w)).toEqual([
    `hook stop --waiting --workspace ${ROOT}`,
    `hook stop --agent-transcript /t/a.jsonl --workspace ${ROOT}`,
  ])
})

test('a broken check lets the stop through and says why', async ($, on) => {
  const w = world(on, BOX)
  await $.session.start(starts)
  w.verdict = 1
  expect((await $.classic.Stop({ stop_hook_active: false })).block).toBeUndefined()
  expect(w.toasts).toContain('SE could not judge this stop: se: boom')
  w.verdict = 'no verdict'
  expect((await $.classic.Stop({ stop_hook_active: false })).block).toBeUndefined()
})

test('a prompt from a person resets the refusals of a box; its own prompts do not', async ($, on) => {
  const w = world(on, BOX)
  await $.session.start(starts)
  await $.prompt.submit({ text: 'go on', origin: { kind: 'scheduled-trigger' } } as never)
  expect(hooked(w)).toEqual([])
  await $.prompt.submit({ text: 'stop here', origin: { kind: 'bridge' } } as never)
  expect(hooked(w)).toEqual([`hook prompt --workspace ${ROOT}`])
})
