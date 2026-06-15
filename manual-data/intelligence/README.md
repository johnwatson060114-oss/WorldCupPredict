# 赛前情报快照

不要手工覆盖已有快照。使用 `pipeline.intelligence.save_intelligence_snapshot` 按目标日期写入带 SHA-256 的不可变 JSON。

情报层只保存证据，不直接修改概率。预测截止时间之后发布的内容、缺少 HTTPS 来源的内容和包含自由 xG/概率调整的内容都会被拒绝。
