import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { compactMoney, fmtStamp, fmtTime, get, initials, isOpenEnded, money, num, qty, send, signed } from './api'
import { ProfileForm } from './traders'

const SYMBOLS = ['COTTON', 'JEERA', 'SOYBEAN']
const DEFAULT_GRID = ['ramesh@ncdex-sim.local', 'ananya@ncdex-sim.local', 'arjun@ncdex-sim.local', 'farhan@ncdex-sim.local']
const STEP_MS = 4500
const RANDOM_MS = 2200
const POLL_MS = 1500

function useStored(key, initial) {
  const [value, setValue] = useState(() => {
    try { return JSON.parse(localStorage.getItem(key)) ?? initial } catch { return initial }
  })
  useEffect(() => { try { localStorage.setItem(key, JSON.stringify(value)) } catch { /* storage unavailable */ } }, [key, value])
  return [value, setValue]
}

// Highlights that fade out on their own: key -> css class.
function useFlashes() {
  const [flashes, setFlashes] = useState({})
  const flash = useCallback((key, cls, ms = 3200) => {
    setFlashes((f) => ({ ...f, [key]: cls }))
    setTimeout(() => setFlashes((f) => { const n = { ...f }; if (n[key] === cls) delete n[key]; return n }), ms)
  }, [])
  return [flashes, flash]
}

const scdKey = (r) => `${r.dimension}|${r.entity_id}|${r.version_no}`

