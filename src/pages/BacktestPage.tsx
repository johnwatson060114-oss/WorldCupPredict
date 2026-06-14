import { CheckCircle2, CircleAlert, MinusCircle } from 'lucide-react'
import type { BacktestMetric } from '../types'

const icons = { good: CheckCircle2, neutral: MinusCircle, warning: CircleAlert }

export function BacktestPage({ metrics }: { metrics: BacktestMetric[] }) {
  return (
    <main className="content-page">
      <div className="page-title"><div><span>严格按时间顺序评估</span><h1>回测与校准</h1></div><p>赛后数据绝不进入赛前特征。</p></div>
      <div className="metric-grid">
        {metrics.map((metric) => { const Icon = icons[metric.status]; return <section className={`metric-card panel ${metric.status}`} key={metric.label}><Icon size={20}/><span>{metric.label}</span><strong>{metric.value}</strong><p>{metric.note}</p></section> })}
      </div>
      <section className="panel methodology-block"><h2>上线门槛</h2><p>新增因素必须在滚动时间窗内改善 Log Loss 或 RPS，并通过 bootstrap 方向稳定性检查。没有足够样本的因素只展示，不进入生产模型。</p></section>
    </main>
  )
}
