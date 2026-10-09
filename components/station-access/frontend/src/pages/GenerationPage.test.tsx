// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { generationApi, type GenerationProvenance } from '../api'
import { GenerationPage } from './GenerationPage'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

const value: GenerationProvenance = {
  schema: 1,
  generation: 'generation-1',
  evidence_state: 'available',
  source_material: 'verified',
  archive: {
    mirror: 'mirror-a', snapshot: 'snapshot-a', collection: 'root-filesystems',
    digest: 'a'.repeat(64), name: 'Zog rootfs', size_bytes: 10,
    availability: 'present', provenance: 'source-export', approval: 'approved',
    observed_at: '2026-10-07T00:00:00Z',
  },
  license_summary: {
    state: 'available', review: 'reviewed', bundle_digest: 'b'.repeat(64),
    notice_digest: 'c'.repeat(64), notice_bytes: 10, package_count: 1,
    issue_count: 0, coverage: 'recorded', source_material: 'verified',
  },
  coverage: {
    source_provenance: { state: 'complete', complete: 1, total: 1 },
    license_evidence: { state: 'complete', complete: 1, total: 1 },
    unresolved_provenance: 0,
  },
  packages: [{
    package: 'python', version: '3.13', revision: null, stage: 'final', scope: 'package',
    source_digest: 'd'.repeat(64), origin: 'https://python.org/source', expression: 'PSF-2.0',
    review: 'reviewed', exceptions: [], issues: [], notice_count: 1, receipt_digest: null,
    source_complete: true, license_complete: true,
    patches: { state: 'not-integrated', count: null, items: [] },
  }],
  patches: { state: 'not-integrated', count: null, items: [] },
  build_evidence: { state: 'not-integrated' },
}

function page() {
  return render(<MemoryRouter initialEntries={['/generations/generation-1?mirror=mirror-a&snapshot=snapshot-a&collection=root-filesystems&digest='+value.archive.digest]}>
    <Routes><Route path="/generations/:generation" element={<GenerationPage/>}/></Routes>
  </MemoryRouter>)
}

test('shows coverage and package provenance without inventing patch/build evidence', async () => {
  vi.spyOn(generationApi, 'detail').mockResolvedValue(value)
  page()
  expect((await screen.findAllByText('1 / 1 complete')).length).toBe(2)
  expect(screen.getAllByText(/Source: Complete|License: Complete/).length).toBe(2)
  expect(screen.getByText('python 3.13')).toBeTruthy()
  expect(screen.getByText('Source & license')).toBeTruthy()
  const exportLink = screen.getByRole('link', { name: 'Export provenance (.json)' })
  expect(exportLink.getAttribute('href')).toContain('/api/archives/generations/generation-1/export/?')
  expect(exportLink.getAttribute('href')).toContain('mirror=mirror-a')
  expect(exportLink.getAttribute('href')).toContain('snapshot=snapshot-a')
  expect(exportLink.getAttribute('href')).toContain('collection=root-filesystems')
  expect(exportLink.getAttribute('href')).toContain('digest=' + 'a'.repeat(64))
  expect(screen.getAllByText('Patch evidence unavailable').length).toBeGreaterThanOrEqual(2)
  expect(screen.getByText(/Build-record\/build-trace evidence is not yet integrated/)).toBeTruthy()
})

test('unknown evidence is explicit rather than rendered as zero', async () => {
  vi.spyOn(generationApi, 'detail').mockResolvedValue({
    ...value,
    evidence_state: 'missing',
    coverage: {
      source_provenance: { state: 'unknown', complete: null, total: null },
      license_evidence: { state: 'unknown', complete: null, total: null },
      unresolved_provenance: null,
    },
    packages: [],
  })
  page()
  await screen.findByText(/Coverage remains unknown/)
  expect(screen.getAllByText('Unknown').length).toBeGreaterThanOrEqual(3)
  expect(screen.queryByText('0 / 0 complete')).toBeNull()
})
