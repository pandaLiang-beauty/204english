# 翻译模型对比：九款 Gemini 与当前 DeepSeek

后续已完成 [Gemini 3.7 与 DeepSeek 的 100 句完整流程对照](translation-gemini-37-100-20260915.md)，该轮对 3.7-high 的质量优势提供了更多依据。本文保留此前九款模型的小样本观察。

本次实测不足以证明 Gemini 整体优于现用的 `deepseek-v4-flash-0731`。建议先保留 DeepSeek；如果要选一款 Gemini 继续对照，优先考虑 `gemini-3.7-flash-high`。它在首轮较少出现需要修改的地方，进入现有完整流程后中文也较自然，但英文词义范围仍需校验。`gemini-3.8-flash-high` 在部分语境解释上较好，没有稳定胜出。

九款 Gemini 均已实际调用，测试覆盖整句翻译、中文本义、中文句中义和简单英文解释。本轮评测没有切换线上模型、修改接口路径/字段/类型，或把候选译文写入学习数据库。此前接入的英文解释仍追加在原有释义字符串中，客户端可继续按原类型读取。

实测发生于北京时间 2026-09-15；原始记录使用 UTC。Gemini 使用用户指定的 `https://api.ncnb.me/v1`，DeepSeek 使用项目当前的 `https://tokenrhythm.studio/v1`。结论针对这两个网关当时返回的内容。

首轮给所有十款模型相同的 12 句、34 个重点词：用户第 106、107 句（库内 ID 359、477），随机真实材料 669、157、280、156，以及六句检验否定、比较和词义范围的构造例句。随机种子为 `20260915`，真实材料候选池为 325 句。每次请求六句，每款两次请求；温度 0.2、最多三个并发、每个网关每分钟最多 12 次请求、超时 120 秒，无请求重试。模型收到邻近英文，不收到旧译文、核对标准或参考答案。

下表“需修改”是逐句核对整句与词卡后，至少发现一处问题的句子数，包含搭配生硬、词义范围和解释不充分，**不是错译率**。“明确改义”是其中明确改变原文含义的句子数。首轮先按匿名标签核对，再查看型号对应关系；审核由本助手对照原文完成，不是独立人工评审或参测模型自评分。

| 请求模型 | 需修改 / 12 | 其中明确改义 | 六句一批中位耗时 | 首轮观察 |
| --- | ---: | ---: | ---: | --- |
| gemini-3.6-flash-high | 3 | 0 | 5.01 秒 | 基本准确；有生硬搭配和把试验具体化为临床试验的情况 |
| gemini-3.5-flash-lite | 2 | 0 | 4.30 秒 | 首轮较好且响应快；后续领域样本暴露问题 |
| gemini-pro-agent | 4 | 0 | 26.85 秒 | 较慢；代词范围和中文搭配仍需修改 |
| gemini-3-flash | 5 | 0 | 5.20 秒 | 词义范围、额外细节等问题较多 |
| gemini-3.1-flash-lite | 3 | 0 | 5.26 秒 | 与基线接近，未显示明确提升 |
| gemini-3.7-flash-high | 2 | 0 | 6.77 秒 | 首轮较好；部分英文解释过短 |
| gemini-3.1-pro-low | 4 | 0 | 27.22 秒 | 较慢，未显示对应质量收益 |
| gemini-3.8-flash-high | 4 | 1 | 5.43 秒 | 曾把“未成瘾”改成“不吸毒”；复测没有重现这一错误 |
| gemini-3.1-flash-image | 4 | 0 | 7.36 秒 | 可以完成文本任务，未显示翻译优势 |
| deepseek-v4-flash-0731 | 3 | 0 | 4.90 秒 | 核心逻辑较好；个别词卡和中文表达仍需修改 |

首轮 20 次请求均完整返回所需 JSON。耗时是两个六句批次的中位数，包含网关响应时间，不包含请求开始前的本地限速等待，不能视作线上单句响应时间。两批样本也不足以估计长期延迟或可靠性。

第二轮选择首轮较好的 3.5-lite、3.7-high，以及用户最先关注的 3.8-high 和 DeepSeek。每款再测六句：重复 359、156，另随机抽取真实材料 88、560、286、210；新样本种子为 `20260916`，候选池 281 句。每款共 16 个重点词，沿用相同提示和参数。型号已经揭晓，因此这轮为非盲核对。

