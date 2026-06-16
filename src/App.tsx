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
import { PersonalBetPage } from './pages/PersonalBetPage'
import { useForecast } from './hooks/useForecast'
import { captureModelSnapshot, loadPersonalLedger, settlePersonalLedger } from './features/personal-bets/storage'
import type { PersonalBetLedger } from './features/personal-bets/types'
import { appendLedgerEntry, combinedAvailableBalance, currentBalance, emptyLedger, loadLedger, saveLedger, settleLedger } from './lib/ledger'
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
  const [personalLedger, setPersonalLedger] = useState<PersonalBetLedger>(() => loadPersonalLedger())
  const [settlements, setSettlements] = useState<SettlementFile | null>(null)

  useEffect(() => {
    fetch('./data/settlements.json', { cache: 'no-store' })
      .then((response) => response.ok ? response.json() as Promise<SettlementFile> : null)
      .then((settlements) => {
        if (!settlements) return
        setSettlements(settlements)
        setLedger((current) => {
          const next = settleLedger(current, settlements)
          if (next !== current) saveLedger(next)
          return next
        })
      })
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!data) return
    setPersonalLedger((current) => {
      const captured = captureModelSnapshot(current, data)
      return settlements ? settlePersonalLedger(captured, settlements) : captured
    })
  }, [data, settlements])

  const availableBankroll = combinedAvailableBalance(ledger, personalLedger)

  const selectedMatch = useMemo(() => {
    if (!data) return null
    return data.matches.find((match) => match.id === selectedMatchId) ?? data.matches[0]
  }, [data, selectedMatchId])

  const selectedPortfolio = useMemo(() => {
    if (!data) return null
    const source = data.portfolios.find((portfolio) => portfolio.key === selectedStrategy) ?? data.portfolios[0]
    return scalePortfolio(source, availableBankroll, data.bankroll)
  }, [data, selectedStrategy, availableBankroll])

  if (error) return <div className="app-state error-state"><h1>预测数据读取失败</h1><p>{error}</p><p>请先运行 <code>python -m pipeline.generate</code>。</p></div>
  if (!data) return <div className="app-state"><div className="loading-ring" /><p>正在读取明日预测...</p></div>
  if (!selectedPortfolio) return <div className="app-state"><div className="loading-ring" /><p>正在计算资金方案...</p></div>

  const formalCandidates = data.matches.flatMap((match) => match.quotes).filter((quote) =>
    quote.available
    && quote.robustExpectedReturn !== null
    && quote.robustExpectedReturn > 0
    && (quote.recommendation === '重点推荐' || quote.recommendation === '小注可选'),
  )
  const lowCoverageMatches = data.matches.filter((match) => match.coverage < 0.75).length
  const singleEligibleOptions = data.matches.flatMap((match) => match.quotes).filter((quote) => quote.available && quote.singleEligible).length
  const emptyPortfolioReason = formalCandidates.length > 0
    ? '有候选项，但资金上限或组合约束未形成合法票单。'
    : lowCoverageMatches === data.matches.length
      ? `${lowCoverageMatches}/${data.matches.length} 场数据覆盖低于 75%，且本期单关选项 ${singleEligibleOptions} 个；高表面价值项仅作观察。`
      : '没有同时通过数据覆盖、赔率时效、原始期望和稳健期望四道门槛的选项。'

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
          {!data.matches.length || !selectedMatch ? (
            <main className="empty-forecast-panel">
              <h1>次日暂无可用比赛</h1>
              <p>{data.statusMessage}</p>
              <p>当前只是“今日方案”没有比赛数据；我的投注、资金记录和历史票单仍可继续使用。</p>
              <button onClick={() => setActiveNav('personal')}>打开我的投注</button>
            </main>
          ) : (
            <>
              <main className="dashboard-grid">
                <MatchRail targetDate={data.targetDate} matches={data.matches} selectedId={selectedMatch.id} onSelect={setSelectedMatchId} />
                <ValueTable matches={data.matches} selectedId={selectedMatch.id} onSelect={setSelectedMatchId} />
                <TacticalPanel match={selectedMatch} onOpenDetail={() => setActiveNav('analysis')} />
                <PortfolioSection bankroll={availableBankroll} portfolios={data.portfolios.map((portfolio) => scalePortfolio(portfolio, availableBankroll, data.bankroll))} emptyReason={emptyPortfolioReason} selected={selectedPortfolio.key} onSelect={setSelectedStrategy} onOpenDetails={() => setDrawerOpen(true)} />
                <div className="right-bottom-stack">
                  <BankrollChart portfolio={selectedPortfolio} portfolios={data.portfolios.map((portfolio) => scalePortfolio(portfolio, availableBankroll, data.bankroll))} onSelect={setSelectedStrategy} />
                  <NoBetPanel hasPositiveOptions={formalCandidates.length > 0} choice={noBetChoice} onChoice={setNoBetChoice} />
                </div>
              </main>
              <StatusBar forecast={data} bankroll={availableBankroll} onOpenDetails={() => setDrawerOpen(true)} />
            </>
          )}
        </>
      )}
      {activeNav === 'analysis' && (selectedMatch ? <AnalysisPage match={selectedMatch} /> : <main className="empty-forecast-panel"><h1>暂无比赛分析</h1><p>当前目标日期没有可分析的比赛；请先使用“我的投注”记录历史票单。</p><button onClick={() => setActiveNav('personal')}>打开我的投注</button></main>)}
      {activeNav === 'personal' && <PersonalBetPage forecast={data} settlements={settlements} ledger={personalLedger} onLedgerChange={setPersonalLedger} />}
      {activeNav === 'ledger' && <LedgerPage ledger={ledger} availableBankroll={availableBankroll} personalBetCount={personalLedger.bets.length} onImport={(next) => { saveLedger(next); setLedger(next) }} onReset={() => { const next = emptyLedger(); saveLedger(next); setLedger(next) }} />}
      {activeNav === 'backtest' && <BacktestPage forecast={data} />}
      {activeNav === 'method' && <MethodPage />}
      <PortfolioDrawer open={drawerOpen} portfolio={selectedPortfolio} onClose={() => setDrawerOpen(false)} onConfirm={confirmPurchase} />
    </div>
  )
}
