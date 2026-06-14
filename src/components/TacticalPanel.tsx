import { ArrowRight, CloudSun, Mountain, RotateCcw, ShieldCheck, Shirt, Users } from 'lucide-react'
import { percent } from '../lib/format'
import type { MatchForecast } from '../types'
import { Flag } from './Flag'

interface TacticalPanelProps {
  match: MatchForecast
  onOpenDetail: () => void
}

const factorIcons = [ShieldCheck, Shirt, Users, RotateCcw, Mountain, CloudSun]

export function TacticalPanel({ match, onOpenDetail }: TacticalPanelProps) {
  const { home, draw, away } = match.outcomeProbabilities
  return (
    <aside className="tactical-panel panel">
      <div className="section-heading compact">
        <div>
          <h2>为什么模型这样判断</h2>
          <p>战术是概率的解释层，不是主观加分</p>
        </div>
      </div>
      <div className="tactical-matchup">
        <div className="team-block"><Flag flag={match.homeFlag} /><strong>{match.homeTeam}</strong></div>
        <div className="score-block"><small>最可能比分</small><b>{match.likelyScore}</b></div>
        <div className="team-block right"><Flag flag={match.awayFlag} /><strong>{match.awayTeam}</strong></div>
      </div>
      <div className="stars-row">
        <span>{'★'.repeat(match.scoreStars)}{'☆'.repeat(3 - match.scoreStars)}</span>
        <small>星级表示比分分布集中度，不代表稳赚</small>
      </div>
      <div className="xg-row">
        <div><strong>{match.expectedGoals.home.toFixed(2)}</strong><span>主队 xG</span></div>
        <div className="xg-divider" />
        <div><strong>{match.expectedGoals.away.toFixed(2)}</strong><span>客队 xG</span></div>
      </div>
      <div className="outcome-bar" aria-label="胜平负概率">
        <span className="home" style={{ width: percent(home) }} />
        <span className="draw" style={{ width: percent(draw) }} />
        <span className="away" style={{ width: percent(away) }} />
      </div>
      <div className="outcome-labels">
        <span>胜 <b>{percent(home)}</b></span>
        <span>平 <b>{percent(draw)}</b></span>
        <span>负 <b>{percent(away)}</b></span>
      </div>
      <div className="score-list">
        {match.scoreProbabilities.slice(0, 4).map((score) => (
          <div key={score.score}>
            <span>{score.score}</span><i><b style={{ width: percent(score.probability / match.scoreProbabilities[0].probability) }} /></i>
            <strong>{percent(score.probability, 1)}</strong>
          </div>
        ))}
      </div>
      <div className="factor-list">
        {match.factors.map((factor, index) => {
          const Icon = factorIcons[index] ?? ShieldCheck
          return (
            <div className={factor.active ? 'factor active' : 'factor inactive'} key={factor.label}>
              <span className="factor-icon"><Icon size={15} /></span>
              <div><strong>{factor.label}</strong><small>{factor.note}</small></div>
              <b className={factor.direction}>{factor.direction === 'home' ? '主队↑' : factor.direction === 'away' ? '客队↑' : '中性→'}</b>
            </div>
          )
        })}
      </div>
      <div className="uncertainty-note">
        随机波动通过 100,000 次模拟进入比分分布，不直接抬高或压低任何一方 xG。
      </div>
      <button className="outline-button wide" onClick={onOpenDetail}>查看完整战术推演 <ArrowRight size={15} /></button>
    </aside>
  )
}
