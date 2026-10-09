// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { api, type Runtime } from '../api'
import { LogViewer } from './LogViewer'
const runtime: Runtime = { runtime_id: 'r1', application_name: 'worker', instance_id: 'worker-1', state: 'running', generation: 'g1', created_at: null, completed_at: null, request_id: null, fault: null, programs: [{ name: 'worker', service_name: 'worker.service', state: 'running', invocation_id: 'i1', command: [], main_pid: null, control_group: null, result: null }] }
afterEach(() => { cleanup(); vi.restoreAllMocks() })
describe('log viewer', () => {
  it('renders messages as text, filters errors, and pauses', async () => {
    vi.spyOn(api, 'logs').mockResolvedValue({ entries: [
      { cursor: '1', program: 'worker', timestamp: '2026-09-16T00:00:00Z', priority: 6, message: '<img src=x onerror=alert(1)>', invocation_id: 'i1' },
      { cursor: '2', program: 'worker', timestamp: '2026-09-16T00:00:01Z', priority: 3, message: 'Failure\nTraceback details', invocation_id: 'i1' },
    ], next_cursor: '2', has_more: false, source: 'fixture' })
    const view = render(<LogViewer runtime={runtime} />)
    await screen.findByText('<img src=x onerror=alert(1)>')
    expect(view.container.querySelector('img')).toBeNull()
    expect(screen.getByText(/Demonstration entries/)).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Severity'), { target: { value: '3' } })
    expect(screen.queryByText('<img src=x onerror=alert(1)>')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
    expect(screen.getByRole('button', { name: 'Resume' })).toBeTruthy()
  })
  it('shows unavailable API and permits explicit reload', async () => {
    const logs = vi.spyOn(api, 'logs').mockRejectedValue(new Error('Live API pending'))
    render(<LogViewer runtime={runtime} />)
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'Live API pending')
    logs.mockResolvedValue({ entries: [], next_cursor: null, has_more: false, source: 'journald' })
    fireEvent.click(screen.getByRole('button', { name: 'Reload recent' }))
    await screen.findByText('No retained entries for this stream. It may have no output, or journal history may have expired.')
    expect(screen.queryByRole('alert')).toBeNull()
  })
  it('aborts the request on unmount', async () => {
    const logs = vi.spyOn(api, 'logs').mockImplementation(() => new Promise(() => {}))
    const view = render(<LogViewer runtime={runtime} />)
    await waitFor(() => expect(logs).toHaveBeenCalledOnce())
    const signal = logs.mock.calls[0][3]
    view.unmount()
    expect(signal?.aborted).toBe(true)
  })
})
