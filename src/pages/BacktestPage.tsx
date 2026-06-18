import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, CircleAlert, MinusCircle } from 'lucide-react'
import type { DailyForecast, TotalGoalsModelReview } from '../types'
import type { StrategyHistory, StrategyHistoryDay } from '../features/personal-bets/types'

const icons = { good: CheckCircle2, neutral: MinusCircle, warning: CircleAlert }

export function BacktestPage({ forecast }: { forecast: DailyForecast }) {
  const [reviewDay, setReviewDay] = useState<StrategyHistoryDay | null>(null)
  const [strategyHistory, setStrategyHistory] = useState<StrategyHistory | null>(null)
  const [modelReview, setModelReview] = useState<TotalGoalsModelReview | null>(null)
  const [oddsSnapshotStats, setOddsSnapshotStats] = useState({ snapshots: 0, closing: 0 })
  useEffect(() => {
    Promise.all([
      fetch('./data/strategy-history.json', { cache: 'no-store' }).then((response) => response.ok ? response.json() as Promise<StrategyHistory> : null),
      fetch('./data/total-goals-model-review.json', { cache: 'no-store' }).then((response) => response.ok ? response.json() as Promise<TotalGoalsModelReview> : null),
      fetch('./data/odds-history/index.json', { cache: 'no-store' }).then((response) => response.ok ? response.json() as Promise<{ snapshots: Array<{ closingWindowMatches: number }> }> : null),
    ])
      .then(([history, review, oddsIndex]) => {
        setStrategyHistory(history)
        setReviewDay([...(history?.days ?? [])].reverse().find((day) => day.review) ?? null)
        setModelReview(review)
        setOddsSnapshotStats({
          snapshots: oddsIndex?.snapshots.length ?? 0,
          closing: oddsIndex?.snapshots.reduce((sum, item) => sum + item.closingWindowMatches, 0) ?? 0,
        })
      })
      .catch(() => {
        setReviewDay(null)
        setStrategyHistory(null)
        setModelReview(null)
        setOddsSnapshotStats({ snapshots: 0, closing: 0 })
      })
  }, [forecast.generatedAt])
  const separatedMetrics = useMemo(() => {
    const reviewedMatches = strategyHistory?.days.flatMap((day) => day.review?.matches ?? []) ?? []
    const settledStrategies = strategyHistory?.days.flatMap((day) => day.strategies)
      .filter((strategy) => strategy.status === 'settled' && strategy.profit !== null) ?? []
    const strategyStake = settledStrategies.reduce((sum, strategy) => sum + strategy.stake, 0)
    const strategyProfit = settledStrategies.reduce((sum, strategy) => sum + (strategy.profit ?? 0), 0)
    const outcomeHits = reviewedMatches.filter((match) => match.outcomeCorrect).length
    const scoreHits = reviewedMatches.filter((match) => match.exactScore).length
    return {
      outcome: reviewedMatches.length ? outcomeHits / reviewedMatches.length : null,
      score: reviewedMatches.length ? scoreHits / reviewedMatches.length : null,
      reviewedMatches: reviewedMatches.length,
      totalGoals: modelReview?.currentModel.exact_accuracy ?? null,
      totalGoalMatches: modelReview?.currentModel.matches ?? 0,
      strategyRoi: strategyStake ? strategyProfit / strategyStake : null,
      strategyStake,
      strategyProfit,
    }
  }, [strategyHistory, modelReview])
  const actualPaths = forecast.simulationQuality?.actualPaths ?? forecast.simulations
  const snapshotFiles = forecast.dataSnapshot?.files.length ?? 0
  const uncertainty = forecast.simulationQuality?.parameterUncertainty === 'posterior_or_bootstrap_samples'
    ? '后验/Bootstrap'
    : '固定参数'
  return (
    <main className="content-page">
      <div className="page-title"><div><span>严格按时间顺序评估</span><h1>回测与校准</h1></div><p>每天北京时间 13:00 先结算赛果再刷新回测；赛后数据绝不进入赛前特征。</p></div>
      <div className="metric-grid">
        {forecast.backtest.map((metric) => { const Icon = icons[metric.status]; return <section className={`metric-card panel ${metric.status}`} key={metric.label}><Icon size={20}/><span>{metric.label}</span><strong>{metric.value}</strong><p>{metric.note}</p></section> })}
      </div>
      <section className="separated-backtest-grid">
        <article className="panel separated-metric"><span>胜平负</span><strong>{separatedMetrics.outcome === null ? '--' : `${Math.round(separatedMetrics.outcome * 100)}%`}</strong><p>{separatedMetrics.reviewedMatches}场赛前快照；同时看Log Loss，不用命中率单独调参。</p></article>
        <article className="panel separated-metric"><span>精确比分</span><strong>{separatedMetrics.score === null ? '--' : `${Math.round(separatedMetrics.score * 100)}%`}</strong><p>{separatedMetrics.reviewedMatches}场；高方差市场，仅作为分布诊断。</p></article>
        <article className="panel separated-metric"><span>总进球数</span><strong>{separatedMetrics.totalGoals === null ? '--' : `${Math.round(separatedMetrics.totalGoals * 100)}%`}</strong><p>{separatedMetrics.totalGoalMatches}场精确档命中；生产与影子模型分开比较。</p></article>
        <article className="panel separated-metric"><span>投注策略</span><strong>{separatedMetrics.strategyRoi === null ? '--' : `${separatedMetrics.strategyRoi >= 0 ? '+' : ''}${Math.round(separatedMetrics.strategyRoi * 100)}%`}</strong><p>已结算投入 {separatedMetrics.strategyStake.toFixed(0)} 元，盈亏 {separatedMetrics.strategyProfit >= 0 ? '+' : ''}{separatedMetrics.strategyProfit.toFixed(2)} 元。</p></article>
      </section>
      {modelReview && <section className="model-review-panel panel">
        <div className="postmatch-heading">
          <div><span>生产 / 影子双轨</span><h2>模型采用状态</h2></div>
          <b className={`adoption-state ${modelReview.adoptionDecision.status}`}>{modelReview.adoptionDecision.status === 'switch' ? '切换' : modelReview.adoptionDecision.status === 'observe' ? '观察' : '保持'}</b>
        </div>
        <div className="model-review-grid">
          {[modelReview.currentModel, modelReview.shadowModel, modelReview.tailShadowModel].filter(Boolean).map((model) => <article key={model!.spec}>
            <span>{model!.role === 'production' ? '生产模型' : model!.role === 'shadow_only' ? '高比分尾部影子' : '候选影子模型'}</span>
            <strong>{model!.spec}</strong>
            <p>精确档 {Math.round(model!.exact_accuracy * 100)}% · Log Loss {model!.average_log_loss.toFixed(3)}{model!.average_rps === undefined ? '' : ` · RPS ${model!.average_rps.toFixed(3)}`}</p>
          </article>)}
        </div>
        <p className="model-review-decision">{modelReview.adoptionDecision.recommendation_zh}</p>
        {modelReview.strengthAllocationPolicy && <p className="model-review-decision">
          双方份额：Elo 权重 {Math.round(modelReview.strengthAllocationPolicy.eloAllocationWeight * 100)}%，
          仅用 {modelReview.strengthAllocationPolicy.validationYears.join('、')} 年时间滚动验证
          （{modelReview.strengthAllocationPolicy.validationMatches} 场），明确排除 {modelReview.strengthAllocationPolicy.excludedYears.join('、')}。
        </p>}
      </section>}
      {reviewDay?.review && <section className="postmatch-review panel">
        <div className="postmatch-heading">
          <div><span>{reviewDay.review.snapshotLabel}</span><h2>{reviewDay.targetDate} · 四场赛后分析</h2></div>
          <p>使用 {reviewDay.generatedAt.replace('T', ' ').slice(0, 16)} 的赛前预测快照，对照真实赛果。</p>
        </div>
        <div className="postmatch-summary">
          <div><span>赛果方向</span><strong>{Math.round(reviewDay.review.summary.outcomeAccuracy * 100)}%</strong><small>{Math.round(reviewDay.review.summary.outcomeAccuracy * reviewDay.review.summary.matchCount)}/{reviewDay.review.summary.matchCount} 场</small></div>
          <div><span>精确比分</span><strong>{Math.round(reviewDay.review.summary.exactScoreAccuracy * 100)}%</strong><small>不作为主优化指标</small></div>
          <div><span>场均比分绝对误差</span><strong>{reviewDay.review.summary.meanGoalAbsoluteError.toFixed(1)}</strong><small>主客进球误差之和</small></div>
          <div><span>Log Loss</span><strong>{reviewDay.review.summary.logLoss.toFixed(3)}</strong><small>越低越好</small></div>
        </div>
        <div className="postmatch-matches">
          {reviewDay.review.matches.map((match) => <article key={match.matchId} className={match.outcomeCorrect ? 'correct' : 'miss'}>
            <header><b>{match.label}</b><span>{match.outcomeCorrect ? '方向命中' : '方向错误'}</span></header>
            <div><small>预测</small><strong>{match.predictedScore}</strong><i>→</i><small>实际</small><strong>{match.actualScore}</strong></div>
            <p>真实赛果赛前概率 {Math.round(match.actualOutcomeProbability * 100)}% · 比分绝对误差 {match.goalAbsoluteError}</p>
            <em>{match.diagnosis}</em>
          </article>)}
        </div>
        <div className="strategy-review-note">
          <b>策略复盘</b>
          <span>{reviewDay.review.summary.strategyDiagnosis}</span>
          <div>{reviewDay.strategies.map((strategy) => <i key={strategy.key}>{strategy.name} {strategy.profit === null ? '待结算' : `${strategy.profit >= 0 ? '+' : ''}${strategy.profit}元`}</i>)}</div>
        </div>
      </section>}
      <section className="monitor-grid">
        <article className="panel monitor-card"><span>实际路径</span><strong>{actualPaths.toLocaleString()}</strong><p>生成器报告的完成计数，不使用页面声明代替执行。</p></article>
        <article className="panel monitor-card"><span>随机种子</span><strong>{forecast.simulationQuality?.seed ?? forecast.reproducibility?.randomSeed ?? '--'}</strong><p>固定种子配合数据快照可逐路径复现。</p></article>
        <article className="panel monitor-card"><span>参数不确定性</span><strong>{uncertainty}</strong><p>没有后验或 bootstrap 样本时不会人为添加正态误差。</p></article>
        <article className="panel monitor-card"><span>数据快照</span><strong>{snapshotFiles} 个文件</strong><p>{forecast.dataSnapshot?.id.slice(0, 16) ?? '等待新格式数据'}...</p></article>
        <article className="panel monitor-card"><span>模型版本</span><strong>{forecast.modelVersion}</strong><p>管线 {forecast.pipelineVersion ?? '旧格式'} · 基线冻结 {forecast.reproducibility?.baselineFrozen ? '是' : '待确认'}</p></article>
        <article className="panel monitor-card"><span>数据覆盖</span><strong>{Math.round(forecast.overallCoverage * 100)}%</strong><p>覆盖下降会扩大不确定性并阻止正式推荐。</p></article>
        <article className="panel monitor-card"><span>赔率与CLV</span><strong>{oddsSnapshotStats.closing ? `${oddsSnapshotStats.closing} 个临场样本` : '等待临场样本'}</strong><p>已保存 {oddsSnapshotStats.snapshots} 个赔率快照；开盘价与赛前60分钟价格配对后才计算CLV。</p></article>
      </section>
      <section className="panel methodology-block"><h2>上线门槛</h2><p>新增因素必须在滚动时间窗内改善 Log Loss 或 RPS，并通过 bootstrap 方向稳定性检查。没有足够样本的因素只展示，不进入生产模型。</p></section>
    </main>
  )
}
