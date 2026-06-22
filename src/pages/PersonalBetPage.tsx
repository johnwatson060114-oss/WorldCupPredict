import { useEffect, useMemo, useState, type CSSProperties, type Dispatch, type SetStateAction } from 'react'
import { CalendarDays, CheckCircle2, ChevronDown, CircleAlert, Database, Download, Pencil, RefreshCw, RotateCcw, Save, Trash2 } from 'lucide-react'
import { percent, shortDateTime, signedPercent } from '../lib/format'
import type { DailyForecast, MarketQuote, MarketType, MatchForecast } from '../types'
import { FairComparisonChart, StrategyActualChart, StrategyProjectionChart } from '../features/personal-bets/Charts'
import { TicketReceipt } from '../features/personal-bets/TicketReceipt'
import { embeddedMatchesForDate, legMatchDate, matchDate, selectableMatchDates, ticketMatchDates } from '../features/personal-bets/cross-day'
import { actualStrategyPerformance, buildFairComparison, personalSummary, projectToFinal, type ComparisonMode } from '../features/personal-bets/analytics'
import {
  captureModelSnapshot,
  deletePersonalBet,
  exportPersonalLedger,
  personalBalance,
  reopenPersonalBet,
  savePersonalLedger,
  settlePersonalBetManually,
  upsertPersonalBet,
} from '../features/personal-bets/storage'
import type { DecisionSource, PersonalBet, PersonalBetLedger, PersonalBetLeg, StrategyHistory } from '../features/personal-bets/types'
import {
  groupLegsByMatch,
  inferPassType,
  PASS_DEFINITIONS,
  PASS_GROUPS,
  stakeForPass,
  theoreticalMaxPayout,
  ticketCountForPass,
  type PassType,
} from '../features/personal-bets/pass-types'

interface PersonalBetPageProps {
  forecast: DailyForecast
  ledger: PersonalBetLedger
  onLedgerChange: Dispatch<SetStateAction<PersonalBetLedger>>
}

interface FormState {
  id: string
  purchaseDate: string
  targetDate: string
  passType: PassType
  matchChoice: string
  market: MarketType
  multiple: string
  actualStake: string
  decisionSource: DecisionSource
  note: string
  legs: PersonalBetLeg[]
}

interface HistoryDateIndex {
  generatedAt: string
  dates: string[]
}

const marketOrder: MarketType[] = ['胜平负', '让球胜平负', '比分', '总进球数', '半全场']
const multipleOptions = Array.from({ length: 50 }, (_, index) => index + 1)

const decisionLabels: Record<DecisionSource, string> = {
  subjective: '我的主观判断',
  conservative: '参考稳健策略',
  balanced: '参考均衡策略',
  aggressive: '参考激进策略',
}

const preciseMoney = (value: number) => `${value.toFixed(2)}元`

const beijingToday = () => {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date())
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  return `${value.year}-${value.month}-${value.day}`
}

const initialForm = (forecast: DailyForecast): FormState => ({
  id: '',
  purchaseDate: beijingToday(),
  targetDate: forecast.targetDate,
  passType: '单关',
  matchChoice: forecast.matches[0]?.id ?? '',
  market: '胜平负',
  multiple: '1',
  actualStake: '',
  decisionSource: 'subjective',
  note: '',
  legs: [],
})

const quoteToLeg = (quote: MarketQuote, match: MatchForecast, matchIndex: number): PersonalBetLeg => ({
  matchId: quote.matchId,
  matchLabel: `${match.homeTeam} vs ${match.awayTeam}`,
  lotteryCode: match.lotteryCode || `第${String(matchIndex + 1).padStart(2, '0')}场`,
  kickoffBeijing: match.kickoffBeijing,
  matchDate: quote.matchDate ?? matchDate(match),
  market: quote.market,
  selection: quote.selection,
  odds: quote.odds ?? 0,
  modelProbability: quote.modelProbability,
})

const legsForBet = (bet: PersonalBet): PersonalBetLeg[] => bet.legs?.length
  ? bet.legs
  : bet.matchId && bet.market !== '自定义' && bet.market !== '混合过关'
    ? [{ matchId: bet.matchId, matchLabel: bet.matchLabel, market: bet.market, selection: bet.selection, odds: bet.odds, modelProbability: bet.modelProbability }]
    : []

