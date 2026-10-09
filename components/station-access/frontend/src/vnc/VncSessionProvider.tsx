import { createContext, useCallback, useContext, useMemo, useState, useRef, type ReactNode } from 'react'
import { api } from '../api'

export type VncSession = { workspaceId: string; novncUrl: string; openedAt: number }
type VncContextValue = {
  sessions: VncSession[]
  open: (workspaceId: string) => Promise<void>
  close: (workspaceId: string) => void
  has: (workspaceId: string) => boolean
}
const VncContext = createContext<VncContextValue | null>(null)

export function VncSessionProvider({ children }: { children: ReactNode }) {
  const [sessions, setSessions] = useState<VncSession[]>([])
  const currentSessions = useRef(sessions)
  currentSessions.current = sessions
  const pending = useRef(new Map<string, Promise<void>>())
  const epochs = useRef(new Map<string, number>())
  const open = useCallback((workspaceId: string): Promise<void> => {
    if (currentSessions.current.some(session => session.workspaceId === workspaceId)) return Promise.resolve()
    const existing = pending.current.get(workspaceId)
    if (existing) return existing
    const epoch = epochs.current.get(workspaceId) ?? 0
    const request = api.vncGrant(workspaceId).then(grant => {
      if ((epochs.current.get(workspaceId) ?? 0) !== epoch) return
      setSessions(current => current.some(s => s.workspaceId === workspaceId)
        ? current
        : [...current, { workspaceId, novncUrl: grant.novnc_url, openedAt: Date.now() }])
    }).finally(() => { if (pending.current.get(workspaceId) === request) pending.current.delete(workspaceId) })
    pending.current.set(workspaceId, request)
    return request
  }, [])
  const close = useCallback((workspaceId: string) => {
    epochs.current.set(workspaceId, (epochs.current.get(workspaceId) ?? 0) + 1)
    pending.current.delete(workspaceId)
    setSessions(current => current.filter(s => s.workspaceId !== workspaceId))
  }, [])
  const value = useMemo(() => ({
    sessions,
    open,
    close,
    has: (id: string) => sessions.some(s => s.workspaceId === id),
  }), [sessions, open, close])
  return <VncContext.Provider value={value}>{children}</VncContext.Provider>
}

export function useVncSessions() {
  const value = useContext(VncContext)
  if (!value) throw new Error('useVncSessions must be used inside VncSessionProvider')
  return value
}
