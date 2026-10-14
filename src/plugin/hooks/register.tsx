// SE's bridgehead. It registers one command, /se, and holds no list of what
// /se does: it hands the words typed after /se to the se binary, which answers
// the text to show and the effects to apply (switch this session on or off,
// where the daemon now answers, reload the plugins). While SE is on, every
// event the engine raises is posted to the workspace's se daemon before it
// goes on, unchanged. The daemon owns what happens to it: today it appends
// the event to the session's log. While SE is off, every hook hands the event
// straight on and contacts nothing, but one: the plugin's SessionStart hook
// puts the guidance se answers into the context (the principles; in a box, the
// box's agent; the skills a take handed over), on or off, at startup, resume,
// clear and compact, since a plugin can ship no rules and no CLAUDE.md. /se ui
// opens a grid of buttons: the on/off toggle and the commands se offers as
// buttons, each labelled with its name and pressed as /se <words>, at most as
// many to a row as se says (gridOf).
// In a box, SE on or off, every Stop and SubagentStop goes to se hook stop,
// which refuses the stop while the issue the box took is open, its PR not
// merged nor the issue superseded; a prompt from a person resets its count.
// An interactive session runs none of it.
// /se help draws as a layout: se answers the help as data beside its text, and
// the command's output row draws that data, headings and two aligned columns.
// Anything a person waits on gives feedback within a second and never blocks:
// every call into se goes through within, which shows the call is working at
// the one-second mark and lets the session go on; and while SE is on, each
// call's duration is a row of the daemon's log, se.call, and each hook's, se.hook.

import type { EngineInterface, Register, Timer } from 'claude-code'

import type { SeActive, SeButtons, SeColumns, SeHelp } from '../types'

const ACTIVE = { plugin: 'se', key: 'active' } as const
// The commands se offered as buttons when /se ui last opened the pane.
const BUTTONS = { plugin: 'se', key: 'buttons' } as const
// The most buttons a row of the pane holds, as se answered it with the buttons.
const COLUMNS = { plugin: 'se', key: 'columns' } as const
const PANE = 'se-ui'
// The help se answered for each /se line that asked for it, by its words.
const HELPS = { plugin: 'se', key: 'helps' } as const
// The folder the daemon owns in a workspace, and its endpoint record there.
export const RUNTIME = '.se/.runtime'
const ENDPOINT = `${RUNTIME}/daemon.json`
// How long a start may take: a first start builds se from the checkout.
const STARTING = 300_000
// How long the update at session start may take: a pull and a rebuild.
const UPDATING = 120_000
// A daemon found down is started again at most this often.
const RESTART_EVERY = 60_000
// What a person waits on shows it is working after this long, and holds nothing up.
export const FEEDBACK = 1_000
// How long se hook stop may take to judge a box's stop: a few reads of GitHub.
const JUDGING = 60_000

type Endpoint = { address: string; token: string }

// What the plugin tells se on every session call (see src/cmd/se/commit.go).
const HOOKS_COMMIT = 'SE_HOOKS_COMMIT'
const PLUGIN_CHECKOUT = 'SE_PLUGIN_CHECKOUT'

// What se --session answers: the text to show and the effects to apply.
export type Reply = {
  text: string
  active?: boolean
  endpoint?: Endpoint
  reload?: boolean
  panel?: { buttons: SeButtons; columns: SeColumns }
  help?: SeHelp
}

