// The API runs on port 8000 of whichever host served the page, so the same
// build works on the presenting laptop and on a phone/tablet on the same Wi-Fi.
export const API = import.meta.env.VITE_API_BASE_URL || `${window.location.protocol}//${window.location.hostname}:8000/api`

export async function get(path) {
  const response = await fetch(`${API}${path}`)
  if (!response.ok) throw new Error(`Request failed: ${response.status}`)
  return response.json()
}

export async function send(path, body, method = 'POST') {
  const response = await fetch(`${API}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : data.detail?.[0]?.msg
    throw new Error(detail || `Request failed: ${response.status}`)
  }
  return data
}

export const num = (value) => Number(value || 0)
export const money = (value) => `₹${num(value).toLocaleString('en-IN', { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`
export const compactMoney = (value) => {
  const v = num(value), a = Math.abs(v)
  if (a >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`
  if (a >= 1e5) return `₹${(v / 1e5).toFixed(2)} L`
  return money(v)
}
export const qty = (value) => num(value).toLocaleString('en-IN', { maximumFractionDigits: 2 })
export const signed = (value, digits = 2) => `${num(value) >= 0 ? '+' : ''}${num(value).toFixed(digits)}`
export const fmtTime = (value) => new Date(value).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
export const isOpenEnded = (value) => new Date(value).getUTCFullYear() >= 9999
export const fmtStamp = (value) => isOpenEnded(value) ? '∞' : new Date(value).toLocaleString('en-IN', {
  day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit',
})
export const initials = (name = '') => name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase()
