import { describe, expect, it } from 'vitest'
import { appendEntries, maximumEntries } from './buffer'
import type { LogEntry } from '../api'
const entry = (i: number): LogEntry => ({ cursor: `${i}`, timestamp: 'now', program: 'worker', priority: 6, message: `${i}`, invocation_id: 'test' })
describe('log buffer', () => {
  it('deduplicates overlapping pages and within a page', () => {
    expect(appendEntries([entry(1)], [entry(1), entry(2), entry(2)]).map(x => x.cursor)).toEqual(['1', '2'])
  })
  it('bounds retained entries and retains newest', () => {
    const result = appendEntries([], Array.from({ length: maximumEntries + 20 }, (_, i) => entry(i)))
    expect(result).toHaveLength(maximumEntries)
    expect(result[0].cursor).toBe('20')
  })
})
