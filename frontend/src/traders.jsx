import { useCallback, useEffect, useState } from 'react'
import { compactMoney, fmtStamp, get, initials, isOpenEnded, num, send } from './api'

const RISK = ['Conservative', 'Moderate', 'Aggressive', 'Very aggressive', 'Neutral']
const KYC = ['Basic', 'Full KYC', 'Derivatives enabled', 'Institutional']
const FIELDS = [
  ['full_name', 'Full name'], ['phone', 'Phone'], ['trader_type', 'Trader type'], ['organisation', 'Organisation'],
  ['address_line', 'Address'], ['city', 'City'], ['state', 'State'], ['pincode', 'PIN code'], ['experience_level', 'Experience'],
]

export function ProfileForm({ trader, brokers, onSaved, onCancel }) {
  const initial = Object.fromEntries([...FIELDS.map(([k]) => [k, trader[k] ?? '']),
    ['risk_appetite', trader.risk_appetite], ['kyc_tier', trader.kyc_tier],
    ['broker_id', trader.broker_id ?? brokers.find((b) => b.name === trader.broker_name)?.broker_id ?? '']])
  const [form, setForm] = useState(initial)
  const [reason, setReason] = useState('Customer requested address change')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const changed = Object.fromEntries(Object.entries(form).filter(([k, v]) => String(v ?? '') !== String(initial[k] ?? '')))

  const save = async (e) => {
    e.preventDefault()
    if (!Object.keys(changed).length) { setError('Change at least one field — SCD2 only versions real changes.'); return }
    setSaving(true); setError('')
    try { onSaved(await send(`/traders/${trader.trader_id}`, { ...changed, reason }, 'PATCH')) }
    catch (err) { setError(err.message) } finally { setSaving(false) }
  }
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  return <form className="profile-form" onSubmit={save}>
    <div className="form-head"><div className="trader-avatar" style={{ '--accent': trader.avatar_color }}>{initials(trader.full_name || trader.trader_name)}</div>
      <div><p className="eyebrow">EDIT PROFILE → NEW SCD2 VERSION</p><h3>{trader.full_name || trader.trader_name}</h3></div></div>
    <div className="form-grid">
      {FIELDS.map(([k, label]) => <label key={k} className={k in changed ? 'dirty' : ''}>{label}<input value={form[k] ?? ''} onChange={set(k)} /></label>)}
      <label className={'risk_appetite' in changed ? 'dirty' : ''}>Risk appetite<select value={form.risk_appetite} onChange={set('risk_appetite')}>{RISK.map((r) => <option key={r}>{r}</option>)}</select></label>
      <label className={'kyc_tier' in changed ? 'dirty' : ''}>KYC tier<select value={form.kyc_tier} onChange={set('kyc_tier')}>{KYC.map((r) => <option key={r}>{r}</option>)}</select></label>
      <label className={'broker_id' in changed ? 'dirty' : ''}>Broker<select value={form.broker_id} onChange={set('broker_id')}>{brokers.map((b) => <option key={b.broker_id} value={b.broker_id}>{b.name}</option>)}</select></label>
    </div>
    <label className="reason-field">Change reason (stored on the new version)<input value={reason} onChange={(e) => setReason(e.target.value)} minLength={3} required /></label>
    <p className="form-hint">{Object.keys(changed).length
      ? <>Saving closes the current version (<code>to_date = now</code>, <code>current_flag = N</code>) and opens a new one (<code>to_date = ∞</code>, <code>current_flag = Y</code>) with: <strong>{Object.keys(changed).join(', ')}</strong>.</>
      : 'Edit any field above — changed fields are highlighted.'}</p>
    {error && <div className="error-banner">{error}</div>}
    <div className="form-actions"><button type="button" className="ghost-button" onClick={onCancel}>Cancel</button>
      <button className="big-button small" disabled={saving}>{saving ? 'Saving…' : 'Save & version'}</button></div>
  </form>
}

