# Gemini 3.7 与 DeepSeek：100 句完整流程对照

在这批 100 条真实学习材料中，`gemini-3.7-flash-high` 的综合表现优于现用的 `deepseek-v4-flash-0731`，优势主要在词卡解释的范围、词性和中文表达。逐句核对后，Gemini 有 8 条建议调整，DeepSeek 有 30 条；综合偏好为 Gemini 30 条、DeepSeek 5 条、持平 65 条。

这些数量是本助手按学习用途作出的审阅判断，包含词卡和措辞优化，**不能读成 8% 或 30% 的整句错译率**。据此更推荐将 3.7-high 作为后续模型选择；本轮按用户要求先完成了 [DeepSeek 中英文释义上线](deepseek-bilingual-release-20260915.md)，线上模型仍为 DeepSeek，接口保持兼容。

| 项目 | DeepSeek v4 Flash 0731 | Gemini 3.7 Flash High |
| --- | ---: | ---: |
| 完整流程最终成功 | 100 / 100 | 100 / 100 |
| 含英文解释的词卡 | 339 / 339 | 339 / 339 |
| 建议调整的句子或词卡所在条目 | 30 / 100 | 8 / 100 |
| 综合比较中更偏好的条目 | 5 | 30 |
| 与对方持平 | 65 | 65 |
| 单条流程平均耗时 | 33.39 秒 | 27.42 秒 |
| 单条流程中位耗时 | 27.91 秒 | 26.25 秒 |
| P95 耗时 | 62.82 秒 | 34.90 秒 |
| 最长耗时 | 86.83 秒 | 54.51 秒 |

两款均完成所有条目，没有最终调用失败或本地质量校验失败。DeepSeek 在 ID 325、545、685 上各有一项分块偏粗的提示，完整译文仍可用；Gemini 没有分块提示。流程保留了内部审校、词卡修复和传输重试，因此这里的成功不代表每次上游首次响应都完美。

耗时包含生成、审校、词卡、分块、修复及限速等待。DeepSeek 通过已上线的真实本地 API 测试，使用线上进程的共享限速器；Gemini 通过现有只读评测脚本调用相同翻译流程。两边网关不同，线上排队也可能影响 DeepSeek 的耗时，因此这些数值反映本次实际运行，不是隔离网络与负载后的模型推理速度。

以下数据库 ID 可直接对应原始输出，不能与复习轮次中的第几句混用。

| 样本 | DeepSeek 输出或问题 | Gemini 输出或表现 |
| --- | --- | --- |
| ID 11：税收政策 | `policies` 词卡解释为“废除贡赋和税收的措施”，但原文指仍在产生收入的贡赋、税收政策 | 保留“政策”，没有将其指向废税措施 |
| ID 168：移民英语能力 | “来自十五个最常见来源国的大多数移民”，漏掉 `each` 的逐国范围 | “来自15个最主要的移民来源国中每一个国家的大多数移民”，保留逐国数量范围 |
| ID 481：法律责任 | “因偏袒指控而免于定罪”，将指控写成了获得豁免的原因 | “免于因偏袒指控而被定罪”，关系更准确 |
| ID 426：dormant、Islands | `dormant` 英释以 `a volcano` 开头，形容词变成名词；`Islands` 用 `a group of islands` 循环解释，并吸收 Hawaiian 的专名范围 | 分别解释为“不活跃但仍可能喷发”和“四面环水的陆地”，范围更清楚 |
| ID 129：brainstorm | 英释 `a method of generating ideas by free-thinking`，没有保持本句动词用法 | `to produce ideas or ways of solving a problem`，词性合适 |
| ID 596：Feasibility | `the quality of being possible or practical to do`，简明清楚 | `the state of being easily or conveniently done`，容易让学习者将可行性理解成容易或方便，建议改进 |

以 ID 168 为例，原文关键片段是：

> a majority of immigrants from each of the fifteen most common countries of origin

“每个国家各自都有大多数”与“这些国家合起来的大多数”不相同。这是比单纯润色更有分量的差异。ID 11、481 也分别涉及词卡指代和法律关系；这些问题即使通过结构与引文校验，也仍会留在结果中。

