import { CloudSun, Database, MapPin, Mountain, UsersRound } from 'lucide-react'
import { percent, shortDateTime } from '../lib/format'
import type { MatchForecast } from '../types'
import { Flag } from '../components/Flag'

export function AnalysisPage({ match }: { match: MatchForecast }) {
  return (
    <main className="content-page analysis-page">
      <div className="page-title">
        <div><span>完整战术推演</span><h1>{match.homeTeam} vs {match.awayTeam}</h1></div>
        <div className="page-meta"><span><MapPin size={14} />{match.venue}</span><span>{match.weather}</span></div>
      </div>
      <section className="analysis-hero panel">
        <div className="formation-side home">
          <Flag flag={match.homeFlag} large /><h2>{match.homeTeam}</h2>
          <strong>{match.expectedGoals.home.toFixed(2)} xG</strong>
        </div>
        <div className="analysis-score"><small>最可能比分</small><b>{match.likelyScore}</b><span>{'★'.repeat(match.scoreStars)}{'☆'.repeat(3 - match.scoreStars)}</span></div>
        <div className="formation-side away">
          <Flag flag={match.awayFlag} large /><h2>{match.awayTeam}</h2>
          <strong>{match.expectedGoals.away.toFixed(2)} xG</strong>
        </div>
      </section>
      <div className="analysis-grid">
        <section className="panel detail-section">
          <div className="section-heading"><div><h2>比分概率矩阵</h2><p>蒙特卡洛模拟后的前八种比分</p></div></div>
          <div className="score-matrix">
            {match.scoreProbabilities.slice(0, 8).map((score, index) => (
              <div className={index === 0 ? 'score-tile top' : 'score-tile'} key={score.score}>
                <strong>{score.score}</strong><span>{percent(score.probability, 1)}</span>{score.odds && <small>奖金 {score.odds.toFixed(2)}</small>}
              </div>
            ))}
          </div>
        </section>
        <section className="panel detail-section">
          <div className="section-heading"><div><h2>因素贡献</h2><p>仅回测稳定的因素进入生产模型</p></div></div>
          <div className="detail-factor-list">
            {match.factors.map((factor) => (
              <div key={factor.label}>
                <span>{factor.label}</span><div className="factor-axis"><i className={factor.direction} style={{ width: `${Math.min(48, Math.abs(factor.value) * 180)}%` }} /></div>
                <strong>{factor.active ? `${factor.value >= 0 ? '+' : ''}${factor.value.toFixed(2)} xG` : '仅展示'}</strong><small>{factor.note}</small>
              </div>
            ))}
          </div>
        </section>
        <section className="panel detail-section evidence-section">
          <div className="section-heading"><div><h2>环境与数据证据</h2><p>所有缺失和人工校正都显式记录</p></div></div>
          <div className="evidence-cards">
            <div><CloudSun /><span>比赛天气</span><strong>{match.weather}</strong></div>
            <div><Mountain /><span>场馆海拔</span><strong>{match.altitude} 米</strong></div>
            <div><Database /><span>数据覆盖</span><strong>{percent(match.coverage)}</strong></div>
            <div><UsersRound /><span>阵容状态</span><strong>预计首发</strong></div>
          </div>
          <div className="missing-box"><strong>缺失数据</strong>{match.missingData.length ? match.missingData.map((item) => <span key={item}>{item}</span>) : <span>无关键缺失</span>}</div>
        </section>
      </div>
    </main>
  )
}

export function EvidenceList({ items }: { items: Array<{ source: string; field: string; observedAt: string; confidence: number; status: string }> }) {
  return <div>{items.map((item) => <div key={`${item.source}-${item.field}`}>{item.source} · {item.field} · {shortDateTime(item.observedAt)}</div>)}</div>
}
