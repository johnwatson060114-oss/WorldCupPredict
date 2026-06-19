import { CalendarRange, Route } from 'lucide-react'
import { percent, shortDateTime } from '../lib/format'
import { getOutcomeDecision } from '../lib/outcome-confidence'
import type { MatchForecast } from '../types'

interface ForecastHorizonProps {
  targetDate: string
  matches: MatchForecast[]
}

const displayDate = (date: string) => new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  month: 'long',
  day: 'numeric',
}).format(new Date(`${date}T12:00:00+08:00`))

export function ForecastHorizon({ targetDate, matches }: ForecastHorizonProps) {
  if (!matches.length) return null

  const lastMatch = matches.reduce((latest, match) =>
    new Date(match.kickoffBeijing).getTime() > new Date(latest.kickoffBeijing).getTime() ? match : latest)
  const recommendedCount = matches.filter((match) => getOutcomeDecision(match).recommended).length

  return (
    <section className="forecast-horizon panel" aria-label="混合串关预测范围">
      <div className="horizon-summary">
        <span className="horizon-icon"><CalendarRange size={18} /></span>
        <div>
          <small>当天投注单</small>
          <strong>仅限 {displayDate(targetDate)} · 当天比赛</strong>
          <em>不会把后续日期比赛混入当天票</em>
        </div>
      </div>
      <div className="horizon-route">
        <div className="horizon-route-title">
          <span><Route size={14} /> 混合串关预测至体彩末场</span>
          <b>{lastMatch.lotteryCode} · {shortDateTime(lastMatch.kickoffBeijing)}</b>
          <small>{matches.length} 场后续比赛 · {recommendedCount} 场达到60%推荐线</small>
        </div>
        <div className="horizon-match-list">
          {matches.map((match) => {
            const decision = getOutcomeDecision(match)
            return (
              <article className={decision.recommended ? 'horizon-match recommended' : 'horizon-match watch'} key={match.id}>
                <header><span>{match.lotteryCode}</span><time>{shortDateTime(match.kickoffBeijing)}</time></header>
                <p>{match.homeTeam} <i>vs</i> {match.awayTeam}</p>
                <footer>
                  <strong>{decision.label} {percent(decision.probability)}</strong>
                  <span>{match.likelyScore}</span>
                </footer>
              </article>
            )
          })}
        </div>
      </div>
    </section>
  )
}
