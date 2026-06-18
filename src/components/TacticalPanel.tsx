import { ArrowRight, CloudSun, Mountain, RotateCcw, ShieldCheck, Shirt, Users } from 'lucide-react'
import { percent } from '../lib/format'
import { getOutcomeDecision } from '../lib/outcome-confidence'
import type { MatchForecast } from '../types'
import { Flag } from './Flag'

interface TacticalPanelProps {
  match: MatchForecast
  onOpenDetail: () => void
}

const factorIcons = [ShieldCheck, Shirt, Users, RotateCcw, Mountain, CloudSun]

export function TacticalPanel({ match, onOpenDetail }: TacticalPanelProps) {
  const { home, draw, away } = match.outcomeProbabilities
  const outcomeDecision = getOutcomeDecision(match)
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
      {match.modelDecomposition?.longTermExpectedGoals && (
        <div className="model-decomposition-inline">
          <span>长期基线 {match.modelDecomposition.longTermExpectedGoals.home.toFixed(2)}-{match.modelDecomposition.longTermExpectedGoals.away.toFixed(2)}</span>
          <b>首轮状态 {match.tournamentForm?.applied ? '有界生效' : '未改变均值'}</b>
        </div>
      )}
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
      <div className={outcomeDecision.recommended ? 'outcome-confidence recommend' : 'outcome-confidence watch'}>
        <div><strong>{outcomeDecision.recommended ? '可推荐' : '观望'}</strong><span>胜平负最高概率门槛 60%</span></div>
        <b>{outcomeDecision.label} {percent(outcomeDecision.probability)}</b>
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
              <b className={factor.direction}>{factor.active ? (factor.direction === 'home' ? '主队↑' : factor.direction === 'away' ? '客队↑' : '已启用') : '仅观察'}</b>
            </div>
          )
        })}
      </div>
      <div className="uncertainty-note">
        实际路径数 {match.simulation?.actualPaths.toLocaleString() ?? '100,000'}；文字赛况只提供标签和置信度，不能直接修改 xG。
      </div>
      <button className="outline-button wide" onClick={onOpenDetail}>查看完整战术推演 <ArrowRight size={15} /></button>
    </aside>
  )
}
