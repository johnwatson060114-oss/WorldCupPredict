# 人工校正数据

免费 API 无法覆盖的预计首发、伤停、教练变化或球员高级数据，可以放在这里。

- `match-overrides.csv`: 对比赛级字段进行校正。
- `player-overrides.csv`: 对球员可用性和近 365 天状态进行校正。
- `availability.csv`: 按比赛日记录伤病、停赛和预计出场概率；未经回测的球员影响只降低置信度，不直接人工加减进球。
- `intelligence/<日期>/*.json`: 由 `pipeline.intelligence.save_intelligence_snapshot` 生成的不可变情报快照。

每行必须包含 `source_url`、`observed_at` 和 `note`，没有来源的值不会进入模型。

情报快照必须包含事件对象、原始来源、发布时间、确认等级、置信度、冲突和结构化结论。任何 `xg_adjustment` 或 `probability_delta` 字段都会被拒绝；官方确认停赛只会转成确定缺阵事实，影响量仍由本地阵容价值模型计算。