// The module's copy of the flag, so an event costs nothing while SE is off.
// $.state holds the session's value across a reload; session.start reads it back.
let active: SeActive = false
// The commit of the checkout these hooks were loaded from, read as they load.
// It lives in the module, not $.state, so a reload shows the new one.
let hooksCommit = ''
let root = ''
let endpoint: Endpoint | null = null
// When the plugin last started the daemon; -Infinity while it never did.
let lastStart = -Infinity
// The one start in flight, which every caller finding the daemon down awaits.
let starting: Promise<string> | null = null
// Events raised while a start runs, the start's own among them, sent once it answers.
const waiting: string[] = []
const WAITING_CAP = 1000
// The session start's update and daemon start, while they run past session.start's answer.
let settingUp: Promise<void> | null = null
// What the status line says is working, one line per call still running past FEEDBACK.
const working: string[] = []
// The sources of a session start whose context the guidance goes into: each
// starts a context that holds none of it yet.
const GUIDED = ['startup', 'resume', 'clear', 'compact']
// How long a session start waits for the guidance: it shows it is working
// after FEEDBACK, and the first prompt goes on without it after this long.
const GUIDING = 30_000

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const began = await $.clock.now()
    await $.command.register({
      name: 'se',
      description: 'SE, the session-event daemon: /se help lists what it does',
      argumentHint: '<command>',
    })
    root = e.cwd
    // Before the update, which may move the checkout under these hooks.
    hooksCommit = await headOf($)
    // A setup that fails leaves the session as it is; the session goes on either way.
    const setup = setsUp($).catch(() => {})
    settingUp = setup
    await within($, 'updating itself', setup)
    took($, 'session.start', began)
    return next(e)
  })

  on('command.run', { command: 'se' }, async ($, e) => {
    const began = await $.clock.now()
    const text = await runs($, e.args)
    took($, 'command.run se', began)
    return { text }
  })

  // Always-on guidance: the documented way a plugin puts text into every
  // session, the SessionStart hook's additionalContext, on each source that
  // starts a context without it (a compaction keeps only a summary of it).
  on('classic.SessionStart', async ($, e, next) => {
    const result = await next(e)
    if (!GUIDED.includes(e.source)) return result
    const began = await $.clock.now()
    const text = await guided($)
    took($, 'classic.SessionStart', began)
    return text ? { ...result, additionalContext: [...(result.additionalContext ?? []), text] } : result
  })

  // Every surface draws Box, Text and Button, the phone too, so the pane uses no other.
  // The pane is a grid: rows of at most `columns` cells, every cell as wide as
  // every other, so the columns align and a short last row stays to the left.
  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const began = await $.clock.now()
    const { Box, Button } = $.ui.resolve(e)
    const { value: isOn = false } = await $.state.get(ACTIVE)
    const { value: buttons = [] } = await $.state.get(BUTTONS)
    const { value: columns = 0 } = await $.state.get(COLUMNS)
    const toggle = isOn ? 'SE on' : 'SE off'
    const cells = [
      <Button
        key="toggle"
        label={toggle}
        variant={isOn ? 'primary' : undefined}
        dimColor={!isOn}
        onPress={() => presses($, isOn ? 'off' : 'on')}
      />,
      ...buttons.map(name => <Button key={`run ${name}`} label={name} onPress={() => presses($, name)} />),
    ]
    const grid = gridOf([toggle, ...buttons], columns, e.props.bodyColumns)
    took($, 'ui.render Pane', began)
    return (
      <Box flexDirection="column" rowGap={GAP} width={e.props.bodyColumns}>
        {grid.rows.map(row => (
          // A row is named by its first cell, the same cell each time it is drawn.
          <Box key={`row ${row[0]}`} flexDirection="row" columnGap={GAP}>
            {row.map(i => (
              <Box key={`cell ${i}`} width={grid.width} flexShrink={0}>
                {cells[i]}
              </Box>
            ))}
          </Box>
        ))}
      </Box>
    )
  })

  // /se help's output row: the help se answered as data, drawn as a layout. A
  // row whose words carried no help, or an error, is drawn as its text.
  on('ui.render', { component: 'CommandOutput', props: { command: 'se' } }, async ($, e, next) => {
    const began = await $.clock.now()
    if (e.props.isErrored) return next(e)
    const { value: helps = {} } = await $.state.get(HELPS)
    const help = helps[wordsOf(e.props.args).join(' ')]
    if (!help) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    const groups = help.groups ?? []
    const flags = help.flags ?? []
    // The left column is as wide as its longest name, and two cells more.
    const left =
      2 + Math.max(0, ...groups.flatMap(g => g.commands.map(c => c.name.length)), ...flags.map(f => f.name.length))
    const row = (key: string, name: string, about: string) => (
      <Box key={key} flexDirection="row">
        <Box width={left} flexShrink={0}>
          <Text color="suggestion">{name}</Text>
        </Box>
        <Box flexGrow={1} flexShrink={1}>
          <Text>{about}</Text>
        </Box>
      </Box>
    )
    const parts = []
    if (help.usage) {
      parts.push(
        <Box key="usage">
          <Text bold>{help.usage}</Text>
        </Box>,
      )
    }
    if (help.about) {
      parts.push(
        <Box key="about">
          <Text>{help.about}</Text>
        </Box>,
      )
    }
    for (const g of groups) {
      parts.push(
        <Box key={`group ${g.name}`} flexDirection="column">
          <Text bold>{g.name}</Text>
          {g.commands.map(c => row(`command ${c.name}`, c.name, c.summary))}
        </Box>,
      )
    }
    if (flags.length > 0) {
      parts.push(
        <Box key="flags" flexDirection="column">
          <Text bold>Flags</Text>
          {flags.map(f => row(`flag ${f.name}`, f.name, f.usage))}
        </Box>,
      )
    }
    if (help.note) {
      parts.push(
        <Box key="note">
          <Text dimColor>{help.note}</Text>
        </Box>,
      )
    }
    took($, 'ui.render CommandOutput', began)
    return (
      <Box flexDirection="column" rowGap={1}>
        {parts}
      </Box>
    )
  })

  // A box that takes an issue closes it: se judges each stop of a box (see
  // src/cmd/se/hook.go). A stop that waits on background work comes back.
  on('classic.Stop', async ($, e, next) => {
    const result = await next(e)
    if (!(await isBox($))) return result
    const began = await $.clock.now()
    const block = await judges($, waits(e) ? ['--waiting'] : [])
    took($, 'classic.Stop', began)
    return block ? { ...result, block } : result
  })
  on('classic.SubagentStop', async ($, e, next) => {
    const result = await next(e)
    if (!(await isBox($))) return result
    const began = await $.clock.now()
    const block = await judges($, [...(waits(e) ? ['--waiting'] : []), '--agent-transcript', e.agent_transcript_path])
    took($, 'classic.SubagentStop', began)
    return block ? { ...result, block } : result
  })
  // A person who prompts a box gives the Stop hook's refusals a fresh count.
  on('prompt.submit', async ($, e, next) => {
    const kind = e.origin?.kind
    if ((kind === 'composer' || kind === 'bridge') && (await isBox($))) {
      const began = await $.clock.now()
      await asksPlain($, ['hook', 'prompt'])
      took($, 'prompt.submit', began)
    }
    return next(e)
  })

  // The bridge never holds an event up for good: a failure here passes it on.
  // Events raised while the session start's setup runs wait for it: sent if it
  // switched SE on, dropped if not.
  on('*', async ($, e, next) => {
    if (next.is('engine.create', e) || (!active && !settingUp)) return next(e)
    const began = await $.clock.now()
    if (!active) {
      if (waiting.length < WAITING_CAP) waiting.push(bodyOf(await $.session.id(), next.event, e, await $.clock.now()))
      return next(e)
    }
    await within(
      $,
      'reaching its daemon',
      forwards($, next.event, e).catch(() => {}),
    )
    took($, '*', began)
    return next(e)
  }).catch(($, e, next) => next(e))
}

