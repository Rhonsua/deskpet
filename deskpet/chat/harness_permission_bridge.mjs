/** Apply the native project's choice before its next turn, including resumes. */
export const name = 'deskpet-permission-mode'
export const inject = ['permissionPresets']

export function apply(ctx, config) {
  ctx.on('agent/pre-step', ({ agent }, next) => {
    if (agent.session.id === config.sessionId) {
      // The official Auto service must already be registered: set throws otherwise.
      // Keep ask enabled; never turn a reviewer denial into automatic permission.
      ctx.permissionPresets.set(agent.session, config.autoApprove === true ? 'auto' : 'workspace-write')
    }
    return next()
  }, { prepend: true })
}
