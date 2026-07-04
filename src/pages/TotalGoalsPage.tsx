import { useEffect, useMemo, useState } from 'react'
import { Activity, CircleAlert, Crosshair, Database, LockKeyhole, TrendingUp } from 'lucide-react'
import { Flag } from '../components/Flag'
import { beijingTime, percent } from '../lib/format'
import type { MarketQuote, MatchForecast } from '../types'

const goalOrder = ['0', '1', '2', '3', '4', '5', '6', '7+'] as const

interface TotalGoalPoint {
  selection: string
  probability: number
  marketProbability: number | null
  odds: number | null
  robustExpectedReturn: number | null
  recommendation: MarketQuote['recommendation']
  available: boolean
}

export interface TotalGoalsSummary {
  points: TotalGoalPoint[]
  peak: TotalGoalPoint
  core: { label: string; selections: string[]; probability: number }
  zones: Array<{ key: 'low' | 'core' | 'high'; label: string; range: string; probability: number }>
  marketAvailable: boolean
  bestValue: TotalGoalPoint | null
}

const goalValue = (selection: string) => selection === '7+' ? 7 : Number.parseInt(selection, 10)

export function summarizeTotalGoals(match: MatchForecast): TotalGoalsSummary {
  const quotes = match.quotes.filter((quote) => quote.market === '总进球数')
  const bySelection = new Map(quotes.map((quote) => [quote.selection, quote]))
  const points = goalOrder.map((selection) => {
    const quote = bySelection.get(selection)
    return {
      selection,
      probability: quote?.modelProbability ?? 0,
      marketProbability: quote?.marketProbability ?? null,
      odds: quote?.odds ?? null,
      robustExpectedReturn: quote?.robustExpectedReturn ?? null,
      recommendation: quote?.recommendation ?? '未开售',
      available: quote?.available ?? false,
    }
  })
  const peak = points.reduce((best, point) => point.probability > best.probability ? point : best, points[0])
  const localCore = points.slice(0, -1).reduce((best, point, index) => {
    const next = points[index + 1]
    const probability = point.probability + next.probability
    return probability > best.probability
      ? { label: `${point.selection}–${next.selection}球`, selections: [point.selection, next.selection], probability }
      : best
  }, { label: '0–1球', selections: ['0', '1'], probability: points[0].probability + points[1].probability })
  const core = match.totalGoalsCore
    ? { label: match.totalGoalsCore.label, selections: match.totalGoalsCore.selections, probability: match.totalGoalsCore.probability }
    : localCore
  const sum = (selections: string[]) => selections.reduce((total, selection) => total + (bySelection.get(selection)?.modelProbability ?? 0), 0)
  const marketAvailable = points.some((point) => point.available && point.odds !== null && point.marketProbability !== null)
  const bestValue = marketAvailable
    ? points.filter((point) => point.available && point.robustExpectedReturn !== null)
      .reduce<TotalGoalPoint | null>((best, point) => !best || (point.robustExpectedReturn ?? -Infinity) > (best.robustExpectedReturn ?? -Infinity) ? point : best, null)
    : null

  return {
    points,
    peak,
    core,
    zones: [
      { key: 'low', label: '低比分', range: '0–1球', probability: sum(['0', '1']) },
      { key: 'core', label: '中枢', range: '2–3球', probability: sum(['2', '3']) },
      { key: 'high', label: '高比分', range: '4+球', probability: sum(['4', '5', '6', '7+']) },
    ],
    marketAvailable,
    bestValue,
  }
}

function formatTargetDate(targetDate: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  }).format(new Date(`${targetDate}T00:00:00+08:00`))
}

function scoreTotal(score: string) {
  const [home, away] = score.split(':').map(Number)
  return home + away
}

function TotalGoalsChart({ summary, selectedGoal, onSelectGoal }: {
  summary: TotalGoalsSummary
  selectedGoal: string
  onSelectGoal: (goal: string) => void
}) {
  const maxProbability = Math.max(...summary.points.map((point) => point.probability), 0.01)
  return (
    <section className="total-goals-chart" aria-label="总进球数模型概率分布">
      <div className="goal-chart-scale" aria-hidden="true"><span>30%</span><span>20%</span><span>10%</span><span>0%</span></div>
      <div className="goal-bars">
        {summary.points.map((point) => {
          const inCore = summary.core.selections.includes(point.selection)
          return (
            <button
              key={point.selection}
              className={`${inCore ? 'core ' : ''}${selectedGoal === point.selection ? 'selected' : ''}`}
              onClick={() => onSelectGoal(point.selection)}
              aria-label={`${point.selection}球，模型概率${percent(point.probability, 1)}`}
            >
              <strong>{percent(point.probability, 1)}</strong>
              <i style={{ height: `${Math.max(4, point.probability / maxProbability * 100)}%` }} />
              {point.marketProbability !== null && <em style={{ bottom: `${point.marketProbability / maxProbability * 100}%` }} title={`市场概率 ${percent(point.marketProbability, 1)}`} />}
              <span>{point.selection}</span>
              {inCore && <small>核心</small>}
            </button>
          )
        })}
      </div>
    </section>
  )
}