// The session start's road: the update, then SE on as this session last had
// it (or as SE_DEFAULT says), its daemon started.
async function setsUp($: EngineInterface): Promise<void> {
  try {
    await updatesItself($)
    const { value } = await $.state.get(ACTIVE)
    if (value === undefined) {
      if ((await $.env.get('SE_DEFAULT')) === 'on') await switchOn($)
    } else {
      active = value
      if (active) await starts($)
    }
  } finally {
    settingUp = null
    if (!active) waiting.splice(0)
  }
}

// The hard rule, kept in this one place: work a person waits on that is not
// done within FEEDBACK shows on the status line that it is working, and the
// caller goes on without it. Answers the work's value when it was done in time,
// else the work itself, to finish in the background.
async function within<T>(
  $: EngineInterface,
  doing: string,
  work: Promise<T>,
): Promise<{ done: true; value: T } | { done: false; later: Promise<T> }> {
  let timer: Timer | undefined
  const late = new Promise<null>(resolve => {
    timer = $.clock.after(FEEDBACK, () => resolve(null))
  })
  const first = await Promise.race([work.then(value => ({ value })), late])
  if (first) {
    timer?.cancel()
    return { done: true, value: first.value }
  }
  const line = `se: ${doing}…`
  working.push(line)
  $.ui.status(line)
  const later = work.finally(() => {
    working.splice(working.indexOf(line), 1)
    $.ui.status(working.at(-1))
  })
  return { done: false, later }
}

// Times one call into se and, while SE is on, records it in the daemon's log as an se.call row.
async function timed<T>($: EngineInterface, words: string[], call: () => Promise<T>): Promise<T> {
  const began = await $.clock.now()
  try {
    return await call()
  } finally {
    const ms = (await $.clock.now()) - began
    if (active) await forwards($, 'se.call', { words, ms }).catch(() => {})
  }
}