Gemini 同样有改进空间。例如 `bilingual` 英释添加“两种语言同样熟练”，`corporate` 限定为大公司，`sneak` 增加未经许可的条件，ID 687 将 `the majority` 加强为“绝大多数”。此外，两款都没有在董事会配额语境中充分说明 `gender parity` 的人数或代表比例含义。不能把本次优势理解为词卡已经全部达到无需审阅的程度。

Feasibility 在匿名初核中被标得较重。二次复核采用保守口径：`easily/conveniently done` 接近一种简化词义表达，但在学习场景中不如 `possible or practical` 清楚，因此只计为释义范围的改进项，不计明确核心改义。该调整没有改变“8 条需调整”或综合偏好数量；原始匿名记录保留，调整另存文件。

本次从 710 条未删除材料中，排除上一轮已测的 10 条真实材料，再从剩余 700 条中以种子 `20260915` 随机抽取 100 条。没有按模型输出好坏挑选样本。样本包含库中已有的完整句、残句和题目选项，长度为 4—47 个英文词，中位数 16.5；每款模型各测试 339 个重点词。

两款使用相同原文、重点词和前后各最多三条上下文，不将旧译文输入模型或视为标准答案。双方均为两个条目并发、上游每分钟最多 18 次请求、传输层最多重试两次，单次上游超时配置为 180 秒；整条评测不额外重跑失败项。模型之外的参数沿用线上配置，代码及提示指纹相同：

```text
pipeline_sha256: a5e02d59fba9d90598fc92811cc227609e24a49bf5b3f5593f16b26482bb1287
prompt_sha256:   9ee9c56c72241523e17f54b5a0d94487da734edd347deda7a41c24d0b88c5471
```

运行期间没有修改翻译代码。完成后确认原文与重点词快照未变，并逐条核实真实 API 使用的上下文与评测快照一致。Gemini 测试没有改变生产配置，两个模型生成的候选均未写入学习句子；临时测试会话已清理。

内容核对覆盖全部 100 对译文及 678 张词卡。每个条目独立随机分配 A/B 标签，审阅时隐藏模型名，记录完成后才展开型号映射；执行进度中的型号是可见的。这是本助手进行的来源核对，没有独立人工评审，也没有让参测模型给自己打分。纯润色和边界意见尽量单列，综合偏好也包含自然度判断。

测试针对当前应用流程，而非模型裸能力：流程已有上下文、已知语义规则、审校及本地修复。样本来自同一学习库，部分条目属于同一篇材料，不能据此推算所有题材上的准确率。每款只生成一遍最终结果，没有评估长期波动、价格或其他能力。Gemini 型号是用户网关的请求名称，未独立验证其内部路由或官方模型身份。

实测从北京时间 2026-09-15 07:59 开始，Gemini 于 08:22 完成，DeepSeek 于 08:27 完成。JSON 记录使用 UTC。原始资料保存在本地 `backend/data/audits/gemini-37-100-evaluation-20260915/`：

- [样本、随机种子与重点词](../backend/data/audits/gemini-37-100-evaluation-20260915/dataset.json)
- [运行参数](../backend/data/audits/gemini-37-100-evaluation-20260915/manifest.json)、[运行汇总](../backend/data/audits/gemini-37-100-evaluation-20260915/run-summary.json)
- [Gemini 全部结果](../backend/data/audits/gemini-37-100-evaluation-20260915/gemini-3.7-flash-high.jsonl)、[DeepSeek 全部结果](../backend/data/audits/gemini-37-100-evaluation-20260915/deepseek.jsonl)
- [评审口径](../backend/data/audits/gemini-37-100-evaluation-20260915/review-method.json)、[原始匿名逐句核对](../backend/data/audits/gemini-37-100-evaluation-20260915/content-review.jsonl)、[型号映射](../backend/data/audits/gemini-37-100-evaluation-20260915/blind-mapping.json)
- [边界词义复核说明](../backend/data/audits/gemini-37-100-evaluation-20260915/review-adjudication.json)、[复核后的逐句结果](../backend/data/audits/gemini-37-100-evaluation-20260915/content-review-adjudicated.json)、[最终比较汇总](../backend/data/audits/gemini-37-100-evaluation-20260915/comparison-summary.json)
- [输入、上下文与版本验证](../backend/data/audits/gemini-37-100-evaluation-20260915/verification.json)