export function LiveSimulation({ presenting, setPresenting }) {
  const [symbol, setSymbol] = useStored('ncdex.symbol', 'COTTON')
  const [grid, setGrid] = useStored('ncdex.grid', DEFAULT_GRID)
  const [live, setLive] = useState(null)
  const [error, setError] = useState('')
  const [autoplay, setAutoplay] = useState(false)
  const [randomFlow, setRandomFlow] = useState(false)
  const [spotlight, setSpotlight] = useState(null)
  const [editing, setEditing] = useState(null)
  const [brokers, setBrokers] = useState([])
  const [flashes, flash] = useFlashes()
  const seenEvents = useRef(null)
  const seenScd = useRef(null)
  const inflight = useRef(false)
  const stepping = useRef(false)
  const autoplayRef = useRef(autoplay)
  autoplayRef.current = autoplay

  const refresh = useCallback(async () => {
    if (inflight.current) return
    inflight.current = true
    try { setLive(await get(`/live?symbol=${symbol}`)); setError('') }
    catch { setError('Live API unreachable — start the FastAPI server (port 8000).') }
    finally { inflight.current = false }
  }, [symbol])

  useEffect(() => { refresh(); const id = setInterval(refresh, POLL_MS); return () => clearInterval(id) }, [refresh])
  useEffect(() => { get('/brokers').then(setBrokers).catch(() => {}) }, [])

  // Detect what is new since the previous poll and light it up.
  useEffect(() => {
    if (!live) return
    const ids = live.feed.map((e) => e.event_id)
    if (seenEvents.current) {
      const fresh = live.feed.filter((e) => !seenEvents.current.has(e.event_id)).reverse()
      fresh.forEach((e) => {
        flash(`event:${e.event_id}`, 'new', 6000)
        const who = live.participants.find((p) => p.full_name === e.trader_name)
        if (who) flash(`trader:${who.trader_id}`, e.event_type === 'profile_updated' ? 'flash-scd' : e.side === 'sell' ? 'flash-sell' : 'flash-buy')
        if (e.symbol && autoplayRef.current && SYMBOLS.includes(e.symbol)) setSymbol(e.symbol)
      })
      if (fresh.length) setSpotlight(fresh.at(-1))
    } else if (live.feed[0]) setSpotlight(live.feed[0])
    seenEvents.current = new Set(ids)

    const keys = live.scd.map(scdKey)
    if (seenScd.current) keys.filter((k) => !seenScd.current.has(k)).forEach((k) => flash(`scd:${k}`, 'row-new', 7000))
    seenScd.current = new Set(keys)
  }, [live, flash, setSymbol])

  const step = useCallback(async () => {
    if (stepping.current) return
    stepping.current = true
    try {
      const r = await send('/sim/step')
      if (r.scenario.done) setAutoplay(false)
      await refresh()
    } catch (e) { setError(e.message); setAutoplay(false) }
    finally { stepping.current = false }
  }, [refresh])

  useEffect(() => {
    if (!autoplay) return
    step()
    const id = setInterval(step, STEP_MS)
    return () => clearInterval(id)
  }, [autoplay, step])

  useEffect(() => {
    if (!randomFlow) return
    const id = setInterval(() => send('/sim/random').then(refresh).catch((e) => setError(e.message)), RANDOM_MS)
    return () => clearInterval(id)
  }, [randomFlow, refresh])

  const startDemo = async () => {
    try { await send('/sim/restart'); setAutoplay(true) } catch (e) { setError(e.message) }
  }

  const trade = async (trader, side, quantity, orderType = 'market') => {
    try {
      await send('/sim/order', { trader_id: trader.trader_id, symbol, side, quantity, order_type: orderType, motive: 'Live action from the demo console' })
      await refresh()
    } catch (e) { setError(e.message) }
  }

  const participants = live?.participants || []
  const byEmail = useMemo(() => Object.fromEntries(participants.map((p) => [p.email, p])), [participants])
  const ticker = live?.tickers.find((t) => t.symbol === symbol)
  const scenario = live?.scenario

  return <div className={`live ${presenting ? 'presenting' : ''}`}>
    <section className="control-bar">
      <div className="control-main">
        {!autoplay
          ? <button className="big-button" onClick={startDemo}><span>▶</span>{scenario?.next > 0 && !scenario?.done ? 'Restart live demo' : 'Start live demo'}</button>
          : <button className="big-button pause" onClick={() => setAutoplay(false)}><span>❚❚</span>Pause demo</button>}
        <button className="ghost-button" onClick={step} disabled={autoplay}>Next step ⏭</button>
        <label className={`toggle ${randomFlow ? 'on' : ''}`}><input type="checkbox" checked={randomFlow} onChange={(e) => setRandomFlow(e.target.checked)} /><i />Random market flow</label>
        <button className="ghost-button" onClick={() => setPresenting(!presenting)}>{presenting ? '⤡ Exit presenter' : '⤢ Presenter mode'}</button>
      </div>
      {scenario && <div className="scenario-track">
        {scenario.steps.map((title, i) => <span key={title} title={title}
          className={`dot ${i < scenario.next ? 'done' : ''} ${i === scenario.next && !scenario.done ? 'next' : ''}`} />)}
        <small>{scenario.done ? 'Scenario complete — press Start to replay' : `Step ${scenario.next + 1}/${scenario.total}: ${scenario.next_title}`}</small>
      </div>}
    </section>

    {error && <div className="error-banner">{error}<button onClick={() => setError('')}>Dismiss</button></div>}

    <section className="ticker-strip">
      {live?.tickers.map((t) => {
        const change = num(t.ltp) - num(t.prev_close)
        const pct = t.prev_close ? change / num(t.prev_close) * 100 : 0
        return <button key={t.symbol} className={`ticker ${t.symbol === symbol ? 'active' : ''}`} onClick={() => setSymbol(t.symbol)}>
          <span className="ticker-sym">{t.symbol}</span>
          <strong key={t.ltp} className={`ticker-ltp ${pct >= 0 ? 'up' : 'down'}`}>{money(t.ltp)}</strong>
          <small className={pct >= 0 ? 'positive' : 'negative'}>{pct >= 0 ? '▲' : '▼'} {signed(change)} ({signed(pct)}%)</small>
          <em>Vol {qty(t.today_volume)} {t.unit} · min lot {qty(t.minimum_order_quantity)}</em>
        </button>
      })}
      {live && <div className="ticker stats"><span className="ticker-sym">TODAY</span><strong>{live.stats.trades_today} trades</strong>
        <small>{compactMoney(live.stats.notional_today)} notional</small><em>{live.stats.scd_rows} SCD2 rows</em></div>}
    </section>

    <section className="live-layout">
      <div className="trader-grid">
        {grid.map((email, slot) => {
          const p = byEmail[email]
          return <TraderCard key={slot} p={p} participants={participants} symbol={symbol}
            flash={p && flashes[`trader:${p.trader_id}`]}
            onSwap={(next) => setGrid(grid.map((g, i) => (i === slot ? next : g)))}
            onTrade={trade} onEdit={() => setEditing(p)} />
        })}
      </div>
      <aside className="market-rail">
        <Spotlight event={spotlight} />
        <div className="panel compact">
          <div className="panel-head"><div><p className="eyebrow">LAST TRADED PRICE · {symbol}</p><h3>{money(ticker?.ltp)} <small className="unit">/ {ticker?.unit}</small></h3></div>
            <span className="chart-tag">{live?.ticks.length || 0} ticks</span></div>
          <PriceChart ticks={live?.ticks || []} ticker={ticker} />
        </div>
        <OrderBook book={live?.book} ticker={ticker} />
      </aside>
    </section>

    <section className="live-bottom">
      <div className="panel compact">
        <div className="panel-head"><div><p className="eyebrow">SLOWLY CHANGING DIMENSION · TYPE 2</p><h3>Live SCD2 version log</h3></div>
          <span className="chart-tag">to_date = ∞ ⇒ current_flag Y</span></div>
        <ScdTable rows={live?.scd || []} flashes={flashes} />
      </div>
      <div className="panel compact">
        <div className="panel-head"><div><p className="eyebrow">CAUSE → EFFECT</p><h3>Why the price moved</h3></div></div>
        <Feed feed={live?.feed || []} flashes={flashes} />
      </div>
    </section>

    {editing && <div className="modal-backdrop" onClick={() => setEditing(null)}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <ProfileForm trader={editing} brokers={brokers} onCancel={() => setEditing(null)}
          onSaved={() => { setEditing(null); refresh() }} />
      </div>
    </div>}
  </div>
}