// Records how long a hook took since began on the clock, while SE is on, as
// an se.hook row of the daemon's log, without waiting on the post. A hook
// measures its own work up to handing the event on. spec/budgets.yaml gives
// each hook a class by the name it passes here, and se rules fails on a hook
// it does not.
function took($: EngineInterface, hook: string, began: number): void {
  const to = endpoint
  if (!active || !to) return
  void Promise.all([$.clock.now(), $.session.id()])
    .then(([now, session]) => posts($, to, bodyOf(session, 'se.hook', { hook, ms: now - began }, now)))
    .catch(() => {})
}

// Brings the checkout the plugin was loaded from to the newest main, whether or
// not SE is on. se leaves a checkout that is no clean main alone; nothing here
// holds the session up: what happened, if anything, is one line in a toast,
// and a reload, when the update brought a new SE, waits until session.start has answered.
async function updatesItself($: EngineInterface): Promise<void> {
  const asked = await asks($, ['update', '--session-start', '--repo', checkoutOf($)], UPDATING)
  const said = typeof asked === 'string' ? `SE did not update itself: ${asked}` : await applies($, asked)
  if (said) $.ui.toast(said.split('\n')[0])
}

// The guidance se answers for this session; '' where se failed, or did not
// answer within GUIDING. Past FEEDBACK the status line says it is working.
async function guided($: EngineInterface): Promise<string> {
  const asking = asks($, ['guidance', '--session-id', await $.session.id()]).then(said =>
    typeof said === 'string' ? '' : said.text,
  )
  const ran = await within($, 'reading its guidance', asking)
  if (ran.done) return ran.value
  let timer: Timer | undefined
  const late = new Promise<string>(resolve => {
    timer = $.clock.after(GUIDING, () => resolve(''))
  })
  const text = await Promise.race([ran.later, late])
  timer?.cancel()
  return text
}

// Hands the words to se as a session call; answers its reply, or why there is none.
async function asks($: EngineInterface, words: string[], timeoutMs = STARTING): Promise<Reply | string> {
  try {
    const bin = await builds($)
    if (bin.failed) return bin.failed
    root = await $.session.root()
    const ran = await timed($, words, () =>
      $.process.run([bin.path, '--session', '--workspace', root, ...words], {
        timeoutMs,
        env: { [HOOKS_COMMIT]: hooksCommit, [PLUGIN_CHECKOUT]: checkoutOf($) },
      }),
    )
    const said = parsed(ran.stdout) as Reply | null
    if (typeof said?.text !== 'string') return `se did not answer: ${failed(ran)}`
    return said
  } catch (error) {
    return `se did not answer: ${String(error)}`
  }
}

// A box is a cloud session no person attends, as a routine starts it; se
// hook stop reads the same two variables.
async function isBox($: EngineInterface): Promise<boolean> {
  return (await $.env.get('CLAUDE_CODE_REMOTE')) === 'true' && (await $.env.get('CLAUDE_CODE_SESSION_ATTENDED')) === '0'
}

// Whether the session has work in flight, or a wake-up, that brings it back.
function waits(e: { background_tasks?: unknown[]; session_crons?: unknown[] }): boolean {
  return (e.background_tasks?.length ?? 0) + (e.session_crons?.length ?? 0) > 0
}

// Runs se with these words outside a session call; answers what it printed,
// or why it did not answer.
async function asksPlain($: EngineInterface, words: string[]): Promise<{ stdout: string } | { failed: string }> {
  try {
    const bin = await builds($)
    if (bin.failed) return { failed: bin.failed }
    root = await $.session.root()
    const ran = await $.process.run([bin.path, ...words, '--workspace', root], { timeoutMs: JUDGING })
    if (ran.exitCode !== 0) return { failed: failed(ran) }
    return { stdout: String(ran.stdout ?? '') }
  } catch (error) {
    return { failed: String(error) }
  }
}

// se hook stop's verdict: the reason the stop is refused, or '' to let it be.
// A check that cannot run lets the turn end and says why in a toast.
async function judges($: EngineInterface, words: string[]): Promise<string> {
  const ran = await asksPlain($, ['hook', 'stop', ...words])
  const said = 'stdout' in ran ? (parsed(ran.stdout) as { block?: string; pass?: string } | null) : null
  if (said && (typeof said.block === 'string' || typeof said.pass === 'string')) return said.block ?? ''
  $.ui.toast(`SE could not judge this stop: ${'failed' in ran ? ran.failed : 'se answered no verdict'}`.split('\n')[0])
  return ''
}