export function TradersScd() {
  const [traders, setTraders] = useState([])
  const [brokers, setBrokers] = useState([])
  const [selected, setSelected] = useState(null)
  const [history, setHistory] = useState(null)
  const [log, setLog] = useState([])
  const [dimension, setDimension] = useState('')
  const [editing, setEditing] = useState(false)
  const [contract, setContract] = useState({ symbol: 'COTTON', field: 'tick_size', value: '', reason: 'Exchange circular — contract revision' })
  const [message, setMessage] = useState('')

  const load = useCallback(async () => {
    const [t, b, l] = await Promise.all([get('/traders'), get('/brokers'), get(`/scd${dimension ? `?dimension=${encodeURIComponent(dimension)}` : ''}`)])
    setTraders(t.filter((x) => !x.is_market_maker)); setBrokers(b); setLog(l)
    setSelected((s) => s ? t.find((x) => x.trader_id === s.trader_id) : t.find((x) => !x.is_market_maker))
  }, [dimension])
  useEffect(() => { load().catch(() => setMessage('API is not reachable.')) }, [load])
  useEffect(() => { if (selected) get(`/traders/${selected.trader_id}/history`).then(setHistory) }, [selected])

  const saveContract = async (e) => {
    e.preventDefault()
    try {
      const r = await send(`/commodities/${contract.symbol}`, { [contract.field]: contract.value, reason: contract.reason }, 'PATCH')
      setMessage(r.narrative); load()
    } catch (err) { setMessage(err.message) }
  }

  return <>
    <div className="page-intro"><p className="eyebrow">MASTER DATA · SCD TYPE 2</p><h2>Traders & profile history</h2>
      <p>Every participant profile is versioned. Editing an address, risk profile, KYC tier or broker closes the current row and opens a new one — nothing is overwritten.</p></div>
    {message && <div className="info-banner">{message}<button onClick={() => setMessage('')}>×</button></div>}
    <section className="traders-layout">
      <div className="panel compact trader-list">
        <div className="panel-head"><div><p className="eyebrow">PARTICIPANTS</p><h3>{traders.length} trader profiles</h3></div></div>
        {traders.map((t) => <button key={t.trader_id} className={`trader-row ${selected?.trader_id === t.trader_id ? 'active' : ''}`} onClick={() => { setSelected(t); setEditing(false) }}>
          <span className="trader-avatar sm" style={{ '--accent': t.avatar_color }}>{initials(t.trader_name)}</span>
          <span><strong>{t.trader_name}</strong><small>{t.trader_type} · {t.city}</small></span>
          <span className="ver">v{t.profile_versions}</span>
        </button>)}
      </div>
      {selected && <div className="panel compact">
        {editing
          ? <ProfileForm trader={selected} brokers={brokers} onCancel={() => setEditing(false)}
              onSaved={(r) => { setEditing(false); setMessage(r.narrative); load(); get(`/traders/${selected.trader_id}/history`).then(setHistory) }} />
          : <>
            <div className="profile-head">
              <span className="trader-avatar" style={{ '--accent': selected.avatar_color }}>{initials(selected.trader_name)}</span>
              <div><p className="eyebrow">{selected.trader_type}</p><h3>{selected.trader_name}</h3>
                <p className="muted">{selected.organisation} · {selected.address_line}, {selected.city}, {selected.state} {selected.pincode}</p></div>
              <button className="big-button small" onClick={() => setEditing(true)}>✎ Edit profile</button>
            </div>
            <div className="profile-stats">
              <div><small>Cash</small><strong>{compactMoney(selected.cash_balance)}</strong></div>
              <div><small>Unrealised P&L</small><strong className={num(selected.unrealized_pnl) >= 0 ? 'positive' : 'negative'}>{compactMoney(selected.unrealized_pnl)}</strong></div>
              <div><small>Realised P&L</small><strong className={num(selected.realized_pnl) >= 0 ? 'positive' : 'negative'}>{compactMoney(selected.realized_pnl)}</strong></div>
              <div><small>Risk · KYC</small><strong>{selected.risk_appetite} · {selected.kyc_tier}</strong></div>
            </div>
          </>}
        <p className="eyebrow section-label">trader_history — physical SCD2 rows</p>
        <div className="table-wrap"><table>
          <thead><tr><th>Ver.</th><th>Address</th><th>City</th><th>Type</th><th>Risk</th><th>KYC</th><th>Broker</th><th>from_date</th><th>to_date</th><th>Flag</th><th>Reason</th></tr></thead>
          <tbody>{(history?.profile_versions || []).map((v) => <tr key={v.trader_history_id} className={v.current_flag === 'Y' ? 'current' : 'closed'}>
            <td>v{v.version_no}</td><td>{v.address_line || '∅'}</td><td>{v.city || '∅'}</td><td>{v.trader_type}</td><td>{v.risk_appetite}</td><td>{v.kyc_tier}</td><td>{v.broker_name}</td>
            <td>{fmtStamp(v.from_date)}</td><td className={isOpenEnded(v.to_date) ? 'infinity' : ''}>{fmtStamp(v.to_date)}</td>
            <td><span className={`flag ${v.current_flag}`}>{v.current_flag}</span></td><td className="reason">{v.change_reason}</td></tr>)}</tbody>
        </table></div>
        <p className="eyebrow section-label">user_history — account SCD2 rows</p>
        <div className="table-wrap"><table>
          <thead><tr><th>Name</th><th>Email</th><th>Phone</th><th>from_date</th><th>to_date</th><th>Flag</th><th>Reason</th></tr></thead>
          <tbody>{(history?.account_versions || []).map((v) => <tr key={v.user_history_id} className={v.current_flag === 'Y' ? 'current' : 'closed'}>
            <td>{v.full_name}</td><td>{v.email}</td><td>{v.phone}</td><td>{fmtStamp(v.from_date)}</td>
            <td className={isOpenEnded(v.to_date) ? 'infinity' : ''}>{fmtStamp(v.to_date)}</td><td><span className={`flag ${v.current_flag}`}>{v.current_flag}</span></td><td className="reason">{v.change_reason}</td></tr>)}</tbody>
        </table></div>
      </div>}
    </section>

    <section className="panel compact">
      <div className="panel-head"><div><p className="eyebrow">ALL TRACKED DIMENSIONS</p><h3>SCD2 change log</h3></div>
        <div className="seg">{['', 'Trader profile', 'User account', 'Commodity'].map((d) => <button key={d} className={dimension === d ? 'active' : ''} onClick={() => setDimension(d)}>{d || 'All'}</button>)}</div></div>
      <form className="contract-form" onSubmit={saveContract}>
        <span className="eyebrow">Admin · revise contract →</span>
        <select value={contract.symbol} onChange={(e) => setContract({ ...contract, symbol: e.target.value })}>{['COTTON', 'JEERA', 'SOYBEAN'].map((s) => <option key={s}>{s}</option>)}</select>
        <select value={contract.field} onChange={(e) => setContract({ ...contract, field: e.target.value })}>
          <option value="tick_size">tick size</option><option value="minimum_order_quantity">minimum lot</option><option value="description">description</option></select>
        <input placeholder="new value" value={contract.value} onChange={(e) => setContract({ ...contract, value: e.target.value })} required />
        <input className="wide" value={contract.reason} onChange={(e) => setContract({ ...contract, reason: e.target.value })} required />
        <button className="ghost-button">Version it</button>
      </form>
      <div className="table-wrap"><table>
        <thead><tr><th>Dimension</th><th>Entity</th><th>Ver.</th><th>What changed</th><th>from_date</th><th>to_date</th><th>Flag</th><th>Reason</th></tr></thead>
        <tbody>{log.map((r) => <tr key={`${r.dimension}${r.entity_id}${r.version_no}`}>
          <td><span className={`dim ${r.dimension.split(' ')[0].toLowerCase()}`}>{r.dimension}</span></td><td><strong>{r.entity_name}</strong></td><td>v{r.version_no}</td>
          <td className="changes">{r.changed_fields}</td><td>{fmtStamp(r.from_date)}</td><td className={isOpenEnded(r.to_date) ? 'infinity' : ''}>{fmtStamp(r.to_date)}</td>
          <td><span className={`flag ${r.current_flag}`}>{r.current_flag}</span></td><td className="reason">{r.change_reason}</td></tr>)}</tbody>
      </table></div>
    </section>
  </>
}