| 模型 | 需修改 / 6 | 其中明确改义 | 六句耗时 | JSON 结果 |
| --- | ---: | ---: | ---: | --- |
| gemini-3.5-flash-lite | 5 | 1 | 5.21 秒 | 完整 |
| gemini-3.7-flash-high | 4 | 0 | 5.74 秒 | 完整 |
| gemini-3.8-flash-high | 3 | 0 | 4.93 秒 | 完整 |
| deepseek-v4-flash-0731 | 4 | 0 | 6.97 秒 | 多余逗号导致解析失败；文本内容完整 |

DeepSeek 原始失败记录保持原样。为了核对已经生成的内容，只删除那一处尾随逗号，另存审阅副本；上表内容评价来自该副本，格式仍记失败。这是三次通用提示请求中的一次格式失败，不能据此推算稳定的故障率。

几处具体输出比单看待改数量更有参考价值：

- 第 107 句 `Good governance rests on an understanding of the inherent worth of each individual.`，十款模型都保留了基本意思。3.7-high 写“良好的治理建立在对每个人固有价值的理解之上”，DeepSeek 写“良好的治理依赖于对每个人内在价值的理解”。原来的“善治”并非错误，主要需要改善表达与词卡范围，不能凭这一句证明换模型更好。
- 3.8-high 首轮把 `while not addicted or mentally ill` 写成“虽然既不吸毒也没有精神疾病”。没有成瘾不等于没有吸毒行为；复测和完整流程均恢复成瘾含义，说明单次表现会波动。
- 在学术出版语境中，3.5-lite 把 `the legal ecosystem has lost legitimacy among its users` 写成“法律生态系统已经失去了使用者的合法性”，错挂所属关系；英文释义只有 `conformity to the law or to rules`。此处侧重合法出版体系失去用户认可或正当性。3.8-high 的英文解释 `the quality of being accepted, proper, or justified` 更贴合语境。
- 首轮十款、第二轮四款都将第 106 句的 `For another` 写成“另一方面”，没有保留材料中“对另一个人而言”的指代。之前两款模型在完整流程下可以恢复正确指代，详见[前次两模型实测](translation-gemini-trial-20260915.md)。
- 3.7-high 和 3.8-high 在两轮通用提示中都只用 `although` 解释 `while`。它是同义词，但不满足当前应用要求的英文解释短语。3.7-high 复测还用物理方向解释 `turn their lives around` 中的 `around`；DeepSeek、3.5-lite 则出现未交代短语整体范围的解释。

随后将 ID 156（成瘾、让步、改善生活）和 560（出版体系、正当性）放入项目实际的初译、审校、词卡与分块流程，每款模型测试两句。四款使用相同代码和提示词指纹，没有按型号调整规则，也没有输入旧译文。现有流程自带上下文与词义约束，因此这一轮评估的是应用最终效果。

| 模型 | 调用及本地校验 | ID 156 耗时 | ID 560 耗时 | 最终内容核对 |
| --- | --- | ---: | ---: | --- |
| gemini-3.5-flash-lite | 2 / 2 通过 | 42.07 秒 | 22.39 秒 | `while`、`around` 英释改善；出版语境仍偏向法律合规义 |
| gemini-3.7-flash-high | 2 / 2 通过 | 28.41 秒 | 39.16 秒 | 中文较自然，出版体系与正当性清楚；`around` 中文宜注明短语范围 |
| gemini-3.8-flash-high | 2 / 2 通过 | 39.97 秒 | 44.21 秒 | 成瘾和英文解释已改善；“合法体系”仍较泛，中文搭配可润色 |
| deepseek-v4-flash-0731 | 2 / 2 通过 | 40.97 秒 | 25.93 秒 | 出版语境及英文解释准确；“却仅仅缺乏改变生活”等措辞可润色 |

完整流程以两个句子并发、每分钟最多 12 次上游请求运行，无外层重试和传输重试。上表每句耗时包含多阶段生成、内部词卡修复和限速等待，与首轮六句批量直调不能直接比较。八个结果均没有本地质量问题或分块告警；这些校验主要检查结构、释义形式和引文，不能保证语义完全正确。

ID 560 的最终结果体现了差别：