// Applies se's effects to this session and answers the text to show.
async function applies($: EngineInterface, reply: Reply): Promise<string> {
  if (reply.endpoint?.address) {
    endpoint = { address: reply.endpoint.address, token: reply.endpoint.token }
    for (const body of waiting.splice(0)) await posts($, endpoint, body)
  }
  if (typeof reply.active === 'boolean') {
    // An on that found no daemon tries again on the road, not at once.
    if (reply.active) lastStart = await $.clock.now()
    active = reply.active
    await $.state.set(ACTIVE, reply.active)
  }
  if (reply.panel) {
    await $.state.set(BUTTONS, reply.panel.buttons)
    await $.state.set(COLUMNS, reply.panel.columns)
    await $.ui.open({ id: PANE, title: 'SE' })
  }
  if (!reply.reload) return reply.text
  // A command.run hook cannot run another command: the reload waits until this one has answered.
  $.clock.after(0, async () => {
    try {
      await $.command.run({ command: 'reload-plugins', args: '' } as never)
    } catch {
      await $.ui.toast('SE updated; run /reload-plugins to load it.')
    }
  })
  return `${reply.text} The plugins reload now.`
}

// /se <words>: hands the words to se and applies its reply; answers the text
// to show. One se does not answer within FEEDBACK answers that it is working,
// and its answer follows as a line of the transcript.
async function runs($: EngineInterface, args: string): Promise<string> {
  const words = wordsOf(args)
  const typed = ['/se', ...words].join(' ')
  const ran = await within($, typed, answers($, words))
  if (ran.done) return ran.value
  void ran.later.then(text => $.ui.log(text))
  return `${typed} is still working; its answer follows here.`
}

// Hands the words to se and applies its reply; answers the text to show.
// Help se answered is kept for the output row to draw; a line that no longer
// answers help draws as its text.
async function answers($: EngineInterface, words: string[]): Promise<string> {
  const asked = await asks($, words)
  if (typeof asked === 'string') return asked
  const key = words.join(' ')
  const { value: helps = {} } = await $.state.get(HELPS)
  if (asked.help) await $.state.set(HELPS, { ...helps, [key]: asked.help })
  else if (key in helps) {
    const { [key]: _, ...rest } = helps
    await $.state.set(HELPS, rest)
  }
  return applies($, asked)
}

// The cells between two cells of the pane's grid, across and down.
const GAP = 1

// What the terminal draws around a Button's label: `[ label ]`.
const CHROME = 4

// The pane's grid, the one place its shape is drawn: the cells, by their
// labels, in rows of at most `columns` (se's config value; one row where se
// named none), every cell the same width: the row's share of the pane less
// its gaps, or the longest label's button where that is wider.
export function gridOf(labels: string[], columns: number, paneWidth: number): { rows: number[][]; width: number } {
  const count = labels.length
  const across = Math.max(1, Math.min(columns > 0 ? columns : count, count))
  const rows: number[][] = []
  for (let i = 0; i < count; i += across)
    rows.push(Array.from({ length: Math.min(across, count - i) }, (_, j) => i + j))
  const share = Math.floor((paneWidth - GAP * (across - 1)) / across)
  return { rows, width: Math.max(share, CHROME + Math.max(0, ...labels.map(l => l.length))) }
}

function wordsOf(args: string): string[] {
  return args.split(/\s+/).filter(Boolean)
}

// A press runs what typing /se <words> runs; its answer is a line of the
// transcript, where a command's answer shows. (A plugin's $.command.run skips
// the plugin's own hooks, so it cannot reach /se.)
async function presses($: EngineInterface, words: string): Promise<void> {
  $.ui.log(await runs($, words))
}

// Switches SE on and starts the daemon; answers why the daemon did not start, or ''.
async function switchOn($: EngineInterface): Promise<string> {
  active = true
  // The start begins before anything else raises an event, so those events wait for it.
  const started = starts($)
  await $.state.set(ACTIVE, true)
  return started
}

// The start road, run once however many callers ask at the same time.
function starts($: EngineInterface): Promise<string> {
  starting ??= startsOnce($).finally(() => {
    starting = null
  })
  return starting
}

