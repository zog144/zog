import { matchPath, useLocation } from 'react-router-dom'
import { useVncSessions } from './VncSessionProvider'

export function PersistentVncSessions() {
  const { sessions } = useVncSessions()
  const location = useLocation()
  const match = matchPath('/vnc/:workspaceId', location.pathname)
  const activeWorkspaceId = match?.params.workspaceId ?? null
  return (
    <div className="vnc-session-layer" aria-hidden={activeWorkspaceId === null}>
      {sessions.map(session => (
        <iframe
          key={session.workspaceId}
          className={`vnc-frame ${activeWorkspaceId === session.workspaceId ? 'active' : ''}`}
          src={session.novncUrl}
          title={`VNC workspace ${session.workspaceId}`}
          allow="clipboard-read; clipboard-write"
        />
      ))}
    </div>
  )
}
