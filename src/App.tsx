import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { Header, type NavKey } from './components/Header'
import { MatchRail } from './components/MatchRail'
import { ValueTable } from './components/ValueTable'
import { TacticalPanel } from './components/TacticalPanel'
import { PortfolioSection } from './components/PortfolioSection'
import { BankrollChart } from './components/BankrollChart'
import { NoBetPanel } from './components/NoBetPanel'
import { StatusBar } from './components/StatusBar'
import { PortfolioDrawer } from './components/PortfolioDrawer'
import { AnalysisPage } from './pages/AnalysisPage'
import { LedgerPage } from './pages/LedgerPage'
import { BacktestPage } from './pages/BacktestPage'
import { MethodPage } from './pages/MethodPage'
import { useForecast } from './hooks/useForecast'
import { appendLedgerEntry, currentBalance, emptyLedger, loadLedger, saveLedger, settleLedger } from './lib/ledger'
import { scalePortfolio } from './lib/portfolio'
import type { BankrollLedger, LedgerEntry, SettlementFile, StrategyKey } from './types'

export default function App() {
  const { data, error } = useForecast()
  const [activeNav, setActiveNav] = useState<NavKey>('today')
  const [selectedMatchId, setSelectedMatchId] = useState<string>('')
  const [selectedStrategy, setSelectedStrategy] = useState<StrategyKey>('balanced')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [noBetChoice, setNoBetChoice] = useState<'hold' | 'fun'>('hold')
  const [ledger, setLedger] = useState<BankrollLedger>(() => loadLedger())

  useEffect(() => {
    fetch('./data/settlements.json', { cache: 'no-store' })
      .then((response) => response.ok ? response.json() as Promise<SettlementFile> : null)
      .then((settlements) => settlements && setLedger((current) => {
        const next = settleLedger(current, settlements)
        if (next !== current) saveLedger(next)
        return next
      }))
      .catch(() => undefined)
  }, [])

  const selectedMatch = useMemo(() => {
    if (!data) return null
    return data.matches.find((match) => match.id === selectedMatchId) ?? data.matches[0]
  }, [data, selectedMatchId])

  const selectedPortfolio = useMemo(() => {
    if (!data) return null
    const source = data.portfolios.find((portfolio) => portfolio.key === selectedStrategy) ?? data.portfolios[0]
    return scalePortfolio(source, currentBalance(ledger), data.bankroll)
  }, [data, selectedStrategy, ledger])

  if (error) return <div className="app-state error-state"><h1>预测数据读取失败</h1><p>{error}</p><p>请先运行 <code>python -m pipeline.generate</code>。</p></div>
  if (!data) return <div className="app-state"><div className="loading-ring" /><p>正在读取明日预测...</p></div>
  if (!data.matches.length) return <div className="app-state error-state"><h1>次日暂无可用比赛</h1><p>{data.statusMessage}</p><p>实时任务会在北京时间 18:00 再次尝试。</p></div>
  if (!selectedMatch || !selectedPortfolio) return <div className="app-state"><div className="loading-ring" /><p>正在计算资金方案...</p></div>

  const hasPositiveOptions = data.matches.some((match) => match.quotes.some((quote) => (quote.robustExpectedReturn ?? -1) > 0))

  const navigate = (key: NavKey) => {
    setActiveNav(key)
    window.scrollTo({ top: 0 })
  }

  const confirmPurchase = () => {
    const entry: LedgerEntry = {
      id: crypto.randomUUID(),
      createdAt: new Date().toISOString(),
      targetDate: data.targetDate,
      strategy: selectedPortfolio.key,
      openingBalance: currentBalance(ledger),
      stake: selectedPortfolio.stake,
      status: 'pending',
      tickets: selectedPortfolio.tickets,
    }
    setLedger((current) => appendLedgerEntry(current, entry))
    setDrawerOpen(false)
    setActiveNav('ledger')
  }

  return (
    <div className="app-shell">
      <Header forecast={data} active={activeNav} onNavigate={navigate} />
      {activeNav === 'today' && (
        <>
          {data.status !== 'ready' && (
            <div className="degraded-banner" role="status">
              <AlertTriangle size={15} />
              <strong>数据来源受限</strong>
              <span>{data.statusMessage}</span>
              <small>仅用于功能预览，不作为实际投注依据</small>
            </div>
          )}
          <main className="dashboard-grid">
            <MatchRail targetDate={data.targetDate} matches={data.matches} selectedId={selectedMatch.id} onSelect={setSelectedMatchId} />
            <ValueTable matches={data.matches} selectedId={selectedMatch.id} onSelect={setSelectedMatchId} />
            <TacticalPanel match={selectedMatch} onOpenDetail={() => setActiveNav('analysis')} />
            <PortfolioSection bankroll={currentBalance(ledger)} portfolios={data.portfolios.map((portfolio) => scalePortfolio(portfolio, currentBalance(ledger), data.bankroll))} selected={selectedPortfolio.key} onSelect={setSelectedStrategy} onOpenDetails={() => setDrawerOpen(true)} />
            <div className="right-bottom-stack">
              <BankrollChart portfolio={selectedPortfolio} portfolios={data.portfolios.map((portfolio) => scalePortfolio(portfolio, currentBalance(ledger), data.bankroll))} onSelect={setSelectedStrategy} />
              <NoBetPanel hasPositiveOptions={hasPositiveOptions} choice={noBetChoice} onChoice={setNoBetChoice} />
            </div>
          </main>
          <StatusBar forecast={data} bankroll={currentBalance(ledger)} onOpenDetails={() => setDrawerOpen(true)} />
        </>
      )}
      {activeNav === 'analysis' && <AnalysisPage match={selectedMatch} />}
      {activeNav === 'ledger' && <LedgerPage ledger={ledger} onImport={(next) => { saveLedger(next); setLedger(next) }} onReset={() => { const next = emptyLedger(); saveLedger(next); setLedger(next) }} />}
      {activeNav === 'backtest' && <BacktestPage metrics={data.backtest} />}
      {activeNav === 'method' && <MethodPage />}
      <PortfolioDrawer open={drawerOpen} portfolio={selectedPortfolio} onClose={() => setDrawerOpen(false)} onConfirm={confirmPurchase} />
    </div>
  )
}
