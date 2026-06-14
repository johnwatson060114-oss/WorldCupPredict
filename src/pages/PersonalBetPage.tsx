import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { CheckCircle2, CircleAlert, Database, Download, Pencil, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { percent, shortDateTime, signedPercent } from '../lib/format'
import type { DailyForecast, SettlementFile } from '../types'
import { FairComparisonChart, StrategyProjectionChart } from '../features/personal-bets/Charts'
import { buildFairComparison, personalSummary, projectToFinal, type ComparisonMode } from '../features/personal-bets/analytics'
import {
  captureModelSnapshot,
  deletePersonalBet,
  exportPersonalLedger,
  loadPersonalLedger,
  personalBalance,
  savePersonalLedger,
  settlePersonalLedger,
  upsertPersonalBet,
} from '../features/personal-bets/storage'
import type { DecisionSource, PersonalBet, PersonalBetLedger, PersonalBetStatus, StrategyHistory } from '../features/personal-bets/types'

interface PersonalBetPageProps {
  forecast: DailyForecast
  settlements: SettlementFile | null
}

interface FormState {
  id: string
  targetDate: string
  matchChoice: string
  customMatch: string
  market: string
  customMarket: string
  selection: string
  customSelection: string
  odds: string
  stake: string
  decisionSource: DecisionSource
  status: PersonalBetStatus
  payout: string
  note: string
}

const decisionLabels: Record<DecisionSource, string> = {
  subjective: '我的主观判断',
  conservative: '参考稳健策略',
  balanced: '参考均衡策略',
  aggressive: '参考激进策略',
}

const statusLabels: Record<PersonalBetStatus, string> = { pending: '待结算', settled: '已结算', void: '作废' }
const preciseMoney = (value: number) => `${value.toFixed(2)}元`

const firstQuote = (forecast: DailyForecast) => forecast.matches[0]?.quotes.find((quote) => quote.available) ?? forecast.matches[0]?.quotes[0]

const initialForm = (forecast: DailyForecast): FormState => {
  const match = forecast.matches[0]
  const quote = firstQuote(forecast)
  return {
    id: '',
    targetDate: forecast.targetDate,
    matchChoice: match?.id ?? '__custom__',
    customMatch: '',
    market: quote?.market ?? '自定义',
    customMarket: '',
    selection: quote?.selection ?? '',
    customSelection: '',
    odds: quote?.odds?.toString() ?? '',
    stake: '2',
    decisionSource: 'subjective',
    status: 'pending',
    payout: '',
    note: '',
  }
}

const quoteFor = (forecast: DailyForecast, matchId: string, market: string, selection: string) =>
  forecast.matches.find((match) => match.id === matchId)?.quotes.find((quote) => quote.market === market && quote.selection === selection)

export function PersonalBetPage({ forecast, settlements }: PersonalBetPageProps) {
  const [ledger, setLedger] = useState<PersonalBetLedger>(() => loadPersonalLedger())
  const [history, setHistory] = useState<StrategyHistory | null>(null)
  const [comparisonMode, setComparisonMode] = useState<ComparisonMode>('matched')
  const [form, setForm] = useState<FormState>(() => initialForm(forecast))
  const [message, setMessage] = useState('')

  useEffect(() => {
    setLedger((current) => {
      const captured = captureModelSnapshot(current, forecast)
      return settlements ? settlePersonalLedger(captured, settlements) : captured
    })
  }, [forecast, settlements])

  useEffect(() => {
    fetch('./data/strategy-history.json', { cache: 'no-store' })
      .then((response) => response.ok ? response.json() as Promise<StrategyHistory> : null)
      .then(setHistory)
      .catch(() => setHistory(null))
  }, [forecast.generatedAt])

  const selectedMatch = forecast.matches.find((match) => match.id === form.matchChoice)
  const marketQuotes = useMemo(() => selectedMatch?.quotes.filter((quote) => quote.market === form.market) ?? [], [selectedMatch, form.market])
  const marketOptions = useMemo(() => [...new Set(selectedMatch?.quotes.map((quote) => quote.market) ?? [])], [selectedMatch])
  const summary = useMemo(() => personalSummary(ledger), [ledger])
  const comparison = useMemo(() => buildFairComparison(ledger, history, comparisonMode), [ledger, history, comparisonMode])
  const projection = useMemo(() => projectToFinal(forecast.portfolios, history, ledger, forecast.targetDate), [forecast.portfolios, forecast.targetDate, history, ledger])

  const resetForm = () => setForm(initialForm(forecast))

  const chooseMatch = (matchChoice: string) => {
    if (matchChoice === '__custom__') {
      setForm((current) => ({ ...current, matchChoice, market: '自定义', selection: '', odds: '' }))
      return
    }
    const match = forecast.matches.find((item) => item.id === matchChoice)
    const quote = match?.quotes.find((item) => item.available) ?? match?.quotes[0]
    setForm((current) => ({
      ...current,
      matchChoice,
      market: quote?.market ?? '自定义',
      selection: quote?.selection ?? '',
      odds: quote?.odds?.toString() ?? '',
    }))
  }

  const chooseMarket = (market: string) => {
    if (market === '自定义') {
      setForm((current) => ({ ...current, market, selection: '', odds: '' }))
      return
    }
    const quote = selectedMatch?.quotes.find((item) => item.market === market)
    setForm((current) => ({ ...current, market, selection: quote?.selection ?? '', odds: quote?.odds?.toString() ?? '' }))
  }

  const chooseSelection = (selection: string) => {
    const quote = selectedMatch?.quotes.find((item) => item.market === form.market && item.selection === selection)
    setForm((current) => ({ ...current, selection, odds: quote?.odds?.toString() ?? current.odds }))
  }

  const saveBet = () => {
    const custom = form.matchChoice === '__custom__'
    const matchLabel = custom ? form.customMatch.trim() : `${selectedMatch?.homeTeam ?? ''} vs ${selectedMatch?.awayTeam ?? ''}`
    const market = form.market === '自定义' ? '自定义' : form.market
    const selection = form.market === '自定义' ? form.customSelection.trim() : form.selection
    const odds = Number(form.odds)
    const stake = Number(form.stake)
    const payout = form.status === 'settled' ? Number(form.payout || 0) : undefined
    if (!matchLabel || !selection || !Number.isFinite(odds) || odds <= 1 || !Number.isFinite(stake) || stake < 2 || stake % 2 !== 0) {
      setMessage('请完整填写比赛、选择、赔率和投注额；投注额至少 2 元且为 2 元整数倍。')
      return
    }
    const quote = custom ? undefined : quoteFor(forecast, form.matchChoice, market, selection)
    const bet: PersonalBet = {
      id: form.id || crypto.randomUUID(),
      createdAt: form.id ? ledger.bets.find((item) => item.id === form.id)?.createdAt ?? new Date().toISOString() : new Date().toISOString(),
      targetDate: form.targetDate,
      matchId: custom ? undefined : form.matchChoice,
      matchLabel,
      market: market as PersonalBet['market'],
      selection,
      odds,
      stake,
      decisionSource: form.decisionSource,
      status: form.status,
      payout,
      settledAt: form.status === 'settled' ? new Date().toISOString() : undefined,
      note: form.note.trim() || undefined,
      forecastGeneratedAt: forecast.generatedAt,
      modelProbability: quote?.modelProbability,
    }
    setLedger((current) => upsertPersonalBet(captureModelSnapshot(current, forecast), bet))
    setMessage(form.id ? '记录已更新。' : '已写入本机投注账本。')
    resetForm()
  }

  const editBet = (bet: PersonalBet) => {
    const matchChoice = bet.matchId && forecast.matches.some((match) => match.id === bet.matchId) ? bet.matchId : '__custom__'
    const knownMarket = matchChoice !== '__custom__' && forecast.matches.find((match) => match.id === matchChoice)?.quotes.some((quote) => quote.market === bet.market)
    setForm({
      id: bet.id,
      targetDate: bet.targetDate,
      matchChoice,
      customMatch: matchChoice === '__custom__' ? bet.matchLabel : '',
      market: knownMarket ? bet.market : '自定义',
      customMarket: knownMarket ? '' : bet.market,
      selection: knownMarket ? bet.selection : '',
      customSelection: knownMarket ? '' : bet.selection,
      odds: bet.odds.toString(),
      stake: bet.stake.toString(),
      decisionSource: bet.decisionSource,
      status: bet.status,
      payout: bet.payout?.toString() ?? '',
      note: bet.note ?? '',
    })
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const removeBet = (id: string) => {
    setLedger((current) => deletePersonalBet(current, id))
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
    setLedger(parsed)
    setMessage('个人投注账本已导入。')
  }

  const usingDemoTeams = forecast.statusMessage.includes('开发样例')
  const dataChecks = [
    { label: '体彩赔率与让球', source: '中国体育彩票', blocked: false, evidence: forecast.evidence.find((item) => item.source.includes('体育彩票')) },
    { label: '阵容、伤停、预计首发', source: 'API-Football', blocked: usingDemoTeams, evidence: forecast.evidence.find((item) => item.source.includes('API-Football')) },
    { label: '场地、天气、海拔', source: 'Open-Meteo + 场馆表', blocked: usingDemoTeams, evidence: forecast.evidence.find((item) => item.source.includes('Open-Meteo')) },
    { label: '停赛、红牌、纪律变化', source: 'API-Football', blocked: usingDemoTeams, evidence: forecast.evidence.find((item) => item.source.includes('API-Football')) },
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
        <div><span>独立本机账本，不影响原资金记录</span><h1>我的投注账本</h1></div>
        <div className="personal-page-actions">
          <button onClick={() => exportPersonalLedger(ledger)}><Download size={14} />导出</button>
          <label><Database size={14} />导入<input type="file" accept="application/json" onChange={(event) => void importLedger(event.target.files?.[0])} /></label>
        </div>
      </div>

      <div className="personal-top-grid">
        <section className="panel personal-entry-panel">
          <div className="personal-panel-title"><div><h2>记一笔投注</h2><p>没采用推荐也可以如实记录</p></div><Plus size={18} /></div>
          <div className="personal-summary-grid">
            <div><span>当前可用</span><strong>{preciseMoney(personalBalance(ledger))}</strong></div>
            <div><span>累计投入</span><strong>{preciseMoney(summary.totalStaked)}</strong></div>
            <div><span>已实现盈亏</span><strong className={summary.realizedProfit >= 0 ? 'positive-text' : 'negative-text'}>{preciseMoney(summary.realizedProfit)}</strong></div>
            <div><span>待结算敞口</span><strong>{preciseMoney(summary.pendingExposure)}</strong></div>
          </div>
          <div className="personal-form">
            <label>比赛日期<input type="date" value={form.targetDate} onChange={(event) => setForm((current) => ({ ...current, targetDate: event.target.value }))} /></label>
            <label>比赛/票面<select value={form.matchChoice} onChange={(event) => chooseMatch(event.target.value)}>{forecast.matches.map((match) => <option key={match.id} value={match.id}>{match.homeTeam} vs {match.awayTeam}</option>)}<option value="__custom__">自定义或串关</option></select></label>
            {form.matchChoice === '__custom__' && <label className="form-wide">自定义票面<input value={form.customMatch} placeholder="例如：德国胜 × 荷兰胜" onChange={(event) => setForm((current) => ({ ...current, customMatch: event.target.value }))} /></label>}
            <label>玩法<select value={form.market} onChange={(event) => chooseMarket(event.target.value)}>{marketOptions.map((market) => <option key={market} value={market}>{market}</option>)}<option value="自定义">自定义</option></select></label>
            {form.market === '自定义' ? <label>选择<input value={form.customSelection} placeholder="填写票面选择" onChange={(event) => setForm((current) => ({ ...current, customSelection: event.target.value }))} /></label> : <label>选择<select value={form.selection} onChange={(event) => chooseSelection(event.target.value)}>{marketQuotes.map((quote) => <option key={quote.id} value={quote.selection}>{quote.selection}</option>)}</select></label>}
            <label>下单赔率<input type="number" min="1.01" step="0.01" value={form.odds} onChange={(event) => setForm((current) => ({ ...current, odds: event.target.value }))} /></label>
            <label>投注额<input type="number" min="2" step="2" value={form.stake} onChange={(event) => setForm((current) => ({ ...current, stake: event.target.value }))} /></label>
            <label>决策来源<select value={form.decisionSource} onChange={(event) => setForm((current) => ({ ...current, decisionSource: event.target.value as DecisionSource }))}>{Object.entries(decisionLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
            <label>状态<select value={form.status} onChange={(event) => setForm((current) => ({ ...current, status: event.target.value as PersonalBetStatus }))}>{Object.entries(statusLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
            {form.status === 'settled' && <label>实际派彩<input type="number" min="0" step="0.01" value={form.payout} onChange={(event) => setForm((current) => ({ ...current, payout: event.target.value }))} /></label>}
            <label className="form-wide">备注<input value={form.note} placeholder="记录临场判断、心情或未采用推荐的原因" onChange={(event) => setForm((current) => ({ ...current, note: event.target.value }))} /></label>
          </div>
          {message && <p className="personal-form-message">{message}</p>}
          <div className="personal-form-actions"><button onClick={resetForm}>重置</button><button className="primary" onClick={saveBet}>{form.id ? '更新记录' : '保存记录'}</button></div>
        </section>

        <section className="panel personal-comparison-panel">
          <div className="personal-panel-title"><div><h2>公平对比</h2><p>默认只比较你和模型都下注的日期</p></div><div className="comparison-tabs"><button className={comparisonMode === 'matched' ? 'active' : ''} onClick={() => setComparisonMode('matched')}>共同下注日</button><button className={comparisonMode === 'all' ? 'active' : ''} onClick={() => setComparisonMode('all')}>所有各自下注日</button></div></div>
          <div className="comparison-metrics">
            <div><span>同口径 ROI</span><strong className="positive-text">{comparison.userRoi === null ? '--' : signedPercent(comparison.userRoi)}</strong><small>我的实际</small></div>
            <div><span>模型 ROI</span><strong>{comparison.modelRoi === null ? '--' : signedPercent(comparison.modelRoi)}</strong><small>均衡策略</small></div>
            <div><span>命中率</span><strong>{comparison.userHitRate === null ? '--' : percent(comparison.userHitRate, 1)}</strong><small>按实际票数</small></div>
            <div><span>共同样本</span><strong>{comparison.matchedDays} 天</strong><small>不足 10 天不定论</small></div>
          </div>
          {comparison.points.length ? <FairComparisonChart comparison={comparison} /> : <div className="personal-chart-empty">完成至少一天结算后，这里会出现你与模型的累计 ROI 曲线。</div>}
          <p className="comparison-footnote">未下注日期不会记为你的亏损；金额不同用 ROI 标准化。切换“所有各自下注日”时只比较各自表现率，不比较总利润。</p>
        </section>

        <aside className="personal-side-stack">
          <section className="panel fairness-rules">
            <div className="personal-panel-title"><div><h2>公平规则</h2><p>防止天数和本金造成假领先</p></div></div>
            <ul>
              <li><strong>共同下注日</strong><span>只取双方同一天有已结算投注的交集。</span></li>
              <li><strong>ROI 标准化</strong><span>收益除以投入，避免谁下注多谁数字大。</span></li>
              <li><strong>样本门槛</strong><span>少于 10 个共同日只展示，不判断优劣。</span></li>
              <li><strong>收盘价差</strong><span>临场赔率尚未稳定归档，暂不伪造 CLV。</span></li>
            </ul>
          </section>
          <section className="panel data-check-panel">
            <div className="personal-panel-title"><div><h2>每日数据检查</h2><p>{shortDateTime(forecast.generatedAt)} 生成</p></div><RefreshCw size={15} /></div>
            <div className="data-check-list">{dataChecks.map((check) => {
              const ok = check.evidence?.status === 'fresh' && !check.blocked
              const state = check.blocked ? '开发样例' : check.evidence?.status ?? 'missing'
              return <div key={check.label} className={ok ? 'ok' : 'warning'}>{ok ? <CheckCircle2 size={14} /> : <CircleAlert size={14} />}<span><b>{check.label}</b><small>{check.source} · {state}</small></span></div>
            })}</div>
          </section>
        </aside>
      </div>

      <section className="panel strategy-journey-panel">
        <div className="personal-panel-title"><div><h2>三策略终局模拟</h2><p>每条路径独立从 200 元滚动到 2026 年 7 月 19 日决赛；余额不足 2 元即停止</p></div><span className="simulation-note">历史用真实结算，未来按当前分布模拟</span></div>
        <div className="strategy-journey-body">
          <div className="strategy-projection-cards">{projection.summaries.map((item) => <div key={item.key} style={{ '--strategy-color': item.color } as CSSProperties}><span>{item.name}</span><strong>{preciseMoney(item.median)}</strong><small>5% {preciseMoney(item.p05)} · 95% {preciseMoney(item.p95)}</small><em>停止概率 {percent(item.stopProbability, 1)} · 中位最大回撤 {percent(item.medianMaxDrawdown, 1)}</em></div>)}</div>
          <StrategyProjectionChart dates={projection.dates} summaries={projection.summaries} />
        </div>
        <p className="projection-disclaimer">这是路径分布而不是承诺收益。未来尚未生成的比赛日沿用当前策略分布；每日 18:00 新预测归档后会逐步用真实当日方案替换。</p>
      </section>

      <div className="personal-bottom-grid">
        <section className="panel personal-ledger-panel">
          <div className="personal-panel-title"><div><h2>近期投注记录</h2><p>自动结算可识别的单场票，自定义串关可手工填写派彩</p></div><span>{ledger.bets.length} 条</span></div>
          <div className="personal-table-wrap"><table className="personal-ledger-table"><thead><tr><th>日期</th><th>比赛/票面</th><th>玩法</th><th>选择</th><th>赔率</th><th>投入</th><th>来源</th><th>状态</th><th>派彩/盈亏</th><th>操作</th></tr></thead><tbody>{ledger.bets.map((bet) => <tr key={bet.id}><td>{bet.targetDate.slice(5)}</td><td><strong>{bet.matchLabel}</strong>{bet.note && <small>{bet.note}</small>}</td><td>{bet.market}</td><td>{bet.selection}</td><td>{bet.odds.toFixed(2)}</td><td>{preciseMoney(bet.stake)}</td><td>{decisionLabels[bet.decisionSource]}</td><td><span className={`bet-status ${bet.status}`}>{statusLabels[bet.status]}</span></td><td>{bet.status === 'settled' ? <><b>{preciseMoney(bet.payout ?? 0)}</b><small className={(bet.payout ?? 0) - bet.stake >= 0 ? 'positive-text' : 'negative-text'}>{preciseMoney((bet.payout ?? 0) - bet.stake)}</small></> : '--'}</td><td><button onClick={() => editBet(bet)} aria-label="编辑"><Pencil size={13} /></button><button onClick={() => removeBet(bet.id)} aria-label="删除"><Trash2 size={13} /></button></td></tr>)}{!ledger.bets.length && <tr><td colSpan={10} className="empty-row">还没有记录。上方录入后只保存在这台浏览器中。</td></tr>}</tbody></table></div>
        </section>
        <section className="panel betting-review-panel">
          <div className="personal-panel-title"><div><h2>下注模式复盘</h2><p>同时反思预测与资金分配</p></div></div>
          <div className="review-state"><CircleAlert size={18} /><strong>{comparison.matchedDays < 5 ? '暂不调参' : '进入观察'}</strong></div>
          <p>{reviewText}</p>
          <dl><div><dt>预测层</dt><dd>比分、胜平负用 Log Loss / RPS 评估</dd></div><div><dt>下注层</dt><dd>ROI、最大回撤、破产率、赔率价值分别评估</dd></div><div><dt>改进门槛</dt><dd>至少 20 个模型日且 bootstrap 优势稳定</dd></div></dl>
        </section>
      </div>
    </main>
  )
}
