// SE's one hooks module. /se-on and /se-off switch the session flag; while it
// is on, every event the engine raises lands as one JSON line in the session's
// log under .se/.runtime, and goes on unchanged. While it is off, every hook
// hands the event straight on and touches nothing.

import type { EngineInterface, Register } from 'claude-code'

import type { SeActive } from '../types'

const ACTIVE = { plugin: 'se', key: 'active' } as const
// The folder the plugin owns in a workspace; git ignores it through the file
// /se-on writes into it.
export const RUNTIME = '.se/.runtime'
// A payload longer than this lands cut, with its full length beside it.
export const PAYLOAD_CAP = 4000
// $.fs writes whole files, so a log past this size moves on to its next part.
export const PART_CAP = 1 << 20

// The module's copy of the flag, so an event costs nothing while SE is off.
// $.state holds the session's value across a reload; session.start reads it back.
let active: SeActive = false
let root = ''
// Each log file's text as last written, since every write replaces the file.
const held = new Map<string, string>()
// The part each session's log has reached.
const parts = new Map<string, number>()
// Writes run one after another, so no row overwrites another.
let writing: Promise<void> = Promise.resolve()

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'se-on',
      description: 'Switch SE on: log every event of this session under .se/.runtime',
    })
    await $.command.register({ name: 'se-off', description: 'Switch SE off for this session' })
    root = e.cwd
    const { value } = await $.state.get(ACTIVE)
    if (value === undefined) {
      if ((await $.env.get('SE_DEFAULT')) === 'on') await switchOn($)
    } else {
      active = value
    }
    return next(e)
  })

  on('command.run', { command: 'se-on' }, async $ => {
    await switchOn($)
    return { text: `SE is on. Every event of this session is logged under ${RUNTIME}/logs.` }
  })

  on('command.run', { command: 'se-off' }, async $ => {
    active = false
    await $.state.set(ACTIVE, false)
    return { text: 'SE is off.' }
  })

  // A logger never holds an event up: a failure here passes it on.
  on('*', async ($, e, next) => {
    if (!active || next.is('engine.create', e)) return next(e)
    const logged = logs($, next.event, e).catch(() => {})
    const out = await next(e)
    await logged
    return out
  }).catch(($, e, next) => next(e))
}

async function switchOn($: EngineInterface): Promise<void> {
  active = true
  await $.state.set(ACTIVE, true)
  root = await $.session.root()
  await $.fs.write(`${root}/${RUNTIME}/.gitignore`, '*\n')
}

async function logs($: EngineInterface, event: string, e: unknown): Promise<void> {
  const line = `${JSON.stringify({ at: new Date().toISOString(), event, e: payloadOf(e) })}\n`
  const id = await $.session.id()
  const turn = writing.then(() => appends($, id, line))
  writing = turn.catch(() => {})
  return turn
}

async function appends($: EngineInterface, id: string, line: string): Promise<void> {
  let part = parts.get(id) ?? 0
  let file = fileOf(id, part)
  let text = held.get(file) ?? (await readOrEmpty($, file))
  while (text.length + line.length > PART_CAP && text.length > 0) {
    part += 1
    file = fileOf(id, part)
    text = held.get(file) ?? (await readOrEmpty($, file))
  }
  parts.set(id, part)
  text += line
  await $.fs.write(file, text)
  held.set(file, text)
}

export function fileOf(id: string, part: number): string {
  return `${root}/${RUNTIME}/logs/${id}${part ? `.${part}` : ''}.jsonl`
}

async function readOrEmpty($: EngineInterface, file: string): Promise<string> {
  try {
    return String(await $.fs.read(file))
  } catch {
    return ''
  }
}

// The event's input as the row carries it: whole while short, else its head and length.
export function payloadOf(e: unknown): unknown {
  let text: string
  try {
    text = JSON.stringify(e) ?? 'null'
  } catch {
    return { unserializable: String(e) }
  }
  if (text.length <= PAYLOAD_CAP) return e ?? null
  return { cut: true, length: text.length, head: text.slice(0, PAYLOAD_CAP) }
}