// Build se where it is missing, then have it start the workspace's daemon.
async function startsOnce($: EngineInterface): Promise<string> {
  lastStart = await $.clock.now()
  root = await $.session.root()
  try {
    const { path: bin, failed: unbuilt } = await builds($)
    if (unbuilt) return unbuilt
    const ran = await timed($, ['start'], () =>
      $.process.run([bin, 'start', '--workspace', root], { timeoutMs: STARTING }),
    )
    const said = parsed(ran.stdout) as Endpoint | null
    if (ran.exitCode !== 0 || !said?.address) return failed(ran)
    endpoint = { address: said.address, token: said.token }
    for (const body of waiting.splice(0)) await posts($, endpoint, body)
    return ''
  } catch (error) {
    return String(error)
  }
}

// Posts the event to the daemon. A daemon that moved (restarted, or started
// under the debugger) is found again through daemon.json; one that is gone is
// started again, at most once a minute.
async function forwards($: EngineInterface, event: string, e: unknown): Promise<void> {
  const body = bodyOf(await $.session.id(), event, e, await $.clock.now())
  if (endpoint && (await posts($, endpoint, body))) return
  // An event that waited on the start would hold up the start's own events.
  if (starting) {
    if (waiting.length < WAITING_CAP) waiting.push(body)
    return
  }
  endpoint = await recorded($)
  if (endpoint && (await posts($, endpoint, body))) return
  if ((await $.clock.now()) - lastStart < RESTART_EVERY) return
  if (!(await starts($)) && endpoint) await posts($, endpoint, body)
}

async function posts($: EngineInterface, to: Endpoint, body: string): Promise<boolean> {
  try {
    const said = await $.http.fetch(`http://${to.address}/event`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: `Bearer ${to.token}` },
      body,
    })
    return said.ok
  } catch {
    return false
  }
}

async function recorded($: EngineInterface): Promise<Endpoint | null> {
  try {
    const said = parsed(await $.fs.read(`${root}/${ENDPOINT}`)) as Endpoint | null
    return said?.address ? { address: said.address, token: said.token } : null
  } catch {
    return null
  }
}

// The post's body: the event whole, at ms on the clock, which the daemon
// trims; one that is no JSON goes as text.
export function bodyOf(session: string, event: string, e: unknown, ms: number): string {
  const at = new Date(ms).toISOString()
  try {
    return JSON.stringify({ session, event, at, e: e ?? null })
  } catch {
    return JSON.stringify({ session, event, at, e: { unserializable: String(e) } })
  }
}

// The checkout the plugin was loaded from.
function checkoutOf($: EngineInterface): string {
  return `${$.plugin.root}/../..`
}

// The commit the plugin's checkout is at, or '' where git does not say.
async function headOf($: EngineInterface): Promise<string> {
  try {
    const ran = await $.process.run(['git', 'rev-parse', 'HEAD'], { cwd: checkoutOf($), timeoutMs: 10_000 })
    return ran.exitCode === 0 ? String(ran.stdout ?? '').trim() : ''
  } catch {
    return ''
  }
}

// se under the plugin folder, built from the checkout where it is missing,
// with the commit it was built from embedded (see src/cmd/se/commit.go).
async function builds($: EngineInterface): Promise<{ path: string; failed?: string }> {
  const path = binaryOf($.plugin.root)
  if (await $.fs.exists(path)) return { path }
  const head = await headOf($)
  const ldflags = head ? ['-ldflags', `-X main.commit=${head}`] : []
  // Go runs in src/, which holds go.mod (ModuleDir in src/internal/update/update.go).
  const built = await $.process.run(['go', 'build', ...ldflags, '-o', path, './cmd/se'], {
    cwd: `${checkoutOf($)}/src`,
    timeoutMs: STARTING,
  })
  return built.exitCode === 0 ? { path } : { path, failed: `se is not built and go build failed: ${failed(built)}` }
}

// se under the plugin folder, with the suffix a Windows build carries.
export function binaryOf(pluginRoot: string): string {
  const windows = /^[A-Za-z]:/.test(pluginRoot) || pluginRoot.includes('\\')
  return `${pluginRoot}/bin/se${windows ? '.exe' : ''}`
}

function parsed(text: unknown): unknown {
  try {
    return JSON.parse(String(text ?? '').trim())
  } catch {
    return null
  }
}

function failed(ran: { exitCode?: number; stdout?: string; stderr?: string }): string {
  return `${ran.stderr ?? ''}${ran.stdout ?? ''}`.trim() || `exit ${ran.exitCode}`
}
