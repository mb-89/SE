// SE's session state: whether /se on holds for this session.
export type SeActive = boolean
// The commands /se ui offers as buttons, by name, as se answered them.
export type SeButtons = string[]
// The most buttons a row of /se ui holds, the toggle counted, as se answered it.
export type SeColumns = number
// The help se answered as data beside its text (Help in src/cmd/se/help.go).
export type SeHelp = {
  usage?: string
  about?: string
  groups?: { name: string; commands: { name: string; summary: string; usage: string }[] }[]
  flags?: { name: string; usage: string }[]
  note?: string
}
// The help se last answered for each /se line that asked for it, by the
// words typed after /se, which the command's output row draws.
export type SeHelps = Record<string, SeHelp>

declare module 'claude-code' {
  interface PluginState {
    se: { active: SeActive; buttons: SeButtons; columns: SeColumns; helps: SeHelps }
  }
}
