import type { LogEntry } from '../api'
export const maximumEntries = 2000
export function appendEntries(current: LogEntry[], incoming: LogEntry[]) {
  const seen = new Set(current.map(entry => entry.cursor))
  return [...current, ...incoming.filter(entry => {
    if (seen.has(entry.cursor)) return false
    seen.add(entry.cursor)
    return true
  })].slice(-maximumEntries)
}
export const priorities = ['Emergency', 'Alert', 'Critical', 'Error', 'Warning', 'Notice', 'Info', 'Debug']
export function entryText(entry: LogEntry) {
  return `${entry.timestamp} ${entry.program} [${priorities[entry.priority] ?? entry.priority}] ${entry.message}`
}
