import { useEffect, useMemo, useState, type CSSProperties, type Dispatch, type SetStateAction } from 'react'
import { CalendarDays, CheckCircle2, CircleAlert, Database, Download, Pencil, Plus, RefreshCw, Trash2, X } from 'lucide-react'
import { percent, shortDateTime, signedPercent } from '../lib/format'
import type { DailyForecast, MarketQuote, MarketType, SettlementFile } from '../types'
import { FairComparisonChart, StrategyActualChart, StrategyProjectionChart } from '../features/personal-bets/Charts'
import { actualStrategyPerformance, buildFairComparison, personalSummary, projectToFinal, type ComparisonMode } from '../features/personal-bets/analytics'
import {
  captureModelSnapshot,
  deletePersonalBet,
  exportPersonalLedger,
  personalBalance,
  savePersonalLedger,
  settlePersonalLedger,
  upsertPersonalBet,
} from '../features/personal-bets/storage'
import type { DecisionSource, PersonalBet, PersonalBetLedger, PersonalBetLeg, PersonalBetStatus, StrategyHistory } from '../features/personal-bets/types'
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
  settlements: SettlementFile | null
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

const marketOrder: MarketType[] = ['胜平负', '让球胜平负', '比分', '总进球数', '半全场']
const multipleOptions = Array.from({ length: 50 }, (_, index) => index + 1)

const decisionLabels: Record<DecisionSource, string> = {
  subjective: '我的主观判断',
  conservative: '参考稳健策略',
  balanced: '参考均衡策略',
  aggressive: '参考激进策略',
}

const statusLabels: Record<PersonalBetStatus, string> = { pending: '待结算', settled: '已结算', void: '作废' }
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

const quoteToLeg = (quote: MarketQuote, matchLabel: string): PersonalBetLeg => ({
  matchId: quote.matchId,
  matchLabel,
  market: quote.market,
  selection: quote.selection,
  odds: quote.odds ?? 0,
  modelProbability: quote.modelProbability,
})

