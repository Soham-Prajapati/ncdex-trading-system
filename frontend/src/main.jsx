import { useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import './live.css'
import { get, money } from './api'
import { LiveSimulation } from './live'
import { PortfolioPage, TradersScd } from './traders'

const POWER_BI_URL = 'https://app.powerbi.com/groups/82cf6b9e-a1b0-401f-a341-40b1c99117c1/reports/455db239-d0fb-4ee2-836e-c094fd96d94e'

function formatPct(value) {
  if (value == null || value === '') return '0%'
  const n = Number(value)
  if (Number.isNaN(n) || n === 0) return '0%'
  const formatted = parseFloat(n.toFixed(2))
  if (formatted === 0) return '0%'
  return `${formatted > 0 ? '+' : ''}${formatted}%`
}

function formatTradeTime(value) {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('en-IN')
}

function Sparkline({ values = [] }) {
  if (!values.length) return <div className="empty-chart">No market series yet</div>
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1
  const points = values.map((v, i) => `${(i / Math.max(values.length - 1, 1)) * 100},${100 - ((v - min) / span) * 82 - 8}`).join(' ')
  return <svg className="sparkline" viewBox="0 0 100 100" preserveAspectRatio="none"><polyline points={points} fill="none" stroke="currentColor" strokeWidth="3" vectorEffect="non-scaling-stroke" /></svg>
}

function App() {
  const [tab, setTab] = useState(() => window.location.hash.slice(1) || 'live')
  const [presenting, setPresenting] = useState(false)
  useEffect(() => { window.location.hash = tab }, [tab])
  useEffect(() => {
    const follow = () => setTab(window.location.hash.slice(1) || 'live')
    window.addEventListener('hashchange', follow)
    return () => window.removeEventListener('hashchange', follow)
  }, [])
  const [overview, setOverview] = useState(null)
  const [commodities, setCommodities] = useState([])
  const [prices, setPrices] = useState([])
  const [trades, setTrades] = useState([])
  const [orders, setOrders] = useState([])
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [connectionStatus, setConnectionStatus] = useState('connecting')

  const load = async () => {
    setRefreshing(true); setError('')
    if (connectionStatus !== 'online') setConnectionStatus('connecting')
    try {
      const [o, c, p, t, od] = await Promise.all([get('/overview'), get('/commodities'), get('/market/prices?limit=60'), get('/trades?limit=12'), get('/orders?limit=12')])
      setOverview(o); setCommodities(c); setPrices(p); setTrades(t); setOrders(od)
      setConnectionStatus('online')
    } catch (e) {
      setError('API is not reachable. Start the FastAPI server to load live Neon data.')
      setConnectionStatus('offline')
    }
    finally { setRefreshing(false) }
  }
  useEffect(() => { load() }, [tab])

  const cotton = useMemo(() => prices.filter(p => p.symbol === 'COTTON').sort((a,b) => new Date(a.price_date) - new Date(b.price_date)), [prices])
  const nav = [['live','Live simulation','◎'],['overview','Overview','⌂'],['market','Market watch','↗'],['orders','Orders','⇄'],['traders','Traders & SCD2','⟲'],['portfolio','Portfolio','◉'],['reports','Reports','▥']]
  return <div className={`app-shell ${presenting ? 'presenting' : ''}`}>
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">N</div><div><strong>NCDEX</strong><span>Trading simulation</span></div></div>
      <div className="workspace-label">COMMAND CENTER</div>
      <nav>{nav.map(([id,label,icon]) => <button key={id} className={tab===id?'active':''} onClick={() => setTab(id)}><span>{icon}</span>{label}</button>)}</nav>
      <div className="sidebar-footer">
        <div className={`status-dot ${connectionStatus}`}/>
        <span>{connectionStatus === 'connecting' ? 'Connecting to database…' : connectionStatus === 'online' ? 'Neon database online' : 'Neon database offline'}</span>
      </div>
    </aside>
    <main className="main">
      <header className="topbar"><div><p className="eyebrow">GROUP 100 · ACADEMIC YEAR 2026–27</p><h1>{tab === 'overview' ? 'Market command center' : tab === 'live' ? 'Live exchange simulation' : nav.find(n => n[0] === tab)?.[1]}</h1></div><div className="header-actions"><span className="live-pill"><i/> LIVE SIMULATION</span><button className="refresh" onClick={load}>{refreshing ? 'Refreshing…' : '↻ Refresh data'}</button><div className="avatar">G100</div></div></header>
      {error && tab !== 'live' && <div className="error-banner">{error}<button onClick={load}>Retry</button></div>}
      {tab === 'live' && <LiveSimulation presenting={presenting} setPresenting={setPresenting}/>}
      {tab === 'traders' && <TradersScd/>}
      {tab === 'overview' && <>
        <section className="hero"><div><p className="eyebrow light">NATIONAL COMMODITY & DERIVATIVES EXCHANGE</p><h2>Trade smarter.<br/><em>Learn bigger.</em></h2><p className="hero-copy">A transparent simulation of commodity markets, built for understanding order flow, risk, and opportunity.</p></div><div className="hero-orbit"><div className="orbit-ring ring-one"/><div className="orbit-ring ring-two"/><div className="orbit-core">₹<strong>7.2K</strong><small>cotton / bale</small></div></div></section>
        <section className="metric-grid">{[['Total traded notional',money(overview?.traded_notional),'↗ 12.4%','teal'],['Executed trades',overview?.total_trades || 0,'Today','purple'],['Active traders',overview?.active_traders || 0,'Across 3 commodities','yellow'],['Market movement',`${Number(overview?.market_change_pct || 0).toFixed(2)}%`,'Latest close','blue']].map(([label,value,detail,color]) => <div className={`metric-card ${color}`} key={label}><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>)}</section>
        <section className="content-grid"><div className="panel wide"><div className="panel-head"><div><p className="eyebrow">PRICE PERFORMANCE</p><h3>Cotton futures</h3></div><span className="chart-tag">COTTON · 14D</span></div><div className="chart-value">{money(cotton.at(-1)?.close_price)} <span>{formatPct(cotton.at(-1)?.daily_change_pct)}</span></div><Sparkline values={cotton.map(p => Number(p.close_price))}/><div className="axis"><span>01 Sep</span><span>07 Sep</span><span>14 Sep 2026</span></div></div><div className="panel"><div className="panel-head"><div><p className="eyebrow">LISTED CONTRACTS</p><h3>Market board</h3></div><button className="text-button" onClick={() => setTab('market')}>View all →</button></div><div className="commodity-list">{commodities.map(c => <div className="commodity-row" key={c.symbol}><div className="commodity-icon">{c.symbol[0]}</div><div><strong>{c.name}</strong><small>{c.symbol} · per {c.unit}</small></div><div className="commodity-price"><strong>{money(c.current_price)}</strong><small className={Number(c.daily_change_pct) >= 0 ? 'positive':'negative'}>{Number(c.daily_change_pct || 0).toFixed(2)}%</small></div></div>)}</div></div></section>
        <section className="content-grid bottom"><div className="panel wide"><div className="panel-head"><div><p className="eyebrow">RECENT EXECUTION</p><h3>Latest trades</h3></div><button className="text-button" onClick={() => setTab('orders')}>Open blotter →</button></div><TradeTable rows={trades}/></div><div className="panel insight"><div className="insight-icon">✦</div><p className="eyebrow">LEARNING SIGNAL</p><h3>Price-time priority is working.</h3><p>Orders are matched by best price first, then earliest submission time—just like a real exchange order book.</p><button className="outline-button">Explore order matching</button></div></section>
      </>}
      {tab === 'market' && <Page title="Market watch" subtitle="Historical prices and live contract snapshots"><div className="market-grid">{commodities.map(c => <div className="market-card" key={c.symbol}><div className="commodity-icon large">{c.symbol[0]}</div><p className="eyebrow">{c.symbol}</p><h3>{c.name}</h3><div className="market-card-price">{money(c.current_price)}</div><span className={Number(c.daily_change_pct)>=0?'positive':'negative'}>{Number(c.daily_change_pct||0).toFixed(2)}% today</span><Sparkline values={prices.filter(p=>p.symbol===c.symbol).sort((a,b)=>new Date(a.price_date)-new Date(b.price_date)).map(p=>Number(p.close_price))}/></div>)}</div><div className="panel"><div className="panel-head"><div><p className="eyebrow">OHLC DATA</p><h3>Historical market prices</h3></div></div><div className="table-wrap"><table><thead><tr><th>Date</th><th>Contract</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Volume</th></tr></thead><tbody>{prices.map(p=><tr key={`${p.symbol}-${p.price_date}`}><td>{p.price_date}</td><td><strong>{p.symbol}</strong></td><td>{money(p.open_price)}</td><td>{money(p.high_price)}</td><td>{money(p.low_price)}</td><td><strong>{money(p.close_price)}</strong></td><td>{Number(p.volume).toLocaleString('en-IN')}</td></tr>)}</tbody></table></div></div></Page>}
      {tab === 'orders' && <Page title="Orders & trades" subtitle="Monitor order flow, fills, and executed trades"><div className="panel"><div className="panel-head"><div><p className="eyebrow">ORDER BLOTTER</p><h3>Recent orders</h3></div><span className="chart-tag">{orders.length} visible</span></div><div className="table-wrap"><table><thead><tr><th>Trader</th><th>Contract</th><th>Side</th><th>Price</th><th>Quantity</th><th>Filled</th><th>Status</th></tr></thead><tbody>{orders.map(o=><tr key={o.order_id}><td>{o.trader_name}</td><td><strong>{o.symbol}</strong></td><td><span className={`side ${o.side}`}>{o.side}</span></td><td>{money(o.price)}</td><td>{o.quantity}</td><td>{o.filled_quantity}</td><td><span className="status">{o.status}</span></td></tr>)}</tbody></table></div></div><div className="panel"><div className="panel-head"><div><p className="eyebrow">EXECUTED TRADES</p><h3>Trade tape</h3></div></div><TradeTable rows={trades}/></div></Page>}
      {tab === 'portfolio' && <PortfolioPage/>}
      {tab === 'reports' && <Page title="Reports & analytics" subtitle="Faculty-ready views powered by Neon analytics"><div className="report-grid">{[['Faculty overview','KPIs, market movement, execution activity'],['Market analytics','OHLC, volume, VWAP, daily change'],['Trading operations','Order flow, fills, and trade tape'],['SCD audit','Effective-date history for trader profiles, users and commodities'],['Live price ticks','Every execution with the reason the price moved']].map(([title,copy],i)=><div className="report-card" key={title}><div className="report-number">0{i+1}</div><h3>{title}</h3><p>{copy}</p><a href={POWER_BI_URL} target="_blank" rel="noreferrer">Open in Power BI →</a></div>)}</div></Page>}
    </main>
  </div>
}

function Page({title, subtitle, children}) { return <><div className="page-intro"><p className="eyebrow">NCDEX SIMULATION</p><h2>{title}</h2><p>{subtitle}</p></div>{children}</> }
function TradeTable({rows}) { return <div className="table-wrap"><table><thead><tr><th>Time</th><th>Contract</th><th>Buyer</th><th>Seller</th><th>Price</th><th>Quantity</th><th>Notional</th></tr></thead><tbody>{rows.map(t=><tr key={t.trade_id}><td>{formatTradeTime(t.trade_time)}</td><td><strong>{t.symbol}</strong></td><td>{t.buyer_name}</td><td>{t.seller_name}</td><td>{money(t.price)}</td><td>{t.quantity}</td><td><strong>{money(t.notional_value)}</strong></td></tr>)}</tbody></table></div> }
createRoot(document.getElementById('root')).render(<App />)

