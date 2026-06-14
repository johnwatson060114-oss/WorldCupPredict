import { CalendarDays, CircleAlert } from 'lucide-react'
import { beijingTime, percent } from '../lib/format'
import type { MatchForecast } from '../types'
import { Flag } from './Flag'

interface MatchRailProps {
  targetDate: string
  matches: MatchForecast[]
  selectedId: string
  onSelect: (id: string) => void
}

export function MatchRail({ targetDate, matches, selectedId, onSelect }: MatchRailProps) {
  const displayDate = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: 'long',
    day: 'numeric',
  }).format(new Date(`${targetDate}T12:00:00+08:00`))

  return (
    <aside className="match-rail panel">
      <div className="rail-title">
        <div>
          <span className="section-kicker">北京时间</span>
          <h2>{displayDate} · {matches.length}场</h2>
        </div>
        <CalendarDays size={17} />
      </div>
      <div className="match-list">
        {matches.map((match) => {
          const normalAvailable = match.quotes.some((quote) => quote.market === '胜平负' && quote.available)
          const handicapAvailable = match.quotes.some((quote) => quote.market === '让球胜平负' && quote.available)
          const marketLabel = normalAvailable ? '胜平负有售' : handicapAvailable ? '仅让球有售' : '未开售'
          return (
            <button
              key={match.id}
              className={selectedId === match.id ? 'match-card selected' : 'match-card'}
              onClick={() => onSelect(match.id)}
            >
              <div className="match-card-head">
                <span className="kickoff">{beijingTime(match.kickoff)}</span>
                <span className={normalAvailable || handicapAvailable ? 'market-state open' : 'market-state'}>
                  {marketLabel}
                </span>
              </div>
              <div className="team-line">
                <Flag flag={match.homeFlag} />
                <strong>{match.homeTeam}</strong>
              </div>
              <div className="team-line">
                <Flag flag={match.awayFlag} />
                <strong>{match.awayTeam}</strong>
              </div>
              <div className="match-odds">
                <span>{percent(match.outcomeProbabilities.home)}</span>
                <span>{percent(match.outcomeProbabilities.draw)}</span>
                <span>{percent(match.outcomeProbabilities.away)}</span>
              </div>
              <div className="match-prediction">
                <span>最可能比分 <b>{match.likelyScore}</b></span>
                <span>{match.scoreStars ? '★'.repeat(match.scoreStars) : '低集中度'}</span>
              </div>
              <div className="coverage-row">
                <span>数据 {percent(match.coverage)}</span>
                <span className="coverage-track"><i style={{ width: percent(match.coverage) }} /></span>
              </div>
              {match.missingData.length > 0 && (
                <span className="missing-hint"><CircleAlert size={12} />{match.missingData.length} 项缺失</span>
              )}
            </button>
          )
        })}
      </div>
      <div className="rail-legend">
        <span><b>★</b> 比分集中度</span>
        <span>蓝线 数据覆盖</span>
      </div>
    </aside>
  )
}
