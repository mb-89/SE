// SE's bridgehead. It registers one command, /se, and holds no list of what
// /se does: it hands the words typed after /se to the se binary, which answers
// the text to show and the effects to apply (switch this session on or off,
// where the daemon now answers, reload the plugins). While SE is on, every
// event the engine raises is posted to the workspace's se daemon before it
// goes on, unchanged. The daemon owns what happens to it: today it appends
// the event to the session's log. se owns finding and starting the daemon: an
// event that finds none asks se ensure, which answers where it is, or how long
// to wait before asking again. While SE is off, every hook hands the event
// straight on and contacts nothing. /se ui opens a pane of buttons: the on/off
// toggle and the commands se offers as buttons, each pressed as /se <words>.
// /se help draws as a layout: se answers the help as data beside its text, and
// the command's output row draws that data, headings and two aligned columns.
// Anything a person waits on gives feedback within a second and never blocks:
// every call into se goes through within, which shows the call is working at
// the one-second mark and lets the session go on; and while SE is on, each
// call's duration is a row of the daemon's log, se.call.

import type { EngineInterface, Register, Timer } from 'claude-code'

import type { SeActive, SeButtons, SeHelp } from '../types'

const ACTIVE = { plugin: 'se', key: 'active' } as const
// The commands se offered as buttons when /se ui last opened the pane.
const BUTTONS = { plugin: 'se', key: 'buttons' } as const
const PANE = 'se-ui'
// The help se answered for each /se line that asked for it, by its words.
const HELPS = { plugin: 'se', key: 'helps' } as const
// The folder the daemon owns in a workspace.
export const RUNTIME = '.se/.runtime'
// How long a start may take: a first start builds se from the checkout.
const STARTING = 300_000
// How long the update at session start may take: a pull and a rebuild.
const UPDATING = 120_000
// What a person waits on shows it is working after this long, and holds nothing up.
export const FEEDBACK = 1_000

type Endpoint = { address: string; token: string }
// What se ensure answers (Ensured in src/cmd/se/ensure.go).
type Ensured = { address?: string; token?: string; retryInMs?: number; error?: string }

// What the plugin tells se on every session call (see src/cmd/se/commit.go).
const HOOKS_COMMIT = 'SE_HOOKS_COMMIT'
const PLUGIN_CHECKOUT = 'SE_PLUGIN_CHECKOUT'

