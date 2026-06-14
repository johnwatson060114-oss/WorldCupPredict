# 世界杯比赛推演

面向桌面大屏的世界杯概率预测、体彩价值比较与 200 元滚动本金模拟工具。

它不会调用 OpenAI，不会代购、登录或付款。开发快照与降级数据会在页面顶部明确警告，不能当作实际投注建议。

## 功能

- 每天北京时间 18:00 生成次日 00:00–23:59 开球比赛。
- Dixon-Coles 比分分布、胜平负、让球胜平负和比分概率。
- 体彩固定奖金去水、原始期望和概率下界的稳健期望。
- 稳健、均衡、激进三种分数凯利方案，金额按 2 元取整。
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

安装 Windows 18:00 任务：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-scheduled-task.ps1
```

GitHub Actions 的 cron 使用 `10:00 UTC`，即北京时间 18:00。GitHub 调度可能延迟，本机任务用于需要严格准点的情况。

## 数据原则

- API-Football 每日最多使用 95 次请求，预留 5 次失败重试。
- 体彩页面结构无法识别时停止推荐，不猜字段。
- 缺失球员数据回归位置基线，并显示覆盖率和缺失清单。
- 新因素只有在时间顺序回测改善 Log Loss/RPS 且 bootstrap 方向稳定时才启用。
- 没有正稳健期望时默认不买，娱乐方案必须由用户主动选择。

## 测试

```powershell
python -m pytest -q
npm.cmd run build
```

固定 HTML 快照覆盖未开售、让球正负号、单关标识、比分“其它”和页面结构变化。

## 免责声明

本项目只做概率和风险分析。彩票有风险，不保证盈利；任何购买均由用户通过合法官方渠道自行完成。