export function PersonalBetPage({ forecast, settlements, ledger, onLedgerChange }: PersonalBetPageProps) {
  const [history, setHistory] = useState<StrategyHistory | null>(null)
  const [comparisonMode, setComparisonMode] = useState<ComparisonMode>('matched')
  const [form, setForm] = useState<FormState>(() => initialForm(forecast))
  const [bettingForecast, setBettingForecast] = useState<DailyForecast | null>(forecast)
  const [archiveState, setArchiveState] = useState<'ready' | 'loading' | 'missing'>('ready')
  const [message, setMessage] = useState('')

  useEffect(() => {
    fetch('./data/strategy-history.json', { cache: 'no-store' })
      .then((response) => response.ok ? response.json() as Promise<StrategyHistory> : null)
      .then(setHistory)
      .catch(() => setHistory(null))
  }, [forecast.generatedAt])

  useEffect(() => {
    if (form.targetDate === forecast.targetDate) {
      setBettingForecast(forecast)
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
  const marketQuotes = useMemo(
    () => selectedMatch?.quotes.filter((quote) => quote.market === form.market) ?? [],
    [selectedMatch, form.market],
  )
  const summary = useMemo(() => personalSummary(ledger), [ledger])
  const comparison = useMemo(() => buildFairComparison(ledger, history, comparisonMode), [ledger, history, comparisonMode])
  const actual = useMemo(() => actualStrategyPerformance(history), [history])
  const projection = useMemo(() => projectToFinal(forecast.portfolios, history, ledger, forecast.targetDate), [forecast.portfolios, forecast.targetDate, history, ledger])
  const projectionReady = actual.summaries.every((item) => item.settledDays >= 5)
  const selectedGroups = useMemo(() => groupLegsByMatch(form.legs), [form.legs])
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
    setForm((current) => ({ ...current, targetDate, id: '', legs: [], matchChoice: '', market: '胜平负' }))
  }

  const choosePassType = (passType: PassType) => {
    setMessage('')
    setForm((current) => {
      const allowedMatches = new Set(groupLegsByMatch(current.legs).slice(0, PASS_DEFINITIONS[passType].matches).map((group) => group.matchId))
      return { ...current, passType, legs: current.legs.filter((leg) => allowedMatches.has(leg.matchId)) }
    })
  }

  const chooseQuote = (quote: MarketQuote) => {
    if (!quote.available || !quote.odds || !selectedMatch) return
    if (form.passType === '单关' && !quote.singleEligible) {
      setMessage('该赔率不支持单关，请选择串关票型或改选带“单关”资格的选项。')
      return
    }
    const leg = quoteToLeg(quote, `${selectedMatch.homeTeam} vs ${selectedMatch.awayTeam}`)
    setForm((current) => {
      if (current.passType === '单关') return { ...current, legs: [leg] }
      const identical = current.legs.some((item) => item.matchId === leg.matchId && item.market === leg.market && item.selection === leg.selection)
      if (identical) return { ...current, legs: current.legs.filter((item) => !(item.matchId === leg.matchId && item.market === leg.market && item.selection === leg.selection)) }
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
    if (form.purchaseDate > form.targetDate) {
      setMessage('出票日期不能晚于所选比赛日期。')
      return
    }
    if (!Number.isFinite(actualStake) || actualStake <= 0) {
      setMessage('实际投入必须是大于 0 的金额，支持填写 3 元等非标准票面金额。')
      return
    }
    const existing = form.id ? ledger.bets.find((item) => item.id === form.id) : undefined
    const reusableStake = existing?.status === 'pending'
      ? existing.stake
      : existing?.status === 'settled'
        ? existing.stake - (existing.payout ?? 0)
        : 0
    const availableForSave = personalBalance(ledger) + reusableStake
    if (actualStake > availableForSave) {
      setMessage(`实际投入 ${preciseMoney(actualStake)}，已超过当前可用余额 ${preciseMoney(availableForSave)}。`)
      return
    }
    const odds = actualStake > 0 ? actualMaximumPayout / actualStake : 0
    const bet: PersonalBet = {
      id: form.id || crypto.randomUUID(),
      createdAt: existing?.createdAt ?? new Date().toISOString(),
      purchaseDate: form.purchaseDate,
      targetDate: form.targetDate,
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
    onLedgerChange(settlements ? settlePersonalLedger(next, settlements) : next)
    setMessage(form.id ? '记录已更新，并按已有赛果重新结算。' : '已写入本机投注账本。')
    resetForm()
  }

  const editBet = (bet: PersonalBet) => {
    const legs = bet.legs?.length ? bet.legs : bet.matchId && bet.market !== '自定义' && bet.market !== '混合过关'
      ? [{ matchId: bet.matchId, matchLabel: bet.matchLabel, market: bet.market, selection: bet.selection, odds: bet.odds, modelProbability: bet.modelProbability }]
      : []
    if (!legs.length) {
      setMessage('旧版自定义票不具备结构化选项，请删除后用新票单重新记录。')
      return
    }
    setForm({
      id: bet.id,
      purchaseDate: bet.purchaseDate ?? bet.targetDate,
      targetDate: bet.targetDate,
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
    <main className="personal-bet-page">
      <div className="personal-page-title">
        <div><span>全站统一使用这份本机账本计算可用金额</span><h1>我的投注账本</h1></div>
        <div className="personal-page-actions">
          <button onClick={() => exportPersonalLedger(ledger)}><Download size={14} />导出</button>
          <label><Database size={14} />导入<input type="file" accept="application/json" onChange={(event) => void importLedger(event.target.files?.[0])} /></label>
        </div>
      </div>

      <div className="personal-top-grid">
        <section className="panel personal-entry-panel">
          <div className="personal-panel-title"><div><h2>体彩式点选记账</h2><p>日期、比赛、玩法和赔率均从当日归档读取</p></div><Plus size={18} /></div>
          <div className="personal-summary-grid">
            <div><span>当前可用</span><strong>{preciseMoney(personalBalance(ledger))}</strong></div>
            <div><span>累计投入</span><strong>{preciseMoney(summary.totalStaked)}</strong></div>
            <div><span>已实现盈亏</span><strong className={summary.realizedProfit >= 0 ? 'positive-text' : 'negative-text'}>{preciseMoney(summary.realizedProfit)}</strong></div>
            <div><span>待结算敞口</span><strong>{preciseMoney(summary.pendingExposure)}</strong></div>
          </div>

          <div className="ticket-control-row">
            <label><CalendarDays size={13} />出票日期<input type="date" min="2026-06-11" max={beijingToday()} value={form.purchaseDate} onInput={(event) => { const purchaseDate = event.currentTarget.value; setForm((current) => ({ ...current, purchaseDate })) }} /></label>
            <label><CalendarDays size={13} />比赛日期<input type="date" min="2026-06-11" max={forecast.targetDate} value={form.targetDate} onInput={(event) => chooseDate(event.currentTarget.value)} /></label>
            <label>过关方式<select value={form.passType} onChange={(event) => choosePassType(event.target.value as PassType)}>{PASS_GROUPS.map((group) => <optgroup key={group.label} label={group.label}>{group.options.map((passType) => <option key={passType}>{passType}</option>)}</optgroup>)}</select></label>
            <label>倍数<select value={form.multiple} onChange={(event) => setForm((current) => ({ ...current, multiple: event.target.value }))}>{multipleOptions.map((value) => <option key={value} value={value}>{value}倍</option>)}</select></label>
            <label>判断来源<select value={form.decisionSource} onChange={(event) => setForm((current) => ({ ...current, decisionSource: event.target.value as DecisionSource }))}>{Object.entries(decisionLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
          </div>

          {archiveState === 'loading' && <div className="archive-state">正在读取 {form.targetDate} 的体彩归档…</div>}
          {archiveState === 'missing' && <div className="archive-state warning">该日期没有保存赔率快照，不能合规地自动补造赔率。今后的每日快照会持续归档。</div>}
          {archiveState === 'ready' && bettingForecast && <>
            <div className="ticket-match-row">
              <label>选择比赛<select value={form.matchChoice} onChange={(event) => setForm((current) => ({ ...current, matchChoice: event.target.value }))}>{bettingForecast.matches.map((match) => <option key={match.id} value={match.id}>{match.lotteryCode ? `${match.lotteryCode} · ` : ''}{match.homeTeam} vs {match.awayTeam}</option>)}</select></label>
              <span>{selectedMatch ? `${shortDateTime(selectedMatch.kickoffBeijing)} 开球` : '暂无比赛'}</span>
            </div>
            <div className="market-tabs" role="tablist">{marketOrder.map((market) => <button key={market} className={form.market === market ? 'active' : ''} onClick={() => setForm((current) => ({ ...current, market }))}>{market}</button>)}</div>
            <div className="sporttery-options">
              {marketQuotes.map((quote) => {
                const selected = form.legs.some((leg) => leg.matchId === quote.matchId && leg.market === quote.market && leg.selection === quote.selection)
                const singleBlocked = form.passType === '单关' && !quote.singleEligible
                return <button key={quote.id} disabled={!quote.available || singleBlocked} className={selected ? 'selected' : ''} onClick={() => chooseQuote(quote)}><span>{quote.selection}</span><strong>{quote.odds?.toFixed(2) ?? '--'}</strong><small>{!quote.available ? '未开售' : singleBlocked ? '不可单关' : quote.singleEligible ? `${quote.recommendation} · 单关` : quote.recommendation}</small></button>
              })}
              {!marketQuotes.length && <div className="market-empty">这份历史快照尚未归档“{form.market}”；不是负期望，而是当时未接入或未开售。</div>}
            </div>
          </>}

          <div className="bet-slip">
            <div className="bet-slip-head"><span>我的票单 · {form.passType}</span><b>{selectedGroups.length}/{requiredMatches} 场 · {form.legs.length} 项</b></div>
            {form.legs.map((leg) => <div className="bet-slip-leg" key={`${leg.matchId}-${leg.market}-${leg.selection}`}><span><b>{leg.matchLabel}</b><small>{leg.market} · {leg.selection}</small></span><strong>{leg.odds.toFixed(2)}</strong><button onClick={() => setForm((current) => ({ ...current, legs: current.legs.filter((item) => item !== leg) }))} aria-label="移除选择"><X size={13} /></button></div>)}
            {!form.legs.length && <p>在上方点击一个赔率选项加入票单。</p>}
            <footer><span>注数 <b>{ticketCount || '--'}</b></span><span>标准票面 <b>{ticketCount ? preciseMoney(calculatedStake) : '--'}</b></span><span>实际投入 <b>{ticketCount && Number.isFinite(actualStake) ? preciseMoney(actualStake) : '--'}</b></span><span>理论最高奖金 <b>{ticketCount ? preciseMoney(actualMaximumPayout) : '--'}</b></span></footer>
          </div>
          <label className="ticket-note">实际投入（元）<input type="number" min="0.01" step="0.01" value={form.actualStake} placeholder={calculatedStake ? `默认 ${calculatedStake.toFixed(2)}` : '选好票后填写'} onChange={(event) => setForm((current) => ({ ...current, actualStake: event.target.value }))} /></label>
          <label className="ticket-note">备注（可选）<input value={form.note} placeholder="例如：临场改主意、跟随自己的判断" onChange={(event) => setForm((current) => ({ ...current, note: event.target.value }))} /></label>
          {message && <p className="personal-form-message">{message}</p>}
          <div className="personal-form-actions"><button onClick={resetForm}>重置</button><button className="primary" onClick={saveBet}>{form.id ? '更新记录' : '保存票单'}</button></div>
        </section>

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
        <div className="personal-panel-title"><div><h2>未来情景模拟（参考）</h2><p>放在真实战绩下方；至少 5 个真实结算日后才启用</p></div><span className="simulation-note">预测区，不计入真实盈利</span></div>
        {projectionReady ? <>
          <div className="strategy-journey-body">
            <div className="strategy-projection-cards">{projection.summaries.map((item) => <div key={item.key} style={{ '--strategy-color': item.color } as CSSProperties}><span>{item.name}</span><strong>{preciseMoney(item.median)}</strong><small>5% {preciseMoney(item.p05)} · 95% {preciseMoney(item.p95)}</small><em>停止概率 {percent(item.stopProbability, 1)} · 中位最大回撤 {percent(item.medianMaxDrawdown, 1)}</em></div>)}</div>
            <StrategyProjectionChart dates={projection.dates} summaries={projection.summaries} />
          </div>
          <p className="projection-disclaimer">未来阶段从已结算日收益分布抽样，不把单日预测优势机械复利。余额不足 2 元时停止下注。</p>
        </> : <div className="projection-locked"><strong>暂不预测终局盈利</strong><span>当前只有 {actual.summaries[0]?.settledDays ?? 0} 个真实结算日；达到 5 个后，才使用真实日收益分布模拟。</span></div>}
      </section>

      <div className="personal-bottom-grid">
        <section className="panel personal-ledger-panel">
          <div className="personal-panel-title"><div><h2>近期投注记录</h2><p>完整票型按基础子注和真实赛果自动结算</p></div><span>{ledger.bets.length} 条</span></div>
          <div className="personal-table-wrap"><table className="personal-ledger-table"><thead><tr><th>出票/比赛</th><th>比赛/票面</th><th>票型</th><th>选择</th><th>注数/倍数</th><th>投入</th><th>来源</th><th>状态</th><th>派彩/盈亏</th><th>操作</th></tr></thead><tbody>{ledger.bets.map((bet) => <tr key={bet.id}><td><strong>{(bet.purchaseDate ?? bet.targetDate).slice(5)}</strong><small>比赛 {bet.targetDate.slice(5)}</small></td><td><strong>{bet.matchLabel}</strong>{bet.note && <small>{bet.note}</small>}</td><td><strong>{bet.passType ?? inferPassType(groupLegsByMatch(bet.legs ?? []).length)}</strong><small>{bet.market}</small></td><td>{bet.selection}</td><td><strong>{bet.ticketCount ?? 1}注</strong><small>{bet.multiple ?? 1}倍</small></td><td>{preciseMoney(bet.stake)}</td><td>{decisionLabels[bet.decisionSource]}</td><td><span className={`bet-status ${bet.status}`}>{statusLabels[bet.status]}</span></td><td>{bet.status === 'settled' ? <><b>{preciseMoney(bet.payout ?? 0)}</b><small className={(bet.payout ?? 0) - bet.stake >= 0 ? 'positive-text' : 'negative-text'}>{preciseMoney((bet.payout ?? 0) - bet.stake)}</small></> : '--'}</td><td><button onClick={() => editBet(bet)} aria-label="编辑"><Pencil size={13} /></button><button onClick={() => removeBet(bet.id)} aria-label="删除"><Trash2 size={13} /></button></td></tr>)}{!ledger.bets.length && <tr><td colSpan={10} className="empty-row">还没有记录。上方点选后只保存在这台浏览器中。</td></tr>}</tbody></table></div>
        </section>
        <section className="panel betting-review-panel">
          <div className="personal-panel-title"><div><h2>下注模式复盘</h2><p>预测准确与资金分配分开检验</p></div></div>
          <div className="review-state"><CircleAlert size={18} /><strong>{comparison.matchedDays < 5 ? '暂不调参' : '进入观察'}</strong></div>
          <p>{reviewText}</p>
          <dl><div><dt>预测层</dt><dd>比分、胜平负、总进球和半全场分别评估概率校准</dd></div><div><dt>下注层</dt><dd>ROI、最大回撤、赔率价值与过关方式分别复盘</dd></div><div><dt>改进门槛</dt><dd>至少 20 个模型日且 bootstrap 优势稳定</dd></div></dl>
        </section>
      </div>
    </main>
  )
}
