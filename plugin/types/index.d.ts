// SE's session state: whether /se on holds for this session.
export type SeActive = boolean
// The commands /se ui offers as buttons, by name, as se answered them.
export type SeButtons = string[]

declare module 'claude-code' {
  interface PluginState {
    se: { active: SeActive; buttons: SeButtons }
  }
}