| 模型 | 最终整句译文 | legitimacy 英文解释 |
| --- | --- | --- |
| 3.5-lite | 表明该法律生态系统在其用户中已失去合法性，必须进行变革，以便为所有参与者服务。 | conformity to the law or to rules; being acceptable and valid |
| 3.7-high | 表明这一合法出版体系已在用户中失去正当性，必须进行变革，以兼顾所有参与者的利益。 | the quality of being accepted, reasonable, or justified |
| 3.8-high | 表明合法体系已在用户中失去了正当性，必须进行变革，以便对所有参与者都切实可行。 | the quality of being reasonable, acceptable, or recognized as right |
| DeepSeek | 这表明，合法出版体系在其使用者中已失去公信力，必须加以改革，使其对所有参与者都有效。 | the state of being accepted and considered valid or rightful by people |

综合这些结果，保留 DeepSeek 是目前较稳妥的选择。3.7-high 值得作为后续候选，但仍不能省去语境审校与词卡校验；3.8-high 没有稳定胜过它或 DeepSeek。3.5-lite 的首轮速度和少量待改数不足以抵消后续领域错误。其余款仅做了首轮筛查，证据不足以认定强弱，其中两款 Pro 的额外耗时未带来可见收益，image 型号在本次纯文本任务中也没有优势。

请求名与响应中的模型标识存在以下差异，其余本轮返回的标识与请求名一致：

| 请求名 | 响应中的标识 |
| --- | --- |
| gemini-3.6-flash-high | gemini-3.6-flash |
| gemini-3.7-flash-high | gemini-3.7-flash-exp-b |
| gemini-3.8-flash-high | gemini-3.8-flash |
| gemini-pro-agent | gemini-pro-default |

这些标识来自网关响应，不能验证底层真实模型身份或官方版本。样本量小、部分样本重复、候选复测存在筛选，评分也包含审阅判断，因此不合并成总榜或统计显著的胜率。不同网关的耗时还受路由和负载影响。本次没有测价格、长期可用性、图像或 agent 能力，不能给出性价比结论。

可复用脚本为 [compare_translation_models.py](../backend/scripts/english/compare_translation_models.py)。候选凭据通过仓库外的私有 JSON 文件传入，包含 `base_url`、`api_key`；基线从现有环境读取。脚本只读学习数据，保存提示词、原始回答、格式问题、耗时、模型标识和用量，并过滤密钥。本次临时凭据文件已删除。

使用已保存的数据集复测示例（凭据文件应设为仅本人可读，输出目录必须是新目录）：

```bash
(
  set -a
  source .env.local
  source .env.secrets.local
  set +a
  backend/.venv/bin/python backend/scripts/english/compare_translation_models.py \
    --candidate-config /path/to/private-candidate.json \
    --dataset backend/data/audits/gemini-model-comparison-20260915/round-1/dataset.json \
    --output backend/data/audits/model-comparison-rerun
)
```

原始审计文件保留在本地 `backend/data/audits/gemini-model-comparison-20260915/`：

- [首轮样本](../backend/data/audits/gemini-model-comparison-20260915/round-1/dataset.json)、[请求清单与型号映射](../backend/data/audits/gemini-model-comparison-20260915/round-1/manifest.json)、[匿名核对记录](../backend/data/audits/gemini-model-comparison-20260915/round-1/blind-review.json)、[首轮汇总](../backend/data/audits/gemini-model-comparison-20260915/round-1/summary.json)。同目录 `Mxx-batch-n.json` 为完整原始输出。
- [第二轮核对记录](../backend/data/audits/gemini-model-comparison-20260915/round-2/review.json)、[DeepSeek 原始格式失败](../backend/data/audits/gemini-model-comparison-20260915/round-2/M05-batch-1.json)、[仅供审阅的修复副本](../backend/data/audits/gemini-model-comparison-20260915/round-2/M05-review-recovered.json)。
- [完整流程核对记录](../backend/data/audits/gemini-model-comparison-20260915/pipeline/review.json)。同目录各型号 `.jsonl` 保留最终译文、词卡、模型内部审校记录与校验状态，`.log` 保留执行结果。

仓库检查已通过 Python 编译、模块边界检查、前端 25 项测试、前端构建、后端可靠性检查、差异空白检查。本机健康接口绕过 shell 代理直连返回 `200 {"status":"ok"}`。服务未因本轮评测重启，生产模型配置保持原值。
