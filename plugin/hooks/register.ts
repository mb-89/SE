// SE's bridgehead. /se-on and /se-off switch the session flag; while it is on,
// every event the engine raises is posted to the workspace's se daemon before
// it goes on, unchanged. The daemon owns what happens to it: today it appends
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
// A daemon found down is started again at most this often.
const RESTART_EVERY = 60_000

type Endpoint = { address: string; token: string }

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
      name: 'se-on',
      description: 'Switch SE on: forward every event of this session to the se daemon',
    })
    await $.command.register({ name: 'se-off', description: 'Switch SE off for this session' })
    await $.command.register({
      name: 'se-update',
      description: 'Update the installed SE to the newest main and reload it',
    })
    root = e.cwd
    const { value } = await $.state.get(ACTIVE)
    if (value === undefined) {
      if ((await $.env.get('SE_DEFAULT')) === 'on') await switchOn($)
    } else {
      active = value
      if (active) await starts($)
    }
    return next(e)
  })

  on('command.run', { command: 'se-on' }, async $ => {
    const why = await switchOn($)
    return {
      text: why
        ? `SE is on, but its daemon did not start: ${why}. Events pass unlogged until it does.`
        : `SE is on. Every event of this session is logged under ${RUNTIME}/logs.`,
    }
  })

  on('command.run', { command: 'se-off' }, async $ => {
    active = false
    await $.state.set(ACTIVE, false)
    return { text: 'SE is off.' }
  })

  on('command.run', { command: 'se-update' }, async $ => {
    const ran = await $.process.run([binaryOf($.plugin.root), 'update'], { timeoutMs: STARTING })
    if (ran.exitCode !== 0) return { text: `SE did not update: ${failed(ran)}` }
    const said = parsed(ran.stdout) as { from?: string; to?: string } | null
    // The daemon runs the old se until it starts again.
    await $.process.run([binaryOf($.plugin.root), 'stop', '--workspace', await $.session.root()])
    endpoint = null
    if (active) await starts($)
    const updated = `SE updated ${said?.from ?? '?'} → ${said?.to ?? '?'}`
    try {
      await $.command.run({ command: 'reload-plugins', args: '' } as never)
      return { text: `${updated} and reloaded.` }
    } catch {
      return { text: `${updated}. Run /reload-plugins to load it.` }
    }
  })

  // The bridge never holds an event up for good: a failure here passes it on.
  on('*', async ($, e, next) => {
    if (!active || next.is('engine.create', e)) return next(e)
    await forwards($, next.event, e).catch(() => {})
    return next(e)
  }).catch(($, e, next) => next(e))
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
  const bin = binaryOf($.plugin.root)
  try {
    if (!(await $.fs.exists(bin))) {
      const built = await $.process.run(['go', 'build', '-o', bin, './cmd/se'], {
        cwd: `${$.plugin.root}/..`,
        timeoutMs: STARTING,
      })
      if (built.exitCode !== 0) return `se is not built and go build failed: ${failed(built)}`
    }
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
