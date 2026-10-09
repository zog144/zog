// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { api, type WorkspaceProvenance } from '../api'
import { WorkspaceProvenancePage } from './WorkspaceProvenancePage'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

const value: WorkspaceProvenance = {
  schema: 1,
  basis: 'immutable-runtime-history',
  administrator_generation_details: true,
  workspace: { id: 'desk-1', number: 1, name: 'Research' },
  runtimes: [{
    runtime_id: 'runtime-1',
    application: 'editor',
    instance_id: 'editor-one',
    role: 'application',
    state: 'running',
    generation: 'generation-old',
    created_at: 1,
    completed_at: null,
    generation_resolution: 'resolved',
    generation_digest: 'a'.repeat(64),
    generation_archive: {
      mirror: '11111111-1111-1111-1111-111111111111',
      snapshot: '22222222-2222-2222-2222-222222222222',
      collection: 'root-filesystems',
      digest: 'a'.repeat(64),
      observed_at: '2026-10-07T12:00:00+00:00',
    },
    generation_candidate_count: 1,
  }],
}

function page() {
  return render(<MemoryRouter initialEntries={['/workspaces/desk-1/provenance']}>
    <Routes><Route path="/workspaces/:workspaceId/provenance" element={<WorkspaceProvenancePage />} /></Routes>
  </MemoryRouter>)
}

test('shows immutable launched generation and exact administrator provenance link', async () => {
  vi.spyOn(api, 'workspaceProvenance').mockResolvedValue(value)
  page()
  expect(await screen.findByText('Research · Provenance')).toBeTruthy()
  expect(screen.getByText(/does not re-resolve the current application specification/)).toBeTruthy()
  expect(screen.getByText('generation-old')).toBeTruthy()
  expect(screen.getByText('Matched to an observed root filesystem')).toBeTruthy()
  const link = screen.getByRole('link', { name: 'Generation provenance' })
  expect(link.getAttribute('href')).toContain('/generations/generation-old?')
  expect(link.getAttribute('href')).toContain('snapshot=22222222-2222-2222-2222-222222222222')
  expect(link.getAttribute('href')).toContain('digest=' + 'a'.repeat(64))
})

test('owner sees resolved generation without receiving administrator detail link', async () => {
  vi.spyOn(api, 'workspaceProvenance').mockResolvedValue({
    ...value,
    administrator_generation_details: false,
    runtimes: [{ ...value.runtimes[0], generation_archive: null }],
  })
  page()
  await screen.findByText('generation-old')
  expect(screen.queryByRole('link', { name: 'Generation provenance' })).toBeNull()
  expect(screen.getByText('Detailed generation provenance is administrator-only')).toBeTruthy()
})

test('conflicting generation identity is visibly unresolved', async () => {
  vi.spyOn(api, 'workspaceProvenance').mockResolvedValue({
    ...value,
    runtimes: [{
      ...value.runtimes[0],
      generation_resolution: 'conflict',
      generation_digest: null,
      generation_archive: null,
      generation_candidate_count: 2,
    }],
  })
  page()
  expect(await screen.findByText(/Conflicting root filesystem digests observed \(2\)/)).toBeTruthy()
  expect(screen.queryByRole('link', { name: 'Generation provenance' })).toBeNull()
})
