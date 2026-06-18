import { useEffect, useMemo, useState } from 'react'
import { BookOpenText, CircleAlert, Filter, ShieldCheck } from 'lucide-react'
import { percent } from '../lib/format'
import type { FirstRoundReview, FirstRoundTeamProfile } from '../types'

const statusLabel = {
  above_expectation: '高于预期',
  near_expectation: '接近预期',
  below_expectation: '低于预期',
}

const statusClass = {
  above_expectation: 'positive',
  near_expectation: 'neutral',
  below_expectation: 'negative',
}

function ProfileCard({ profile }: { profile: FirstRoundTeamProfile }) {
  const sources = profile.commentaryEvidence.sources
  return (
    <article className="round-team-card panel">
      <header>
        <div><span>{profile.teamEn}</span><h2>{profile.team}</h2></div>
        <b className={statusClass[profile.performanceStatus]}>{statusLabel[profile.performanceStatus]}</b>
      </header>
      <div className="round-scoreline">
        <strong>{profile.scoreFor}-{profile.scoreAgainst}</strong>
        <span>首轮对阵 {profile.opponent}</span>
      </div>
      <p>{profile.summary}</p>
      <div className="round-form-deltas">
        <div><span>进攻状态</span><strong>{profile.objectiveForm.attackDelta >= 0 ? '+' : ''}{profile.objectiveForm.attackDelta.toFixed(3)} xG</strong></div>
        <div><span>防守状态</span><strong>{profile.objectiveForm.defenseDelta >= 0 ? '+' : ''}{profile.objectiveForm.defenseDelta.toFixed(3)} xG</strong></div>
        <div><span>证据置信</span><strong>{percent(profile.evidenceConfidence)}</strong></div>
      </div>
      <div className="round-admission">
        <ShieldCheck size={14} />
        <span>{profile.objectiveForm.admissionStatus === 'enabled' ? '有界状态已入模' : '只观察，不改概率'}</span>
        {profile.objectiveForm.redCardAdjusted && <i>红牌干扰已收缩</i>}
        {profile.objectiveForm.finishingOutlierShrunk && <i>终结异常已收缩</i>}
      </div>
      <div className="round-evidence">
        {sources.map((source) => (
          <a href={source.url} target="_blank" rel="noreferrer" key={`${profile.team}-${source.type}`}>
            <BookOpenText size={13} />
            <span>{source.type === 'official_result' ? '官方赛果' : '文字赛况入口'}</span>
            <small>{source.archivedText ? '已归档' : '正文未归档'}</small>
          </a>
        ))}
      </div>
      <footer><CircleAlert size={13} />七项战术维度因逐分钟正文未归档而暂不评分，避免用比分反推比赛过程。</footer>
    </article>
  )
}

export function FirstRoundPage() {
  const [review, setReview] = useState<FirstRoundReview | null>(null)
  const [filter, setFilter] = useState<'all' | FirstRoundTeamProfile['performanceStatus']>('all')

  useEffect(() => {
    fetch('./data/first-round-review.json', { cache: 'no-store' })
      .then((response) => response.ok ? response.json() as Promise<FirstRoundReview> : null)
      .then(setReview)
      .catch(() => setReview(null))
  }, [])

  const teams = useMemo(
    () => review?.teams.filter((team) => filter === 'all' || team.performanceStatus === filter) ?? [],
    [review, filter],
  )

  if (!review) return <main className="empty-forecast-panel"><h1>首轮评估数据读取中</h1><p>等待文字赛况与官方赛果档案。</p></main>

  return (
    <main className="content-page first-round-page">
      <div className="page-title">
        <div><span>文字赛况证据层 · 不用语音</span><h1>小组赛第一轮球队评估</h1></div>
        <p>24场 · 48队 · {review.round.totalGoals}球 · 场均 {review.round.averageGoals.toFixed(3)} 球</p>
      </div>
      <section className="round-method panel">
        <div><strong>状态修正上限</strong><span>单队单方向 ±{review.method.stateCapPerTeamDirectionXg.toFixed(2)} xG</span></div>
        <div><strong>是否首轮拟合</strong><span>{review.method.conversionWasFitOnFirstRound ? '是' : '否，使用预先固定的小幅转换'}</span></div>
        <div><strong>文字直接改概率</strong><span>{review.method.commentaryDirectlyChangesProbability ? '允许' : '禁止'}</span></div>
        <div><strong>生产策略</strong><span>短期状态有界生效，分布模型继续影子观察</span></div>
      </section>
      <div className="round-filter">
        <Filter size={15} />
        {([
          ['all', '全部48队'],
          ['above_expectation', '高于预期'],
          ['near_expectation', '接近预期'],
          ['below_expectation', '低于预期'],
        ] as const).map(([key, label]) => <button className={filter === key ? 'active' : ''} onClick={() => setFilter(key)} key={key}>{label}</button>)}
      </div>
      <section className="round-team-grid">{teams.map((profile) => <ProfileCard profile={profile} key={profile.team} />)}</section>
    </main>
  )
}
