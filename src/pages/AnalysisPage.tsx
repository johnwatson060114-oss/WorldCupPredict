import { CloudSun, Database, MapPin, Mountain, UsersRound } from 'lucide-react'
import { percent, shortDateTime } from '../lib/format'
import type { MatchForecast } from '../types'
import { Flag } from '../components/Flag'

export function AnalysisPage({ match }: { match: MatchForecast }) {
  const standardErrors = match.simulation ? Object.values(match.simulation.monteCarloStandardError) : []
  const maxStandardError = standardErrors.length ? Math.max(...standardErrors) : null
  const finalConvergence = match.simulation?.convergence.at(-1)
  const finalFourStageLabel = match.finalFourContext
    ? ({ SEMI_FINAL: '半决赛', FINAL: '决赛', THIRD_PLACE: '季军赛' } as const)[match.finalFourContext.stage]
    : null
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
        {match.finalFourContext && match.finalFourModel && (
          <section className="panel detail-section evidence-section">
            <div className="section-heading"><div><h2>末四场 90 分钟模型</h2><p>所有胜平负、让球、总进球和比分概率由同一常规时间比分矩阵派生</p></div></div>
            <div className="model-breakdown-grid">
              <div><span>比赛阶段</span><strong>{finalFourStageLabel}</strong></div>
              <div><span>预测口径</span><strong>常规时间 90 分钟</strong></div>
              <div><span>解说训练总 xG 系数</span><strong>{match.finalFourContext.stageParameters.candidateTotalXgMultiplier.toFixed(2)}</strong></div>
              <div><span>历史逐场解说样本</span><strong>{match.finalFourContext.stageParameters.trainingMatches ?? '--'} 场</strong></div>
              <div><span>价值安全边际</span><strong>{percent(match.finalFourModel.valueProbabilityGap)}</strong></div>
              <div><span>主胜 95% 区间</span><strong>{match.finalFourModel.confidence95.home.map((value) => percent(value, 1)).join(' - ')}</strong></div>
              <div><span>平局 95% 区间</span><strong>{match.finalFourModel.confidence95.draw.map((value) => percent(value, 1)).join(' - ')}</strong></div>
              <div><span>客胜 95% 区间</span><strong>{match.finalFourModel.confidence95.away.map((value) => percent(value, 1)).join(' - ')}</strong></div>
              <div><span>最终判断</span><strong>{match.finalFourModel.conclusion}</strong></div>
            </div>
            {match.finalFourContext.diagnosticOnly && <div className="missing-box"><strong>安全门控</strong><span>该阶段的逐分钟解说节奏未通过留一届赛事验证，当前不直接改写 xG，只收紧不确定性与价值判定。</span></div>}
            {match.tournamentEvidence && <div className="missing-box"><strong>本届淘汰赛过程与加时负荷</strong><span>{match.tournamentEvidence.home.team}：读取 {match.tournamentEvidence.home.commentaryMatchesUsed} 场解说，后90分钟负荷 {percent(match.tournamentEvidence.home.post90LoadSeverity)}，疲劳修正 {match.tournamentEvidence.home.fatigueAttackDelta.toFixed(3)} xG</span><span>{match.tournamentEvidence.away.team}：读取 {match.tournamentEvidence.away.commentaryMatchesUsed} 场解说，后90分钟负荷 {percent(match.tournamentEvidence.away.post90LoadSeverity)}，疲劳修正 {match.tournamentEvidence.away.fatigueAttackDelta.toFixed(3)} xG</span></div>}
          </section>
        )}
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
                <strong>{factor.active ? `${factor.value >= 0 ? '+' : ''}${factor.value.toFixed(2)} xG` : '仅观察'}</strong><small>{factor.note}</small>
                <em>{factor.admissionStatus === 'core' ? '核心模型输入' : factor.admissionStatus === 'enabled' ? '已通过样本外准入' : factor.admissionReason ?? '等待消融回测'}</em>
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
        <section className="panel detail-section audit-section">
          <div className="section-heading"><div><h2>模拟质量</h2><p>实际路径、抽样误差和收敛记录</p></div></div>
          <div className="audit-grid">
            <div><span>实际路径</span><strong>{match.simulation?.actualPaths.toLocaleString() ?? '旧格式'}</strong></div>
            <div><span>最大标准误差</span><strong>{maxStandardError === null ? '--' : percent(maxStandardError, 2)}</strong></div>
            <div><span>最终收敛变化</span><strong>{finalConvergence?.maxDeltaFromPrevious == null ? '--' : percent(finalConvergence.maxDeltaFromPrevious, 2)}</strong></div>
          </div>
          <div className="audit-list">
            {match.simulation?.convergence.map((item) => <div key={item.paths}><b>{item.paths.toLocaleString()} 路径</b><span>胜 {percent(item.outcomes.home, 1)} · 平 {percent(item.outcomes.draw, 1)} · 负 {percent(item.outcomes.away, 1)}</span></div>) ?? <p>该快照尚未包含新版收敛记录。</p>}
          </div>
        </section>
        <section className="panel detail-section audit-section">
          <div className="section-heading"><div><h2>模型分解与首轮状态</h2><p>总进球环境、实力分配和短期状态分开记录</p></div></div>
          <div className="model-breakdown-grid">
            <div><span>长期基线</span><strong>{match.modelDecomposition?.longTermExpectedGoals ? `${match.modelDecomposition.longTermExpectedGoals.home.toFixed(2)} - ${match.modelDecomposition.longTermExpectedGoals.away.toFixed(2)}` : '旧格式'}</strong></div>
            <div><span>首轮净修正</span><strong>{match.modelDecomposition?.tournamentFormNet ? `${match.modelDecomposition.tournamentFormNet.home >= 0 ? '+' : ''}${match.modelDecomposition.tournamentFormNet.home.toFixed(3)} / ${match.modelDecomposition.tournamentFormNet.away >= 0 ? '+' : ''}${match.modelDecomposition.tournamentFormNet.away.toFixed(3)}` : '0 / 0'}</strong></div>
            <div><span>最终 xG</span><strong>{match.expectedGoals.home.toFixed(2)} - {match.expectedGoals.away.toFixed(2)}</strong></div>
            <div><span>Elo 份额权重</span><strong>{match.modelDecomposition?.eloAllocationWeight === undefined ? '--' : `${Math.round(match.modelDecomposition.eloAllocationWeight * 100)}%`}</strong></div>
            <div><span>文字赛况</span><strong>只做证据标签</strong></div>
          </div>
          <div className="audit-list">
            {match.tournamentForm ? <>
              <div><b>{match.tournamentForm.home.team}</b><span>{match.tournamentForm.home.summary}</span><small>进攻 {match.tournamentForm.home.attackDelta >= 0 ? '+' : ''}{match.tournamentForm.home.attackDelta.toFixed(3)} · 防守 {match.tournamentForm.home.defenseDelta >= 0 ? '+' : ''}{match.tournamentForm.home.defenseDelta.toFixed(3)} · 衰减 {percent(match.tournamentForm.home.decay)}</small></div>
              <div><b>{match.tournamentForm.away.team}</b><span>{match.tournamentForm.away.summary}</span><small>进攻 {match.tournamentForm.away.attackDelta >= 0 ? '+' : ''}{match.tournamentForm.away.attackDelta.toFixed(3)} · 防守 {match.tournamentForm.away.defenseDelta >= 0 ? '+' : ''}{match.tournamentForm.away.defenseDelta.toFixed(3)} · 衰减 {percent(match.tournamentForm.away.decay)}</small></div>
            </> : <p>该快照尚未包含首轮状态层。</p>}
          </div>
        </section>
        <section className="panel detail-section audit-section">
          <div className="section-heading"><div><h2>停赛与替补价值</h2><p>只应用可追踪的首发-替补差值</p></div></div>
          <div className="audit-list">
            {match.lineupImpact?.length ? match.lineupImpact.map((impact) => (
              <div key={`${impact.starterId}-${impact.replacementId ?? 'missing'}`}>
                <b>{impact.starter} → {impact.replacement ?? '缺少可靠替补值'}</b>
                <span>{impact.position} · 进攻差 {impact.attackDelta?.toFixed(3) ?? '--'} · 防守差 {impact.defenseDelta?.toFixed(3) ?? '--'}</span>
                <small>{impact.modelVersion}</small>
              </div>
            )) : <p>本场没有可追踪的确定停赛替换调整。</p>}
          </div>
        </section>
        <section className="panel detail-section audit-section">
          <div className="section-heading"><div><h2>结构化赛前情报</h2><p>保留来源、时间、确认等级和冲突</p></div></div>
          <div className="audit-list">
            {match.intelligence?.length ? match.intelligence.map((item) => (
              <div key={item.event_id}>
                <b>{item.subject.name} · {item.confirmation}</b>
                <span>{item.claim}</span>
                <a href={item.source_url} target="_blank" rel="noreferrer">来源 · {shortDateTime(item.published_at)}</a>
              </div>
            )) : <p>本场没有截止时间前的结构化情报快照。</p>}
          </div>
        </section>
      </div>
    </main>
  )
}

export function EvidenceList({ items }: { items: Array<{ source: string; field: string; observedAt: string; confidence: number; status: string }> }) {
  return <div>{items.map((item) => <div key={`${item.source}-${item.field}`}>{item.source} · {item.field} · {shortDateTime(item.observedAt)}</div>)}</div>
}