// What se --session answers: the text to show and the effects to apply.
export type Reply = {
  text: string
  active?: boolean
  endpoint?: Endpoint
  reload?: boolean
  panel?: { buttons: SeButtons }
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
// The one se ensure in flight, which every caller finding no daemon awaits.
let ensuring: Promise<string> | null = null
// Until when se said not to ask it for the daemon again, by the session's clock.
let retryAt = 0
// Events raised while se ensure runs, its own among them, sent once it answers.
// The bound only keeps the session's memory in check.
const waiting: string[] = []
const WAITING_CAP = 1000
// The session start's update and daemon start, while they run past session.start's answer.
let settingUp: Promise<void> | null = null
// What the status line says is working, one line per call still running past FEEDBACK.
const working: string[] = []

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
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
    return next(e)
  })

  on('command.run', { command: 'se' }, async ($, e) => ({ text: await runs($, e.args) }))

  // Every surface draws Box, Text and Button, the phone too, so the pane uses no other.
  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Button } = $.ui.resolve(e)
    const { value: isOn = false } = await $.state.get(ACTIVE)
    const { value: buttons = [] } = await $.state.get(BUTTONS)
    return (
      <Box flexDirection="row" flexWrap="wrap" columnGap={1} width={e.props.bodyColumns}>
        <Button
          key="toggle"
          label={isOn ? 'SE on' : 'SE off'}
          variant={isOn ? 'primary' : undefined}
          dimColor={!isOn}
          onPress={() => presses($, isOn ? 'off' : 'on')}
        />
        {buttons.map(name => (
          <Button key={`run ${name}`} label={name} onPress={() => presses($, name)} />
        ))}
      </Box>
    )
  })

  // /se help's output row: the help se answered as data, drawn as a layout. A
  // row whose words carried no help, or an error, is drawn as its text.
  on('ui.render', { component: 'CommandOutput', props: { command: 'se' } }, async ($, e, next) => {
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
    return (
      <Box flexDirection="column" rowGap={1}>
        {parts}
      </Box>
    )
  })

  // The bridge never holds an event up for good: a failure here passes it on.
  // Events raised while the session start's setup runs wait for it: sent if it
  // switched SE on, dropped if not.
  on('*', async ($, e, next) => {
    if (next.is('engine.create', e) || (!active && !settingUp)) return next(e)
    if (!active) {
      if (waiting.length < WAITING_CAP) waiting.push(bodyOf(await $.session.id(), next.event, e))
      return next(e)
    }
    await within(
      $,
      'reaching its daemon',
      forwards($, next.event, e).catch(() => {}),
    )
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
      if (active) await ensures($)
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

// Brings the checkout the plugin was loaded from to the newest main, whether or
// not SE is on. se leaves a checkout that is no clean main alone; nothing here
// holds the session up: what happened, if anything, is one line in a toast,
// and a reload, when the update brought a new SE, waits until session.start has answered.
async function updatesItself($: EngineInterface): Promise<void> {
  const asked = await asks($, ['update', '--session-start', '--repo', checkoutOf($)], UPDATING)
  const said = typeof asked === 'string' ? `SE did not update itself: ${asked}` : await applies($, asked)
  if (said) $.ui.toast(said.split('\n')[0])
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

// Applies se's effects to this session and answers the text to show.
async function applies($: EngineInterface, reply: Reply): Promise<string> {
  if (reply.endpoint?.address) {
    endpoint = { address: reply.endpoint.address, token: reply.endpoint.token }
    for (const body of waiting.splice(0)) await posts($, endpoint, body)
  }
  if (typeof reply.active === 'boolean') {
    active = reply.active
    await $.state.set(ACTIVE, reply.active)
  }
  if (reply.panel) {
    await $.state.set(BUTTONS, reply.panel.buttons)
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

function wordsOf(args: string): string[] {
  return args.split(/\s+/).filter(Boolean)
}

// A press runs what typing /se <words> runs; its answer is a line of the
// transcript, where a command's answer shows. (A plugin's $.command.run skips
// the plugin's own hooks, so it cannot reach /se.)
async function presses($: EngineInterface, words: string): Promise<void> {
  $.ui.log(await runs($, words))
}

// Switches SE on and has se find or start the daemon; answers why there is none, or ''.
async function switchOn($: EngineInterface): Promise<string> {
  active = true
  // The ensure begins before anything else raises an event, so those events wait for it.
  const ensured = ensures($)
  await $.state.set(ACTIVE, true)
  return ensured
}

// se ensure, run once however many callers ask at the same time.
function ensures($: EngineInterface): Promise<string> {
  ensuring ??= ensuresOnce($).finally(() => {
    ensuring = null
  })
  return ensuring
}

// Builds se where it is missing, then asks it for the workspace's daemon and
// applies its answer: where the daemon is, or how long to wait.
async function ensuresOnce($: EngineInterface): Promise<string> {
  root = await $.session.root()
  try {
    const { path: bin, failed: unbuilt } = await builds($)
    if (unbuilt) return unbuilt
    const ran = await timed($, ['ensure'], () =>
      $.process.run([bin, 'ensure', '--workspace', root], { timeoutMs: STARTING }),
    )
    const said = parsed(ran.stdout) as Ensured | null
    if (said?.retryInMs) retryAt = (await $.clock.now()) + said.retryInMs
    if (!said?.address) return said?.error || failed(ran)
    endpoint = { address: said.address, token: said.token ?? '' }
    for (const body of waiting.splice(0)) await posts($, endpoint, body)
    return ''
  } catch (error) {
    return String(error)
  }
}

// Posts the event to the daemon. One that does not answer is asked of se,
// no sooner than se said; the event waits for se's answer.
async function forwards($: EngineInterface, event: string, e: unknown): Promise<void> {
  const body = bodyOf(await $.session.id(), event, e)
  if (endpoint && (await posts($, endpoint, body))) return
  // An event that waited on the ensure would hold up the ensure's own events.
  if (ensuring) {
    if (waiting.length < WAITING_CAP) waiting.push(body)
    return
  }
  if ((await $.clock.now()) < retryAt) return
  if (waiting.length < WAITING_CAP) waiting.push(body)
  await ensures($)
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

// The post's body: the event whole, which the daemon trims; one that is no JSON goes as text.
export function bodyOf(session: string, event: string, e: unknown): string {
  const at = new Date().toISOString()
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

// se under the plugin folder, built from the checkout where it is missing: the
// bootstrap, plain, since Go records the commit it builds from (see src/cmd/se/commit.go).
async function builds($: EngineInterface): Promise<{ path: string; failed?: string }> {
  const path = binaryOf($.plugin.root)
  if (await $.fs.exists(path)) return { path }
  const built = await $.process.run(['go', 'build', '-o', path, './src/cmd/se'], {
    cwd: checkoutOf($),
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