export function PortfolioPage() {
  const [traders, setTraders] = useState([])
  useEffect(() => { get('/traders').then((t) => setTraders(t.filter((x) => !x.is_market_maker))).catch(() => {}) }, [])
  return <>
    <div className="page-intro"><p className="eyebrow">NCDEX SIMULATION</p><h2>Portfolio & positions</h2><p>Cash, marked-to-market position value and P&L for every participant.</p></div>
    <div className="panel"><div className="table-wrap"><table>
      <thead><tr><th>Trader</th><th>Type</th><th>City</th><th>Cash</th><th>Position value</th><th>Unrealised P&L</th><th>Realised P&L</th><th>Profile versions</th></tr></thead>
      <tbody>{traders.map((t) => <tr key={t.trader_id}><td><strong>{t.trader_name}</strong></td><td>{t.trader_type}</td><td>{t.city}</td>
        <td>{compactMoney(t.cash_balance)}</td><td>{compactMoney(t.position_value)}</td>
        <td className={num(t.unrealized_pnl) >= 0 ? 'positive' : 'negative'}>{compactMoney(t.unrealized_pnl)}</td>
        <td className={num(t.realized_pnl) >= 0 ? 'positive' : 'negative'}>{compactMoney(t.realized_pnl)}</td><td>v{t.profile_versions}</td></tr>)}</tbody>
    </table></div></div>
  </>
}
