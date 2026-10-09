// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, test } from 'vitest'
import type { Application, GenerationPackage } from '../api'
import { ApplicationSourceLicense, PatchStatus } from './SoftwareProvenance'

afterEach(cleanup)

const basePatch: GenerationPackage['patches'] = { state: 'not-integrated', count: null, items: [] }

test('patch state cannot silently imply an unpatched package', () => {
  const { rerender } = render(<PatchStatus value={basePatch} />)
  expect(screen.getByText('Patch evidence unavailable')).toBeTruthy()

  rerender(<PatchStatus value={{ state: 'available', count: 2, items: [
    { name: 'fix-a.patch', digest: 'a'.repeat(64), origin: null, reason: null },
    { name: 'fix-b.patch', digest: 'b'.repeat(64), origin: null, reason: null },
  ] }} />)
  expect(screen.getByText('Patched · 2')).toBeTruthy()

  rerender(<PatchStatus value={{ state: 'available', count: 0, items: [] }} />)
  expect(screen.getByText('No patches recorded')).toBeTruthy()
})

test('application cards expose the missing provenance contract without a fake link', () => {
  const application: Application = {
    name: 'browser', description: 'Browser', multi_instance: false,
    start_policy: 'externally-controlled',
    source_license: { state: 'unavailable', reason: 'application-source-identity-not-published' },
  }
  render(<ApplicationSourceLicense application={application} />)
  expect(screen.getByText('Source & license unavailable')).toBeTruthy()
  expect(screen.queryByRole('link', { name: 'Source & license' })).toBeNull()
  expect(screen.getByText('Source & license unavailable').getAttribute('title')).toMatch(/source identity is not published/i)
})
