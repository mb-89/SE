// SE's session state: whether /se on holds for this session.
export type SeActive = boolean

declare module 'claude-code' {
  interface PluginState {
    se: { active: SeActive }
  }
}