function TraderCard({ p, participants, symbol, flash, onSwap, onTrade, onEdit }) {
  const [size, setSize] = useState(10)
  if (!p) return <div className="trader-card empty">Loading participant…</div>
  const position = p.positions.find((x) => x.symbol === symbol)
  const totalPnl = p.positions.reduce((s, x) => s + num(x.unrealized_pnl) + num(x.realized_pnl), 0)
  const action = p.last_action
  return <article className={`trader-card ${flash || ''}`} style={{ '--accent': p.avatar_color }}>
    <header>
      <div className="trader-avatar">{initials(p.full_name)}</div>
      <div className="trader-id">
        <select value={p.email} onChange={(e) => onSwap(e.target.value)} aria-label="Choose participant">
          {participants.map((o) => <option key={o.email} value={o.email}>{o.full_name}</option>)}
        </select>
        <span>{p.trader_type}</span>
      </div>
      <button className="scd-chip" onClick={onEdit} title="Edit profile — creates an SCD2 version">SCD v{p.profile_versions} ✎</button>
    </header>
    <div className="trader-meta">
      <span className="addr">📍 {p.address_line}, {p.city} {p.pincode}</span>
      <span>{p.organisation}</span>
      <div className="chips"><i>{p.risk_appetite}</i><i>{p.kyc_tier}</i><i>{p.broker_name}</i></div>
    </div>
    <div className="trader-numbers">
      <div><small>Cash</small><strong>{compactMoney(p.cash_balance)}</strong></div>
      <div><small>{symbol} position</small><strong className={num(position?.quantity) > 0 ? 'positive' : num(position?.quantity) < 0 ? 'negative' : ''}>
        {position ? `${num(position.quantity) > 0 ? 'Long' : num(position.quantity) < 0 ? 'Short' : 'Flat'} ${qty(Math.abs(num(position.quantity)))}` : '—'}</strong>
        {position && num(position.quantity) !== 0 && <em>avg {money(position.average_price)}</em>}</div>
      <div><small>Total P&L</small><strong className={totalPnl >= 0 ? 'positive' : 'negative'}>{compactMoney(totalPnl)}</strong></div>
    </div>
    <div className="trader-action">
      {action ? <>
        <span className={`action-tag ${action.type === 'profile_updated' ? 'scd' : action.side || 'news'}`}>
          {action.type === 'profile_updated' ? 'PROFILE ▸ SCD2' : `${(action.side || '').toUpperCase()} ${action.symbol || ''}`}</span>
        <p>{action.narrative}</p><time>{fmtTime(action.at)}</time>
      </> : <p className="muted">No activity yet — waiting for the market.</p>}
    </div>
    <footer>
      <select value={size} onChange={(e) => setSize(Number(e.target.value))} aria-label="Order size">
        {[5, 10, 25, 50].map((n) => <option key={n} value={n}>{n}</option>)}
      </select>
      <button className="buy" onClick={() => onTrade(p, 'buy', size)}>Buy {symbol}</button>
      <button className="sell" onClick={() => onTrade(p, 'sell', size)}>Sell {symbol}</button>
    </footer>
  </article>
}

