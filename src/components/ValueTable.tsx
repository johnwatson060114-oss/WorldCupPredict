import { ArrowDown, ArrowUp, CircleSlash2, Star } from 'lucide-react'
import { percent, signedPercent } from '../lib/format'
import { effectiveRecommendation, getOutcomeDecision } from '../lib/outcome-confidence'
import type { MarketQuote, MatchForecast } from '../types'

interface ValueTableProps {
  matches: MatchForecast[]
  selectedId: string
  onSelect: (id: string) => void
}

const recommendationClass: Record<string, string> = {
  '重点推荐': 'strong',
  '小注可选': 'positive',
  '观察': 'watch',
  '不建议': 'negative',
  '未开售': 'disabled',
}

const orderedQuotes = (match: MatchForecast): MarketQuote[] =>
  [...match.quotes].sort((a, b) => {
    if (!a.available && b.available) return 1
    if (a.available && !b.available) return -1
    return (b.robustExpectedReturn ?? -99) - (a.robustExpectedReturn ?? -99)
  })

export function ValueTable({ matches, selectedId, onSelect }: ValueTableProps) {
  return (
    <section className="value-panel panel">
      <div className="section-heading value-heading">
        <div>
          <h1>明日体彩价值比较</h1>
          <p>概率经过不确定性折扣；赔率超过 45 分钟自动失效</p>
        </div>
        <div className="table-legend">
          <span><i className="dot teal" />稳健期望为正</span>
          <span><i className="dot amber" />仅观察</span>
          <span><i className="dot red" />负期望</span>
        </div>
      </div>
      <div className="table-wrap">
        <table className="value-table">
          <thead>
            <tr>
              <th>对阵 / 时间</th>
              <th>玩法</th>
              <th>官方固定奖金</th>
              <th>模型概率</th>
              <th>市场概率</th>
              <th>稳健期望</th>
              <th>数据覆盖</th>
              <th>建议</th>
            </tr>
          </thead>
          <tbody>
            {matches.map((match) => {
              const outcomeDecision = getOutcomeDecision(match)
              const quotes = orderedQuotes(match).slice(0, match.id === selectedId ? 5 : 3)
              return quotes.map((quote, index) => {
                const displayedRecommendation = effectiveRecommendation(match, quote)
                return (
                <tr
                  key={quote.id}
                  className={`${match.id === selectedId ? 'selected-group' : ''} ${index === 0 ? 'group-start' : ''}`}
                  onClick={() => onSelect(match.id)}
                >
                  {index === 0 && (
                    <td rowSpan={quotes.length} className="match-cell">
                      <strong>{match.homeTeam} vs {match.awayTeam}</strong>
                      <span>{match.lotteryCode} · {beijingTimeLabel(match.kickoffBeijing)}</span>
                      <small className={outcomeDecision.recommended ? 'confidence-inline recommend' : 'confidence-inline watch'}>
                        胜平负{outcomeDecision.recommended ? '可推荐' : '观望'} · {percent(outcomeDecision.probability)}
                      </small>
                    </td>
                  )}
                  <td>
                    <span className="market-label">{quote.market}</span>
                    <b>{quote.selection}</b>
                    {quote.singleEligible && <span className="single-mark">单关</span>}
                  </td>
                  <td className="numeric">{quote.odds?.toFixed(2) ?? '--'}</td>
                  <td className="numeric">{percent(quote.modelProbability)}</td>
                  <td className="numeric muted">{quote.marketProbability === null ? '--' : percent(quote.marketProbability)}</td>
                  <td className={`numeric edge ${(quote.robustExpectedReturn ?? -1) > 0 ? 'positive-text' : 'negative-text'}`}>
                    {quote.robustExpectedReturn === null ? '--' : signedPercent(quote.robustExpectedReturn)}
                    {quote.robustExpectedReturn !== null && (quote.robustExpectedReturn > 0 ? <ArrowUp size={12} /> : <ArrowDown size={12} />)}
                  </td>
                  <td>
                    <div className="mini-coverage"><span style={{ width: percent(match.coverage) }} /></div>
                    <small>{percent(match.coverage)}</small>
                  </td>
                  <td>
                    <span className={`recommendation ${recommendationClass[displayedRecommendation]}`} title={quote.formalBlockReason ?? quote.reason}>
                      {displayedRecommendation === '重点推荐' && <Star size={12} fill="currentColor" />}
                      {displayedRecommendation === '未开售' && <CircleSlash2 size={12} />}
                      {displayedRecommendation}
                    </span>
                    {quote.marketConflict?.status === 'conflict' && <small className="market-conflict-badge">市场冲突</small>}
                    {quote.formalEligible && <small className="formal-eligible-badge">正式入池</small>}
                  </td>
                </tr>
                )
              })
            })}
          </tbody>
        </table>
      </div>
      <div className="table-note">
        <span>正式入池还要求官方赔率、正稳健期望且模型与市场最大概率差不超过15%。</span>
        <span>点击任一对阵查看右侧战术解释</span>
      </div>
    </section>
  )
}

function beijingTimeLabel(value: string) {
  return value.slice(11, 16)
}
