# 世界杯比赛推演

面向桌面大屏的世界杯概率预测、体彩价值比较与 200 元滚动本金模拟工具。

它不会调用 OpenAI，不会代购、登录或付款。开发快照与降级数据会在页面顶部明确警告，不能当作实际投注建议。

## 功能

- 每天北京时间 13:00 结算赛果、更新回测统计并生成次日 00:00–23:59 开球比赛。
- 冻结的旧模型基线、内容寻址数据快照和固定随机种子。
- Dixon-Coles、双变量泊松、负二项和层级模型的嵌套滚动回测框架。
- 可配置的 FIFA 2026 黄牌、红牌、清零、停赛和公平竞赛分规则引擎。
- 实际执行的 100,000 条共享比分路径、Monte Carlo 误差区间与收敛检查。
- 体彩固定奖金去水、原始期望和概率下界的稳健期望。
- 同路径逐腿结算的单关、串关、比分、总进球和半全场资金模拟。
- 停赛首发与同位置替补价值差、候选因素消融准入和结构化赛前情报审计。
- 本地本金流水、JSON 导入导出、预测历史和回测页面。
- 免费 API 请求预算、本地缓存、固定快照降级和结构变化熔断。

## 本地启动

```powershell
Copy-Item .env.example .env.local
# 在 .env.local 填写 API_FOOTBALL_KEY
python -m pip install -r requirements.txt
npm.cmd install
python -m pipeline.generate --archive
npm.cmd run dev
```

无密钥查看确定性的开发样例：

```powershell
.\scripts\run-offline-demo.ps1
```

## 每日任务

手工生成：

```powershell
.\scripts\run-daily.ps1
```

安装 Windows 13:00 任务：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-scheduled-task.ps1
```

GitHub Actions 的 cron 使用 `05:00 UTC`，即北京时间 13:00；定时更新从北京时间 2026-06-17 开始。本机计划任务同样从 `2026-06-17 13:00` 起步。

每日任务会同步刷新总进球数模型复盘，并生成 `public/data/total-goals-model-review.json`：旧模型作为主线，新模型作为影子线，`adoptionDecision.should_switch_model` 会直接给出是否需要切换模型。

## 数据原则

- API-Football 每日最多使用 95 次请求，预留 5 次失败重试。
- 体彩页面结构无法识别时停止推荐，不猜字段。
- 缺失球员数据回归位置基线，并显示覆盖率和缺失清单。
- 新因素只有在时间顺序回测改善 Log Loss/RPS 且 bootstrap 方向稳定时才启用。
- 未通过准入的天气、裁判、战术和黄牌行为因素只展示或扩大区间，不修改均值。
- 大模型输出只能进入严格的情报 JSON 契约，不能直接提供 xG 或概率修正。
- 每日任务会更新真实赛果、策略盈亏和回测样本；模型参数只有达到样本门槛后才调整，避免根据单场结果过拟合。
- 没有正稳健期望时默认不买，娱乐方案必须由用户主动选择。

## 测试

```powershell
python -m pytest -q
npm.cmd test
npm.cmd run build
```

在受限 Windows 环境中，pytest 临时目录可显式放在仓库内：

```powershell
python -m pytest -q -p no:cacheprovider --basetemp .\tmp\pytest
```

## 模型升级模块

- `pipeline/historical_store.py`: 按发布时间追加版本的历史比赛、球员、阵容和事件库。
- `pipeline/discipline.py`: FIFA 2026 纪律状态机。
- `pipeline/goal_models.py` / `pipeline/backtest.py`: 候选进球模型与嵌套滚动回测。
- `pipeline/simulation.py`: 100,000 条连续赛事与共享比分路径。
- `pipeline/portfolio.py`: 按共享路径逐腿结算资金结果。
- `pipeline/lineup.py`: 确定停赛与替补价值差。
- `pipeline/factor_gate.py`: 单因素消融和 bootstrap 准入。
- `pipeline/intelligence.py`: 不可变、可审计的赛前情报快照。

生产模型仍保留 `legacy-dixon-coles-v1` 基线。只有真实历史数据达到滚动回测样本门槛且样本外 Log Loss、RPS 与校准共同通过时，候选模型才可晋级。

总进球数模型采用双线并行：旧模型继续作为生产主线，候选新模型只做影子验证；当 2026 已结算样本不少于 24 场，且候选模型同时满足精确档命中率提升、额外命中数、Log Loss 改善和核心区间不显著退化时，才允许切换。当前跟踪脚本和门槛记录在 `artifacts/total-goals-backtest/model_adoption_policy.md`。

固定 HTML 快照覆盖未开售、让球正负号、单关标识、比分“其它”和页面结构变化。

## 免责声明

本项目只做概率和风险分析。彩票有风险，不保证盈利；任何购买均由用户通过合法官方渠道自行完成。