export function TotalGoalsPage({ matches, selectedId, onSelect }: {
  matches: MatchForecast[]
  selectedId: string
  onSelect: (matchId: string) => void
}) {
  const selectedMatch = matches.find((match) => match.id === selectedId) ?? matches[0]
  const summary = useMemo(() => summarizeTotalGoals(selectedMatch), [selectedMatch])
  const [selectedGoal, setSelectedGoal] = useState(summary.peak.selection)

  useEffect(() => {
    setSelectedGoal(summary.peak.selection)
  }, [selectedMatch.id, summary.peak.selection])

  const selectedPoint = summary.points.find((point) => point.selection === selectedGoal) ?? summary.peak
  const scorePaths = selectedMatch.scoreProbabilities
    .filter((score) => scoreTotal(score.score) === goalValue(selectedGoal))
    .sort((left, right) => right.probability - left.probability)
  const totalXg = selectedMatch.expectedGoals.home + selectedMatch.expectedGoals.away
  const comparisonRows = matches.map((match) => ({ match, summary: summarizeTotalGoals(match) }))

  return (
    <main className="total-goals-page">
      <header className="total-goals-title">
        <div><h1>总进球数</h1><p>0–7+ 概率分布 · 核心区间 · 市场价值</p></div>
        <div><strong>{formatTargetDate(selectedMatch.kickoffBeijing.slice(0, 10))} · {matches.length}场比赛</strong><span>赔率未开售时只评估模型概率</span></div>
      </header>

      <nav className="goal-match-tabs" aria-label="选择比赛">
        {matches.map((match) => (
          <button key={match.id} className={match.id === selectedMatch.id ? 'active' : ''} onClick={() => onSelect(match.id)}>
            <Flag flag={match.homeFlag} />
            <strong>{match.homeTeam}<i>vs</i>{match.awayTeam}</strong>
            <span>{beijingTime(match.kickoffBeijing)}</span>
          </button>
        ))}
      </nav>

      <div className="total-goals-primary">
        <section className="panel goal-distribution-panel">
          <div className="goal-match-summary">
            <div className="goal-team home"><Flag flag={selectedMatch.homeFlag} large /><strong>{selectedMatch.homeTeam}</strong></div>
            <span>vs</span>
            <div className="goal-team away"><Flag flag={selectedMatch.awayFlag} large /><strong>{selectedMatch.awayTeam}</strong></div>
            <dl>
              <div><dt>主队 xG</dt><dd>{selectedMatch.expectedGoals.home.toFixed(2)}</dd></div>
              <div><dt>客队 xG</dt><dd>{selectedMatch.expectedGoals.away.toFixed(2)}</dd></div>
              <div><dt>总 xG</dt><dd>{totalXg.toFixed(2)}</dd></div>
              <div><dt>模型覆盖率</dt><dd>{percent(selectedMatch.coverage)}</dd></div>
            </dl>
          </div>
          <div className="goal-chart-heading">
            <div><h2>总进球数概率分布</h2><p>点击任一进球数，查看对应的主要比分路径</p></div>
            <div className="goal-chart-modes"><button className="active">模型概率</button><button disabled={!summary.marketAvailable}>模型 vs 市场 <LockKeyhole size={12} /></button></div>
          </div>
          <TotalGoalsChart summary={summary} selectedGoal={selectedGoal} onSelectGoal={setSelectedGoal} />
        </section>

        <aside className="panel goal-decision-panel">
          <div className="goal-decision-heading"><Crosshair size={18} /><div><h2>决策参考</h2><p>先判断区间，再判断赔率价值</p></div></div>
          <div className="goal-core-call">
            <div><span>核心区间</span><strong>{summary.core.label}</strong></div>
            <div><span>区间概率</span><strong>{percent(summary.core.probability, 1)}</strong></div>
          </div>
          <div className="goal-picks">
            <div><span>首选</span><strong>{summary.peak.selection}球</strong><b>{percent(summary.peak.probability, 1)}</b></div>
            <div><span>当前查看</span><strong>{selectedPoint.selection}球</strong><b>{percent(selectedPoint.probability, 1)}</b></div>
            <div><span>总 xG</span><strong>{totalXg.toFixed(2)}</strong><b>模型中枢</b></div>
          </div>
          <div className="goal-market-state">
            <div><span>当前状态</span><strong>{summary.marketAvailable ? '官方赔率已接入' : '官方赔率未开售'}</strong></div>
            <div><span>建议操作</span><strong className={summary.bestValue && (summary.bestValue.robustExpectedReturn ?? 0) > 0 ? 'positive-text' : ''}>
              {summary.bestValue && (summary.bestValue.robustExpectedReturn ?? 0) > 0 ? `${summary.bestValue.selection}球可进入价值复核` : '仅观察模型，不判定正期望'}
            </strong></div>
          </div>
          <div className="goal-zones">
            {summary.zones.map((zone) => <div key={zone.key} className={zone.key}><span>{zone.label}</span><strong>{zone.range}</strong><b>{percent(zone.probability, 1)}</b></div>)}
          </div>
          <p className="goal-disclaimer"><CircleAlert size={13} />模型概率基于现有数据覆盖与模拟路径，不等于投注建议；赔率开放后才评估市场价值。</p>
        </aside>
      </div>

      <div className="total-goals-secondary">
        <section className="panel goal-comparison-panel">
          <div className="goal-section-heading"><div><h2>全部比赛总进球数对比</h2><p>用相同口径寻找分布更集中、数据更完整的比赛</p></div><Database size={18} /></div>
          <div className="goal-comparison-wrap">
            <table>
              <thead><tr><th>时间</th><th>对阵</th><th>总 xG</th><th>峰值进球数</th><th>核心区间</th><th>覆盖率</th><th>市场状态</th><th>建议状态</th></tr></thead>
              <tbody>{comparisonRows.map(({ match, summary: rowSummary }) => (
                <tr key={match.id} className={match.id === selectedMatch.id ? 'active' : ''} onClick={() => onSelect(match.id)}>
                  <td className="numeric">{beijingTime(match.kickoffBeijing)}</td>
                  <td><strong>{match.homeTeam} vs {match.awayTeam}</strong></td>
                  <td className="numeric">{(match.expectedGoals.home + match.expectedGoals.away).toFixed(2)}</td>
                  <td><b>{rowSummary.peak.selection}球</b><span>{percent(rowSummary.peak.probability, 1)}</span></td>
                  <td><b className="amber-text">{rowSummary.core.label}</b><span>{percent(rowSummary.core.probability, 1)}</span></td>
                  <td><i className="goal-coverage"><em style={{ width: percent(match.coverage) }} /></i><span>{percent(match.coverage)}</span></td>
                  <td>{rowSummary.marketAvailable ? '赔率已接入' : '官方赔率未开售'}</td>
                  <td><span className={rowSummary.marketAvailable ? 'goal-state open' : 'goal-state'}>{rowSummary.marketAvailable ? '等待价值复核' : '仅观察模型'}</span></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </section>

        <section className="panel goal-path-panel">
          <div className="goal-section-heading"><div><h2>比分路径</h2><p>Top 8 比分中，对 {selectedGoal} 球的主要贡献</p></div><Activity size={18} /></div>
          <div className="goal-path-summary"><span>当前进球数</span><strong>{selectedGoal}球</strong><b>{percent(selectedPoint.probability, 1)}</b></div>
          <div className="goal-path-list">
            {scorePaths.length ? scorePaths.map((score) => (
              <div key={score.score}><span>{score.score}</span><p>{selectedMatch.homeTeam} {score.score.replace(':', ' : ')} {selectedMatch.awayTeam}</p><i><em style={{ width: `${Math.min(100, score.probability / selectedPoint.probability * 100)}%` }} /></i><strong>{percent(score.probability, 1)}</strong></div>
            )) : <div className="goal-path-empty"><TrendingUp size={18} /><p>当前 Top 8 比分没有覆盖 {selectedGoal} 球路径，完整概率仍已计入上方分布。</p></div>}
          </div>
          <footer>比分路径只用于解释总进球概率的组成，不把单一比分当作确定结果。</footer>
        </section>
      </div>
    </main>
  )
}
