/** Apply the native project's choice before its next turn, including resumes. */
export const name = 'deskpet-permission-mode'
export const inject = ['permissionPresets', 'agents']

export function apply(ctx, config) {
  // SDK session/prompt always uses next-turn. Promote native user input during
  // a running turn the same way DSH's own session controller steers an item.
  ctx.on('session/event', (session, event) => {
    if (session.id !== config.sessionId || event.type !== 'agent/inbox/spliced'
        || event.data.target !== 'next-turn') return
    const agent = ctx.agents.get(session.id)
    if (agent?.status !== 'running' || agent.session !== session) return
    for (const message of event.data.inserted) {
      if (message.source?.kind !== 'user') continue
      queueMicrotask(() => {
        if (ctx.agents.get(session.id) !== agent || agent.status !== 'running') return
        const queued = agent.inbox.nextTurn.find(item => item.id === message.id)
        if (queued && agent.inbox.remove(queued.id)) agent.steer(queued)
      })
    }
  })
  ctx.on('agent/pre-step', ({ agent }, next) => {
    if (agent.session.id === config.sessionId) {
      // The official Auto service must already be registered: set throws otherwise.
      // Keep ask enabled; never turn a reviewer denial into automatic permission.
      ctx.permissionPresets.set(agent.session, config.autoApprove === true ? 'auto' : 'workspace-write')
    }
    return next()
  }, { prepend: true })
}