export function PersonalBetPage({ forecast, ledger, onLedgerChange }: PersonalBetPageProps) {
  const [history, setHistory] = useState<StrategyHistory | null>(null)
  const [comparisonMode, setComparisonMode] = useState<ComparisonMode>('matched')
  const [form, setForm] = useState<FormState>(() => initialForm(forecast))
  const [bettingForecast, setBettingForecast] = useState<DailyForecast | null>(forecast)
  const [archiveState, setArchiveState] = useState<'ready' | 'loading' | 'missing'>('ready')
  const [historyDates, setHistoryDates] = useState<string[]>([])
  const [message, setMessage] = useState('')
  const [settlementEditor, setSettlementEditor] = useState<{ id: string; profit: string } | null>(null)
  const selectableDates = useMemo(() => selectableMatchDates(forecast, historyDates), [forecast, historyDates])
  const minimumSelectableDate = selectableDates[0] ?? forecast.targetDate
  const maximumSelectableDate = selectableDates.at(-1) ?? forecast.targetDate

  useEffect(() => {
    fetch('./data/history-index.json', { cache: 'no-store' })
      .then((response) => response.ok ? response.json() as Promise<HistoryDateIndex> : null)
      .then((index) => setHistoryDates(index?.dates ?? []))
      .catch(() => setHistoryDates([]))
  }, [forecast.generatedAt])

  useEffect(() => {
    fetch('./data/strategy-history.json', { cache: 'no-store' })
      .then((response) => response.ok ? response.json() as Promise<StrategyHistory> : null)
      .then(setHistory)
      .catch(() => setHistory(null))
  }, [forecast.generatedAt])

  useEffect(() => {
    const matches = embeddedMatchesForDate(forecast, form.targetDate)
    if (form.targetDate === forecast.targetDate || matches.length) {
      setBettingForecast(form.targetDate === forecast.targetDate
        ? forecast
        : { ...forecast, targetDate: form.targetDate, matches })
      setArchiveState('ready')
      return
    }
    const controller = new AbortController()
    setArchiveState('loading')
    fetch(`./data/history/${form.targetDate}.json`, { cache: 'no-store', signal: controller.signal })
      .then((response) => response.ok ? response.json() as Promise<DailyForecast> : Promise.reject(new Error('missing')))
      .then((payload) => {
        setBettingForecast(payload)
        setArchiveState('ready')
      })
      .catch((error: Error) => {
        if (error.name === 'AbortError') return
        setBettingForecast(null)
        setArchiveState('missing')
      })
    return () => controller.abort()
  }, [forecast, form.targetDate])

  useEffect(() => {
    const firstMatch = bettingForecast?.matches[0]
    if (!firstMatch) return
    setForm((current) => {
      if (bettingForecast.matches.some((match) => match.id === current.matchChoice)) return current
      const firstMarket = marketOrder.find((market) => firstMatch.quotes.some((quote) => quote.market === market)) ?? '胜平负'
      return { ...current, matchChoice: firstMatch.id, market: firstMarket }
    })
  }, [bettingForecast])

  const selectedMatch = bettingForecast?.matches.find((match) => match.id === form.matchChoice)
  const summary = useMemo(() => personalSummary(ledger), [ledger])
  const sortedBets = useMemo(() => [...ledger.bets].sort((left, right) => {
    const leftPending = left.status === 'pending' ? 0 : 1
    const rightPending = right.status === 'pending' ? 0 : 1
    return leftPending - rightPending
  }), [ledger.bets])
  const comparison = useMemo(() => buildFairComparison(ledger, history, comparisonMode), [ledger, history, comparisonMode])
  const actual = useMemo(() => actualStrategyPerformance(history), [history])
  const projection = useMemo(() => projectToFinal(forecast.portfolios, history, ledger, forecast.targetDate), [forecast.portfolios, forecast.targetDate, history, ledger])
  const projectionReady = actual.summaries.every((item) => item.settledDays >= 5)
  const selectedGroups = useMemo(() => groupLegsByMatch(form.legs), [form.legs])
  const selectedMatchDates = useMemo(() => ticketMatchDates(form.legs), [form.legs])
  const requiredMatches = PASS_DEFINITIONS[form.passType].matches
  const multiple = Number(form.multiple)
  const ticketComplete = selectedGroups.length === requiredMatches
  const ticketCount = ticketComplete ? ticketCountForPass(form.legs, form.passType) : 0
  const calculatedStake = ticketComplete ? stakeForPass(form.legs, form.passType, multiple) : 0
  const maximumPayout = ticketComplete ? theoreticalMaxPayout(form.legs, form.passType, multiple) : 0
  const actualStake = form.actualStake.trim() ? Number(form.actualStake) : calculatedStake
  const actualMaximumPayout = calculatedStake > 0 && Number.isFinite(actualStake)
    ? Math.round(maximumPayout * actualStake / calculatedStake * 100) / 100
    : 0

  const resetForm = () => setForm(initialForm(forecast))

  const chooseDate = (targetDate: string) => {
    setMessage('')
    setForm((current) => ({ ...current, targetDate, matchChoice: '', market: '胜平负' }))
  }

  const choosePassType = (passType: PassType) => {
    setMessage('')
    setForm((current) => {
      const allowedMatches = new Set(groupLegsByMatch(current.legs).slice(0, PASS_DEFINITIONS[passType].matches).map((group) => group.matchId))
      return { ...current, passType, legs: current.legs.filter((leg) => allowedMatches.has(leg.matchId)) }
    })
  }

  const chooseQuote = (quote: MarketQuote) => {
    // Manual recording: odds is the only gate. available/singleEligible
    // are for live auto-betting — users can record any bet they placed.
    if (!quote.odds || !selectedMatch) return
    if (form.passType === '单关' && !quote.singleEligible && quote.available) {
      setMessage('该赔率不支持单关，请选择串关票型或改选带"单关"资格的选项。')
      return
    }
    const matchIndex = bettingForecast?.matches.findIndex((match) => match.id === selectedMatch.id) ?? 0
    const leg = quoteToLeg(quote, selectedMatch, matchIndex)
    setForm((current) => {
      if (current.passType === '单关') return { ...current, legs: [leg] }
      // Toggle: remove if same match+market+selection already selected
      const identical = current.legs.some((item) => item.matchId === leg.matchId && item.market === leg.market && item.selection === leg.selection)
      if (identical) return { ...current, legs: current.legs.filter((item) => !(item.matchId === leg.matchId && item.market === leg.market && item.selection === leg.selection)) }
      // Allow same-market multi-selection (复式投注): only check match count limit
      const matchIds = new Set(current.legs.map((item) => item.matchId))
      if (!matchIds.has(leg.matchId) && matchIds.size >= PASS_DEFINITIONS[current.passType].matches) {
        setMessage(`${current.passType}需要 ${PASS_DEFINITIONS[current.passType].matches} 场，已选满；同一场仍可继续多选玩法。`)
        return current
      }
      return { ...current, legs: [...current.legs, leg] }
    })
  }

  const saveBet = () => {
    if (selectedGroups.length !== requiredMatches) {
      setMessage(`${form.passType}需要选择 ${requiredMatches} 场，目前已选 ${selectedGroups.length} 场。`)
      return
    }
    if (!Number.isInteger(multiple) || multiple < 1 || multiple > 50) {
      setMessage('投注倍数必须为 1 至 50 的整数。')
      return
    }
    if (!form.purchaseDate) {
      setMessage('请选择实际出票日期；可以补记前一天的票。')
      return
    }
    const earliestMatchDate = selectedMatchDates[0] ?? form.targetDate
    if (form.purchaseDate > earliestMatchDate) {
      setMessage(`出票日期不能晚于最早一场比赛日期 ${earliestMatchDate}。`)
      return
    }
    if (!Number.isFinite(actualStake) || actualStake <= 0) {
      setMessage('实际投入必须是大于 0 的金额，支持填写 3 元等非标准票面金额。')
      return
    }
    const existing = form.id ? ledger.bets.find((item) => item.id === form.id) : undefined
    const odds = actualStake > 0 ? actualMaximumPayout / actualStake : 0
    const bet: PersonalBet = {
      id: form.id || crypto.randomUUID(),
      createdAt: existing?.createdAt ?? new Date().toISOString(),
      purchaseDate: form.purchaseDate,
      targetDate: earliestMatchDate,
      matchId: form.legs.length === 1 ? form.legs[0].matchId : undefined,
      matchLabel: form.legs.map((leg) => leg.matchLabel).join(' × '),
      market: form.legs.length === 1 ? form.legs[0].market : '混合过关',
      selection: form.legs.map((leg) => `${leg.market} ${leg.selection}`).join(' × '),
      odds,
      stake: Math.round(actualStake * 100) / 100,
      standardStake: calculatedStake,
      passType: form.passType,
      multiple,
      ticketCount,
      theoreticalPayout: actualMaximumPayout,
      decisionSource: form.decisionSource,
      status: 'pending',
      note: form.note.trim() || undefined,
      forecastGeneratedAt: bettingForecast?.generatedAt,
      legs: form.legs,
    }
    const next = upsertPersonalBet(captureModelSnapshot(ledger, forecast), bet)
    onLedgerChange(next)
    setMessage(form.id ? '票单已更新，结算结果请在已保存票单中手动填写。' : '已写入本机投注账本，赛后请手动填写实际盈亏。')
    resetForm()
  }

  const editBet = (bet: PersonalBet) => {
    const legs = legsForBet(bet)
    if (!legs.length) {
      setMessage('旧版自定义票不具备结构化选项，请删除后用新票单重新记录。')
      return
    }
    setForm({
      id: bet.id,
      purchaseDate: bet.purchaseDate ?? bet.targetDate,
      targetDate: legMatchDate(legs[0]) ?? bet.targetDate,
      passType: bet.passType ?? inferPassType(groupLegsByMatch(legs).length),
      matchChoice: legs[0].matchId,
      market: legs[0].market,
      multiple: (bet.multiple ?? Math.max(1, Math.round(bet.stake / Math.max(2, (bet.ticketCount ?? 1) * 2)))).toString(),
      actualStake: bet.stake.toString(),
      decisionSource: bet.decisionSource,
      note: bet.note ?? '',
      legs,
    })
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const removeBet = (id: string) => {
    onLedgerChange((current) => deletePersonalBet(current, id))
    if (form.id === id) resetForm()
  }

  const openSettlementEditor = (bet: PersonalBet) => {
    const profit = bet.status === 'settled' ? (bet.payout ?? 0) - bet.stake : -bet.stake
    setSettlementEditor({ id: bet.id, profit: profit.toFixed(2) })
  }

  const saveManualSettlement = (bet: PersonalBet) => {
    if (!settlementEditor || settlementEditor.id !== bet.id) return
    const profit = Number(settlementEditor.profit)
    if (!Number.isFinite(profit) || profit < -bet.stake) {
      setMessage(`实际盈亏不能低于 -${preciseMoney(bet.stake)}。`)
      return
    }
    onLedgerChange((current) => settlePersonalBetManually(current, bet.id, profit))
    setSettlementEditor(null)
    setMessage(`已手动记录盈亏 ${profit >= 0 ? '+' : ''}${preciseMoney(profit)}。`)
  }

  const reopenBet = (bet: PersonalBet) => {
    onLedgerChange((current) => reopenPersonalBet(current, bet.id))
    setSettlementEditor(null)
    setMessage('已撤回为待开奖，可稍后重新手动结算。')
  }

  const importLedger = async (file: File | undefined) => {
    if (!file) return
    const parsed = JSON.parse(await file.text()) as PersonalBetLedger
    if (parsed.schemaVersion !== 1 || !Array.isArray(parsed.bets) || !Array.isArray(parsed.modelSnapshots)) {
      setMessage('导入失败：不是受支持的个人投注账本。')
      return
    }
    savePersonalLedger(parsed)
    onLedgerChange(parsed)
    setMessage('个人投注账本已导入。')
  }

  const lineupEvidence = forecast.evidence.find((item) => item.source.includes('API-Football'))
  const weatherEvidence = forecast.evidence.find((item) => item.source.includes('Open-Meteo'))
  const dataChecks = [
    { label: '体彩五类玩法赔率', source: '中国体育彩票', blocked: false, evidence: forecast.evidence.find((item) => item.source.includes('体育彩票')) },
    { label: '世界杯赛程与赛果', source: 'football-data.org', blocked: false, evidence: forecast.evidence.find((item) => item.source.includes('football-data.org')) },
    { label: '阵容、伤停、预计首发', source: 'API-Football/人工核验', blocked: lineupEvidence?.status !== 'fresh', evidence: lineupEvidence },
    { label: '场地、天气、海拔', source: 'Open-Meteo + 场馆表', blocked: weatherEvidence?.status !== 'fresh', evidence: weatherEvidence },
    { label: '停赛、红牌、纪律变化', source: '人工核验表', blocked: false, evidence: { status: 'manual', observedAt: forecast.generatedAt } },
    { label: '次日方案生成', source: '北京时间', blocked: false, evidence: { status: forecast.status === 'ready' ? 'fresh' : 'manual', observedAt: forecast.generatedAt } },
  ] as const

  const reviewText = comparison.matchedDays < 5
    ? '共同样本不足 5 天，当前只记录误差，不调整凯利比例或串关规则。'
    : (comparison.userRoi ?? 0) > (comparison.modelRoi ?? 0)
      ? '你的共同下注日 ROI 暂时领先；继续观察回撤和样本稳定性，满 10 个共同日后再检验是否来自选择能力。'
      : '模型均衡策略暂时领先；优先复盘你跳过的高价值票、额外加入的负期望票和投注额偏离。'

  return (
    <main className="personal-bet-page sporttery-ledger-page">
      <div className="personal-page-title">
        <div><h1>我的投注</h1><span>个人记录 · 非官方购彩 · 票型与实际出票保持一致</span></div>
        <section className="personal-summary-grid" aria-label="投注资金摘要">
          <div><span>当前可用</span><strong>{preciseMoney(personalBalance(ledger))}</strong></div>
          <div><span>累计投入</span><strong>{preciseMoney(summary.totalStaked)}</strong></div>
          <div><span>已实现盈亏</span><strong className={summary.realizedProfit >= 0 ? 'positive-text' : 'negative-text'}>{preciseMoney(summary.realizedProfit)}</strong></div>
          <div><span>待结算敞口</span><strong>{preciseMoney(summary.pendingExposure)}</strong></div>
        </section>
        <div className="personal-page-actions">
          <button onClick={() => exportPersonalLedger(ledger)}><Download size={15} />导出账本</button>
          <label><Database size={15} />导入账本<input type="file" accept="application/json" onChange={(event) => void importLedger(event.target.files?.[0])} /></label>
        </div>
      </div>

      <div className="sporttery-workbench">
        <section className="sporttery-selector-panel">
          <div className="sporttery-section-title">
            <div><h2>竞彩足球</h2><p>切换比赛日期不会清空已选场次，可直接组合跨天串关</p></div>
            <span>{selectedGroups.length}/{requiredMatches} 场已选</span>
          </div>

          <div className="ticket-date-controls">
            <label><CalendarDays size={15} />出票日期<input type="date" min={minimumSelectableDate} max={beijingToday()} value={form.purchaseDate} onInput={(event) => { const purchaseDate = event.currentTarget.value; setForm((current) => ({ ...current, purchaseDate })) }} /></label>
            <label><CalendarDays size={15} />浏览比赛日期<input type="date" min={minimumSelectableDate} max={maximumSelectableDate} value={form.targetDate} onInput={(event) => chooseDate(event.currentTarget.value)} /></label>
            <label>过关方式<select value={form.passType} onChange={(event) => choosePassType(event.target.value as PassType)}>{PASS_GROUPS.map((group) => <optgroup key={group.label} label={group.label}>{group.options.map((passType) => <option key={passType}>{passType}</option>)}</optgroup>)}</select></label>
          </div>
          <div className="cross-day-date-bar">
            <span>可选比赛日</span>
            {selectableDates.map((date) => <button type="button" key={date} className={form.targetDate === date ? 'active' : ''} onClick={() => chooseDate(date)}>{date.slice(5).replace('-', '/')}</button>)}
            {selectedMatchDates.length > 0 && <em>票内日期：{selectedMatchDates.map((date) => date.slice(5).replace('-', '/')).join('、')}{selectedMatchDates.length > 1 ? '（跨天）' : ''}</em>}
          </div>

          {archiveState === 'loading' && <div className="archive-state">正在读取 {form.targetDate} 的体彩归档…</div>}
          {archiveState === 'missing' && <div className="archive-state warning">该日期没有保存赔率快照，不能补造票面赔率。请选择已有归档日期。</div>}

          {archiveState === 'ready' && bettingForecast && <>
            {!bettingForecast.matches.length ? (
              <div className="archive-state warning">
                {form.targetDate} 的快照存在但未包含比赛数据，可能该日期无赛程或数据生成时出现异常。
                请尝试选择其他已有数据的日期（如 2026-06-15 或 2026-06-16）。
              </div>
            ) : (
              <>
                <div className="sporttery-match-table">
                  <div className="sporttery-match-head"><span>场次</span><span>时间</span><span>主队 vs 客队</span><span>已选</span></div>
                  {bettingForecast.matches.map((match, index) => {
                    const matchLegs = form.legs.filter((leg) => leg.matchId === match.id)
                    return (
                      <button key={match.id} className={form.matchChoice === match.id ? 'active' : ''} onClick={() => setForm((current) => ({ ...current, matchChoice: match.id }))}>
                        <span>{match.lotteryCode || `第${String(index + 1).padStart(2, '0')}场`}</span>
                        <span>{shortDateTime(match.kickoffBeijing).slice(-5)}</span>
                        <strong>{match.homeTeam}<i>vs</i>{match.awayTeam}</strong>
                        <em>{matchLegs.length ? matchLegs.map((leg) => leg.selection).join(' / ') : '选择'}</em>
                      </button>
                    )
                  })}
                </div>

                {/* All 5 markets visible simultaneously — sporttery.cn style */}
                <div className="market-grid">
                  {selectedMatch ? (
                    marketOrder.map((market) => {
                      const quotes = selectedMatch.quotes.filter((q) => q.market === market)
                      if (!quotes.length) return null
                      const handicap = market === '让球胜平负' ? quotes[0]?.handicap : undefined
                      return (
                        <section className="market-grid-section" key={market}>
                          <div className="market-grid-header">
                            <span>{market}</span>
                            {handicap != null && <em className="handicap-badge">让{handicap > 0 ? `+${handicap}` : handicap}球</em>}
                          </div>
                          <div className="market-grid-options">
                            {quotes.map((quote) => {
                              const sel = form.legs.some((leg) => leg.matchId === quote.matchId && leg.market === quote.market && leg.selection === quote.selection)
                              const label = market === '让球胜平负' && quote.handicap != null
                                ? `${quote.handicap > 0 ? `+${quote.handicap}` : quote.handicap}${quote.selection}`
                                : quote.selection
                              const noOdds = !quote.odds || quote.odds <= 1
                              return (
                                <button key={quote.id} disabled={noOdds} className={sel ? 'selected' : ''} onClick={() => chooseQuote(quote)}>
                                  <span>{label}</span>
                                  <strong>{quote.odds?.toFixed(2) ?? '--'}</strong>
                                  <small>{noOdds ? '暂无赔率' : sel ? '已选' : '点击选择'}</small>
                                </button>
                              )
                            })}
                          </div>
                        </section>
                      )
                    })
                  ) : (
                    <div className="market-grid-empty">
                      <strong>暂无比赛</strong>
                      <small>请在上方选择一场比赛</small>
                    </div>
                  )}
                </div>

                {/* Real-time stat bar */}
                <div className="ticket-stat-bar">
                  <span>已选 <strong>{selectedGroups.length}</strong> 场</span>
                  <span>过关 <strong>{form.passType}</strong></span>
                  <span><strong>{ticketCount}</strong> 注</span>
                  <span>预计 <strong>{ticketCount && Number.isFinite(actualStake) ? actualStake.toFixed(2) : calculatedStake.toFixed(2)}</strong> 元</span>
                  {actualMaximumPayout > 0 && <span>最高奖金 <strong>{actualMaximumPayout.toFixed(2)}</strong> 元</span>}
                </div>
              </>
            )}
          </>}
        </section>

        <aside className="ticket-preview-panel">
          <div className="sporttery-section-title compact"><div><h2>投注单预览</h2><p>票型、注数与金额实时生成</p></div><span>个人记录</span></div>
          <TicketReceipt
            passType={form.passType}
            purchaseDate={form.purchaseDate}
            legs={form.legs}
            multiple={multiple}
            ticketCount={ticketCount}
            stake={ticketCount && Number.isFinite(actualStake) ? actualStake : calculatedStake}
            theoreticalPayout={actualMaximumPayout}
            ticketId={form.id}
            onRemoveLeg={(leg) => setForm((current) => ({ ...current, legs: current.legs.filter((item) => !(item.matchId === leg.matchId && item.market === leg.market && item.selection === leg.selection)) }))}
          />

          <div className="ticket-config-grid">
            <label>过关方式<select value={form.passType} onChange={(event) => choosePassType(event.target.value as PassType)}>{PASS_GROUPS.map((group) => <optgroup key={group.label} label={group.label}>{group.options.map((passType) => <option key={passType}>{passType}</option>)}</optgroup>)}</select></label>
            <label>倍数<select value={form.multiple} onChange={(event) => setForm((current) => ({ ...current, multiple: event.target.value }))}>{multipleOptions.map((value) => <option key={value} value={value}>{value}倍</option>)}</select></label>
            <label>注数<input value={ticketCount || ''} placeholder="自动计算" readOnly /></label>
            <label>实际金额<input type="number" min="0.01" step="0.01" value={form.actualStake} placeholder={calculatedStake ? calculatedStake.toFixed(2) : '自动计算'} onChange={(event) => setForm((current) => ({ ...current, actualStake: event.target.value }))} /></label>
            <label className="config-wide">判断来源<select value={form.decisionSource} onChange={(event) => setForm((current) => ({ ...current, decisionSource: event.target.value as DecisionSource }))}>{Object.entries(decisionLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
            <label className="config-wide">备注（可选）<textarea value={form.note} placeholder="例如：临场改票、实体店出票号" onChange={(event) => setForm((current) => ({ ...current, note: event.target.value }))} /></label>
          </div>
          {message && <p className="personal-form-message">{message}</p>}
          <div className="personal-form-actions"><button onClick={resetForm}><RotateCcw size={16} />重置</button><button className="primary" onClick={saveBet}><Save size={16} />{form.id ? '更新票单' : '保存票单'}</button></div>
        </aside>
      </div>

      <section className="saved-ticket-section">
        <div className="sporttery-section-title">
          <div><h2>已保存票单</h2><p>每张记录都按真实票面展示票型、选项、注数、倍数和金额</p></div>
          <span>{ledger.bets.length} 张</span>
        </div>
        {ledger.bets.length ? <div className="saved-ticket-grid">
          {sortedBets.map((bet) => {
            const legs = legsForBet(bet)
            const passType = bet.passType ?? inferPassType(groupLegsByMatch(legs).length)
            return (
              <article className={`saved-ticket-card ${bet.status}`} key={bet.id}>
                <TicketReceipt
                  compact
                  passType={passType}
                  purchaseDate={bet.purchaseDate ?? bet.targetDate}
                  legs={legs}
                  multiple={bet.multiple ?? 1}
                  ticketCount={bet.ticketCount ?? 1}
                  stake={bet.stake}
                  theoreticalPayout={bet.theoreticalPayout}
                  payout={bet.payout}
                  status={bet.status}
                  ticketId={bet.id}
                />
                <div className="saved-ticket-caption">
                  <span><b>{decisionLabels[bet.decisionSource]}</b>{bet.note && <small>{bet.note}</small>}</span>
                  {bet.status === 'settled' && <strong className={(bet.payout ?? 0) - bet.stake >= 0 ? 'positive-text' : 'negative-text'}>盈亏 {preciseMoney((bet.payout ?? 0) - bet.stake)}</strong>}
                </div>
                {settlementEditor?.id === bet.id && <div className="manual-settlement-editor">
                  <label>实际盈亏（元）<input type="number" step="0.01" min={-bet.stake} value={settlementEditor.profit} onChange={(event) => setSettlementEditor({ id: bet.id, profit: event.target.value })} /></label>
                  <small>亏损填负数，例如亏 {bet.stake.toFixed(2)} 元填 -{bet.stake.toFixed(2)}；盈利填正数。</small>
                  <div><button onClick={() => setSettlementEditor(null)}>取消</button><button className="primary" onClick={() => saveManualSettlement(bet)}><Save size={14} />保存盈亏</button></div>
                </div>}
                <div className="saved-ticket-actions manual">
                  <button onClick={() => openSettlementEditor(bet)}><CheckCircle2 size={14} />{bet.status === 'settled' ? '修改盈亏' : '手动结算'}</button>
                  {bet.status === 'settled' && <button onClick={() => reopenBet(bet)}><RefreshCw size={14} />撤回待开奖</button>}
                  <button onClick={() => editBet(bet)}><Pencil size={14} />编辑票单</button>
                  <button onClick={() => removeBet(bet.id)}><Trash2 size={14} />删除</button>
                </div>
              </article>
            )
          })}
        </div> : <div className="saved-ticket-empty"><strong>还没有保存的票型</strong><span>在上方选择比赛、玩法与赔率后保存，这里会出现完整的"2串1 / 4串11"等实体票式记录。</span></div>}
      </section>

      <details className="personal-analytics">
        <summary><span><strong>统计分析</strong><small>公平对比、策略实绩、数据检查与下注复盘</small></span><ChevronDown size={20} /></summary>
        <div className="personal-analytics-grid">
          <section className="panel personal-comparison-panel">
            <div className="personal-panel-title"><div><h2>公平对比</h2><p>默认只比较你和模型都下注的日期</p></div><div className="comparison-tabs"><button className={comparisonMode === 'matched' ? 'active' : ''} onClick={() => setComparisonMode('matched')}>共同下注日</button><button className={comparisonMode === 'all' ? 'active' : ''} onClick={() => setComparisonMode('all')}>所有各自下注日</button></div></div>
            <div className="comparison-metrics">
              <div><span>同口径 ROI</span><strong className={(comparison.userRoi ?? 0) >= 0 ? 'positive-text' : 'negative-text'}>{comparison.userRoi === null ? '--' : signedPercent(comparison.userRoi)}</strong><small>我的实际</small></div>
              <div><span>模型 ROI</span><strong>{comparison.modelRoi === null ? '--' : signedPercent(comparison.modelRoi)}</strong><small>均衡策略真实结算</small></div>
              <div><span>命中率</span><strong>{comparison.userHitRate === null ? '--' : percent(comparison.userHitRate, 1)}</strong><small>按实际票数</small></div>
              <div><span>共同样本</span><strong>{comparison.matchedDays} 天</strong><small>不足 10 天不定论</small></div>
            </div>
            {comparison.points.length ? <FairComparisonChart comparison={comparison} /> : <div className="personal-chart-empty">完成至少一天真实结算后，这里会出现你与模型的累计 ROI 曲线。</div>}
            <p className="comparison-footnote">未下注日期不会记为你的亏损；金额不同用 ROI 标准化。模型数据只取已经结算的真实方案，不把预测收益混入对比。</p>
          </section>

          <aside className="personal-side-stack">
            <section className="panel fairness-rules">
              <div className="personal-panel-title"><div><h2>公平规则</h2><p>防止天数和本金造成假领先</p></div></div>
              <ul><li><strong>共同下注日</strong><span>只取双方同一天有已结算投注的交集。</span></li><li><strong>ROI 标准化</strong><span>收益除以投入，避免谁下注多谁数字大。</span></li><li><strong>样本门槛</strong><span>少于 10 个共同日只展示，不判断优劣。</span></li><li><strong>真实优先</strong><span>未结算策略不显示为盈利，也不参与排名。</span></li></ul>
            </section>
            <section className="panel data-check-panel">
              <div className="personal-panel-title"><div><h2>每日数据检查</h2><p>{shortDateTime(forecast.generatedAt)} 生成</p></div><RefreshCw size={15} /></div>
              <div className="data-check-list">{dataChecks.map((check) => { const ok = check.evidence?.status === 'fresh' && !check.blocked; const state = check.blocked ? '待补全' : check.evidence?.status ?? 'missing'; return <div key={check.label} className={ok ? 'ok' : 'warning'}>{ok ? <CheckCircle2 size={14} /> : <CircleAlert size={14} />}<span><b>{check.label}</b><small>{check.source} · {state}</small></span></div> })}</div>
            </section>
          </aside>
        </div>

        <section className="panel strategy-actual-panel">
          <div className="personal-panel-title"><div><h2>三策略真实战绩</h2><p>只使用已结束比赛的真实派彩，未结算场次不计入盈利</p></div><span className="actual-badge">真实数据优先 · {actual.summaries[0]?.settledDays ?? 0} 个结算日</span></div>
          <div className="strategy-actual-body">
            <div className="strategy-actual-cards">{actual.summaries.map((item) => <div key={item.key} style={{ '--strategy-color': item.color } as CSSProperties}><span>{item.name}</span><strong>{preciseMoney(item.balance)}</strong><small>实际盈亏 <b className={item.profit >= 0 ? 'positive-text' : 'negative-text'}>{item.settledDays ? preciseMoney(item.profit) : '待首场结算'}</b></small><em>累计投入 {preciseMoney(item.totalStake)} · ROI {item.roi === null ? '--' : signedPercent(item.roi)}</em></div>)}</div>
            {actual.summaries.some((item) => item.settledDays > 0) ? <StrategyActualChart dates={actual.dates} summaries={actual.summaries} /> : <div className="strategy-actual-empty">当前还没有已结算策略日。比赛结果进入赛果文件后，这里才会更新真实余额，不提前预测盈利。</div>}
          </div>
          {actual.pendingDays > 0 && <p className="actual-pending-note">另有 {actual.pendingDays} 个方案日等待比赛全部结束，结算完成后自动加入上方真实曲线。</p>}
        </section>

        <section className="panel strategy-journey-panel">
          <div className="personal-panel-title"><div><h2>未来情景模拟（参考）</h2><p>至少 5 个真实结算日后才启用</p></div><span className="simulation-note">预测区，不计入真实盈利</span></div>
          {projectionReady ? <><div className="strategy-journey-body"><div className="strategy-projection-cards">{projection.summaries.map((item) => <div key={item.key} style={{ '--strategy-color': item.color } as CSSProperties}><span>{item.name}</span><strong>{preciseMoney(item.median)}</strong><small>5% {preciseMoney(item.p05)} · 95% {preciseMoney(item.p95)}</small><em>停止概率 {percent(item.stopProbability, 1)} · 中位最大回撤 {percent(item.medianMaxDrawdown, 1)}</em></div>)}</div><StrategyProjectionChart dates={projection.dates} summaries={projection.summaries} /></div><p className="projection-disclaimer">未来阶段从已结算日收益分布抽样，不把单日预测优势机械复利。余额不足 2 元时停止下注。</p></> : <div className="projection-locked"><strong>暂不预测终局盈利</strong><span>当前只有 {actual.summaries[0]?.settledDays ?? 0} 个真实结算日；达到 5 个后，才使用真实日收益分布模拟。</span></div>}
        </section>

        <section className="panel betting-review-panel">
          <div className="personal-panel-title"><div><h2>下注模式复盘</h2><p>预测准确与资金分配分开检验</p></div></div>
          <div className="review-state"><CircleAlert size={18} /><strong>{comparison.matchedDays < 5 ? '暂不调参' : '进入观察'}</strong></div>
          <p>{reviewText}</p>
          <dl><div><dt>预测层</dt><dd>比分、胜平负、总进球和半全场分别评估概率校准</dd></div><div><dt>下注层</dt><dd>ROI、最大回撤、赔率价值与过关方式分别复盘</dd></div><div><dt>改进门槛</dt><dd>至少 20 个模型日且 bootstrap 优势稳定</dd></div></dl>
        </section>
      </details>
    </main>
  )
}