function Spotlight({ event }) {
  if (!event) return <div className="spotlight idle"><p className="eyebrow">LIVE</p><h3>Press “Start live demo”</h3><p>Each action will be explained here as it happens.</p></div>
  const before = num(event.price_before), after = num(event.price_after)
  const moved = event.event_type === 'trade_executed'
  const pct = moved && before ? (after - before) / before * 100 : 0
  const tone = event.event_type === 'profile_updated' || event.event_type === 'commodity_updated' ? 'scd'
    : event.event_type === 'market_news' ? 'news' : pct > 0 ? 'up' : pct < 0 ? 'down' : 'flat'
  return <div key={event.event_id} className={`spotlight ${tone}`}>
    <p className="eyebrow">{tone === 'scd' ? 'SCD2 VERSION CREATED' : tone === 'news' ? 'MARKET NEWS' : `${event.symbol} · ${fmtTime(event.created_at)}`}</p>
    {moved && <h3>{money(before)} → {money(after)} <span>{pct > 0 ? '▲' : pct < 0 ? '▼' : '■'} {signed(pct)}%</span></h3>}
    <p>{event.narrative}</p>
  </div>
}

function PriceChart({ ticks, ticker }) {
  const points = ticks.length >= 2 ? ticks : [{ price: ticker?.prev_close, tick_id: 'p' }, { price: ticker?.ltp, tick_id: 'l' }]
  const values = points.map((t) => num(t.price)).filter(Boolean)
  if (!values.length) return <div className="empty-chart">No ticks yet</div>
  const ref = num(ticker?.prev_close)
  const min = Math.min(...values, ref || Infinity), max = Math.max(...values, ref || -Infinity)
  const span = max - min || 1, W = 600, H = 190, pad = 14
  const x = (i) => pad + (i / Math.max(points.length - 1, 1)) * (W - pad * 2)
  const y = (v) => pad + (1 - (v - min) / span) * (H - pad * 2)
  const line = points.map((t, i) => `${x(i).toFixed(1)},${y(num(t.price)).toFixed(1)}`).join(' ')
  const up = values.at(-1) >= (ref || values[0])
  return <div className="price-chart">
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
      <defs><linearGradient id="area" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor={up ? '#1ba98e' : '#d06767'} stopOpacity=".22" /><stop offset="1" stopColor="#fff" stopOpacity="0" /></linearGradient></defs>
      {ref > 0 && <line x1={pad} x2={W - pad} y1={y(ref)} y2={y(ref)} className="ref-line" />}
      <polygon points={`${x(0)},${H - pad} ${line} ${x(points.length - 1)},${H - pad}`} fill="url(#area)" />
      <polyline points={line} fill="none" stroke={up ? '#1ba98e' : '#d06767'} strokeWidth="2.5" vectorEffect="non-scaling-stroke" />
      {points.slice(-40).map((t, j) => {
        const i = points.length - Math.min(points.length, 40) + j
        return t.aggressor_side && <circle key={t.tick_id} cx={x(i)} cy={y(num(t.price))} r="3.2" className={t.aggressor_side} vectorEffect="non-scaling-stroke"><title>{t.aggressor} {t.aggressor_side} {qty(t.quantity)} @ {money(t.price)}</title></circle>
      })}
    </svg>
    <div className="chart-scale"><span>{money(max)}</span><span>prev close {money(ref)}</span><span>{money(min)}</span></div>
    <div className="legend"><i className="buy" /> buyer-initiated <i className="sell" /> seller-initiated</div>
  </div>
}

