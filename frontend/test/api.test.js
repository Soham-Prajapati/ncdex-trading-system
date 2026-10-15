import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const apiSource = fs.readFileSync(path.join(__dirname, '../src/api.js'), 'utf8')
  .replace('import.meta.env.VITE_API_BASE_URL', 'undefined')

globalThis.window = { location: { protocol: 'http:', hostname: 'localhost' } }
const { fmtTime, fmtStamp, isOpenEnded } = await import(`data:text/javascript,${encodeURIComponent(apiSource)}`)

test('fmtTime - missing values return placeholder', () => {
  assert.equal(fmtTime(null), '—')
  assert.equal(fmtTime(undefined), '—')
  assert.equal(fmtTime(''), '—')
})

test('fmtTime - invalid timestamps return placeholder', () => {
  assert.equal(fmtTime('invalid-date'), '—')
  assert.equal(fmtTime('abc'), '—')
  assert.equal(fmtTime(NaN), '—')
})

test('fmtTime - valid timestamps format time correctly', () => {
  const iso = '2026-10-15T12:30:45Z'
  const expected = new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  assert.equal(fmtTime(iso), expected)
})

test('fmtStamp - missing values return placeholder', () => {
  assert.equal(fmtStamp(null), '—')
  assert.equal(fmtStamp(undefined), '—')
  assert.equal(fmtStamp(''), '—')
})

test('fmtStamp - invalid timestamps return placeholder', () => {
  assert.equal(fmtStamp('invalid-date'), '—')
  assert.equal(fmtStamp('foo'), '—')
  assert.equal(fmtStamp(NaN), '—')
})

test('fmtStamp - valid timestamps format date and time', () => {
  const iso = '2026-10-15T12:30:45Z'
  const expected = new Date(iso).toLocaleString('en-IN', {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
  assert.equal(fmtStamp(iso), expected)
})

test('fmtStamp - open-ended (infinity) dates return infinity symbol', () => {
  assert.equal(fmtStamp('infinity'), '∞')
  assert.equal(fmtStamp('+infinity'), '∞')
  assert.equal(fmtStamp('9999-12-31T23:59:59.999999Z'), '∞')
  assert.equal(fmtStamp(new Date('9999-12-31T23:59:59Z')), '∞')
})

test('isOpenEnded - correctly identifies open-ended timestamps', () => {
  assert.equal(isOpenEnded('infinity'), true)
  assert.equal(isOpenEnded('+infinity'), true)
  assert.equal(isOpenEnded('9999-12-31T23:59:59.999999Z'), true)
  assert.equal(isOpenEnded('2026-10-15T12:30:45Z'), false)
  assert.equal(isOpenEnded(null), false)
  assert.equal(isOpenEnded(undefined), false)
  assert.equal(isOpenEnded(''), false)
  assert.equal(isOpenEnded('invalid-date'), false)
})
