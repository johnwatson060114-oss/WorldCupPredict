# 人工校正数据

免费 API 无法覆盖的预计首发、伤停、教练变化或球员高级数据，可以放在这里。

- `match-overrides.csv`: 对比赛级字段进行校正。
- `player-overrides.csv`: 对球员可用性和近 365 天状态进行校正。
- `availability.csv`: 按比赛日记录伤病、停赛和预计出场概率；未经回测的球员影响只降低置信度，不直接人工加减进球。

每行必须包含 `source_url`、`observed_at` 和 `note`，没有来源的值不会进入模型。