function OrderBook({ book, ticker }) {
  if (!book) return null
  const all = [...book.asks, ...book.bids]
  const maxQty = Math.max(1, ...all.map((l) => num(l.quantity)))
  const row = (l) => {
    const people = l.owners.filter((o) => o !== 'NCDEX Liquidity Desk')
    return <div key={`${l.side}${l.price}`} className={`book-row ${l.side}`}>
      <span className="bar" style={{ width: `${num(l.quantity) / maxQty * 100}%` }} />
      <span className="px">{money(l.price)}</span><span className="q">{qty(l.quantity)}</span>
      <span className="who">{people.length ? people.join(', ') : 'market maker'}</span>
    </div>
  }
  const spread = book.asks[0] && book.bids[0] ? num(book.asks[0].price) - num(book.bids[0].price) : null
  return <div className="panel compact order-book">
    <div className="panel-head"><div><p className="eyebrow">ORDER BOOK · PRICE-TIME PRIORITY</p><h3>Depth</h3></div>
      {spread != null && <span className="chart-tag">spread {money(spread)}</span>}</div>
    <div className="book-head"><span>Price</span><span>Qty</span><span>Resting with</span></div>
    <div className="asks">{[...book.asks].reverse().map(row)}</div>
    <div className="book-mid">LTP {money(ticker?.ltp)}</div>
    <div className="bids">{book.bids.map(row)}</div>
  </div>
}

function ScdTable({ rows, flashes }) {
  return <div className="table-wrap scd-table"><table>
    <thead><tr><th>Entity · version</th><th>What changed</th><th>From date</th><th>To date</th><th>Flag</th><th>Reason</th></tr></thead>
    <tbody>{rows.map((r) => <tr key={scdKey(r)} className={flashes[`scd:${scdKey(r)}`] || ''}>
      <td><strong>{r.entity_name}</strong> v{r.version_no}<br /><span className={`dim ${r.dimension.split(' ')[0].toLowerCase()}`}>{r.dimension}</span></td>
      <td className="changes">{r.changed_fields}</td>
      <td>{fmtStamp(r.from_date)}</td>
      <td className={isOpenEnded(r.to_date) ? 'infinity' : ''}>{fmtStamp(r.to_date)}</td>
      <td><span className={`flag ${r.current_flag}`}>{r.current_flag}</span></td>
      <td className="reason">{r.change_reason}</td>
    </tr>)}</tbody>
  </table></div>
}

function Feed({ feed, flashes }) {
  return <ol className="feed">{feed.map((e) => {
    const delta = e.price_before != null ? num(e.price_after) - num(e.price_before) : null
    const tone = e.event_type === 'profile_updated' || e.event_type === 'commodity_updated' ? 'scd' : e.event_type === 'market_news' ? 'news' : delta > 0 ? 'up' : delta < 0 ? 'down' : 'flat'
    return <li key={e.event_id} className={`${tone} ${flashes[`event:${e.event_id}`] || ''}`}>
      <time>{fmtTime(e.created_at)}</time><p>{e.narrative}</p>
    </li>
  })}</ol>
}
