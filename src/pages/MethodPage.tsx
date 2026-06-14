const steps = [
  ['1', '基础进球强度', '时间衰减的 Dixon-Coles / 双变量泊松模型，以国际比赛历史估计攻防强度。'],
  ['2', '赛前可见调整', '预计首发、球员近 365 天状态、教练风格、体能轮换、旅行、海拔和天气。'],
  ['3', '不确定性传播', '对参数进行 bootstrap，并运行 100,000 次联合模拟生成比分与玩法概率。'],
  ['4', '市场价值判断', '官方固定奖金去除返还率后得到市场概率，再计算原始与稳健期望。'],
  ['5', '资金约束优化', '分数凯利、2 元离散化、同场相关性限制，以及允许完全不下注。'],
]

export function MethodPage() {
  return (
    <main className="content-page">
      <div className="page-title"><div><span>可解释、可回测、可拒绝下注</span><h1>模型方法</h1></div></div>
      <section className="method-flow panel">{steps.map(([number, title, body]) => <div key={number}><b>{number}</b><section><h2>{title}</h2><p>{body}</p></section></div>)}</section>
      <section className="panel methodology-block"><h2>明确不做的事</h2><p>不调用大模型猜比分，不把“运气”设为任意加分项，不隐藏缺失数据，不因为用户有 200 元就要求花完，也不提供代购、登录或支付能力。</p></section>
    </main>
  )
}
