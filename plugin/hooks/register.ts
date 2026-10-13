// SE's bridgehead. It registers one command, /se, and holds no list of what
// /se does: it hands the words typed after /se to the se binary, which answers
// the text to show and the effects to apply (switch this session on or off,
// where the daemon now answers, reload the plugins). While SE is on, every
// event the engine raises is posted to the workspace's se daemon before it
// goes on, unchanged. The daemon owns what happens to it: today it appends
// the event to the session's log. While SE is off, every hook hands the event
// straight on and contacts nothing.

import type { EngineInterface, Register } from 'claude-code'

import type { SeActive } from '../types'

const ACTIVE = { plugin: 'se', key: 'active' } as const
// The folder the daemon owns in a workspace, and its endpoint record there.
export const RUNTIME = '.se/.runtime'
const ENDPOINT = `${RUNTIME}/daemon.json`
// How long a start may take: a first start builds se from the checkout.
const STARTING = 300_000
// How long the update at session start may take: a pull and a rebuild.
const UPDATING = 120_000
// A daemon found down is started again at most this often.
const RESTART_EVERY = 60_000

type Endpoint = { address: string; token: string }

// What se --session answers: the text to show and the effects to apply.
export type Reply = { text: string; active?: boolean; endpoint?: Endpoint; reload?: boolean }

// The module's copy of the flag, so an event costs nothing while SE is off.
// $.state holds the session's value across a reload; session.start reads it back.
let active: SeActive = false
let root = ''
let endpoint: Endpoint | null = null
let lastStart = 0
// The one start in flight, which every caller finding the daemon down awaits.
let starting: Promise<string> | null = null
// Events raised while a start runs, the start's own among them, sent once it answers.
const waiting: string[] = []
const WAITING_CAP = 1000

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'se',
      description: 'SE, the session-event daemon: /se help lists what it does',
      argumentHint: '<command>',
    })
    root = e.cwd
    await updatesItself($)
    const { value } = await $.state.get(ACTIVE)
    if (value === undefined) {
      if ((await $.env.get('SE_DEFAULT')) === 'on') await switchOn($)
    } else {
      active = value
      if (active) await starts($)
    }
    return next(e)
  })

  on('command.run', { command: 'se' }, async ($, e) => {
    const words = e.args.split(/\s+/).filter(Boolean)
    const asked = await asks($, words)
    return { text: typeof asked === 'string' ? asked : await applies($, asked) }
  })

  // The bridge never holds an event up for good: a failure here passes it on.
  on('*', async ($, e, next) => {
    if (!active || next.is('engine.create', e)) return next(e)
    await forwards($, next.event, e).catch(() => {})
    return next(e)
  }).catch(($, e, next) => next(e))
}

// Brings the checkout the plugin was loaded from to the newest main, whether or
// not SE is on. se leaves a checkout that is no clean main alone; nothing here
// holds the session up: what happened, if anything, is one line in a toast,
// and a reload, when the update brought a new SE, waits until session.start has answered.
async function updatesItself($: EngineInterface): Promise<void> {
  const asked = await asks($, ['update', '--session-start', '--repo', `${$.plugin.root}/..`], UPDATING)
  const said = typeof asked === 'string' ? `SE did not update itself: ${asked}` : await applies($, asked)
  if (said) $.ui.toast(said.split('\n')[0])
}

// Hands the words to se as a session call; answers its reply, or why there is none.
async function asks($: EngineInterface, words: string[], timeoutMs = STARTING): Promise<Reply | string> {
  try {
    const bin = await builds($)
    if (bin.failed) return bin.failed
    root = await $.session.root()
    const ran = await $.process.run([bin.path, '--session', '--workspace', root, ...words], { timeoutMs })
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
    // An on that found no daemon tries again on the road, not at once.
    if (reply.active) lastStart = Date.now()
    active = reply.active
    await $.state.set(ACTIVE, reply.active)
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
  lastStart = Date.now()
  root = await $.session.root()
  try {
    const { path: bin, failed: unbuilt } = await builds($)
    if (unbuilt) return unbuilt
    const ran = await $.process.run([bin, 'start', '--workspace', root], { timeoutMs: STARTING })
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
  const body = bodyOf(await $.session.id(), event, e)
  if (endpoint && (await posts($, endpoint, body))) return
  // An event that waited on the start would hold up the start's own events.
  if (starting) {
    if (waiting.length < WAITING_CAP) waiting.push(body)
    return
  }
  endpoint = await recorded($)
  if (endpoint && (await posts($, endpoint, body))) return
  if (Date.now() - lastStart < RESTART_EVERY) return
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

// The post's body: the event whole, which the daemon trims; one that is no JSON goes as text.
export function bodyOf(session: string, event: string, e: unknown): string {
  const at = new Date().toISOString()
  try {
    return JSON.stringify({ session, event, at, e: e ?? null })
  } catch {
    return JSON.stringify({ session, event, at, e: { unserializable: String(e) } })
  }
}

// se under the plugin folder, built from the checkout where it is missing.
async function builds($: EngineInterface): Promise<{ path: string; failed?: string }> {
  const path = binaryOf($.plugin.root)
  if (await $.fs.exists(path)) return { path }
  const built = await $.process.run(['go', 'build', '-o', path, './cmd/se'], {
    cwd: `${$.plugin.root}/..`,
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
