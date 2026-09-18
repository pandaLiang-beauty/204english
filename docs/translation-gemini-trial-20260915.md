# Gemini 翻译实测：2026-09-15

`gemini-3.8-flash-high` 在用户提供的网关上可调用，能够生成整句译文和英文词义解释。本次小样本中，部分中文表达比当前模型自然，但不足以证明整体优于 `deepseek-v4-flash-0731`。相同的新规则也改善了当前模型的输出。

本次只做评测，现有模型配置保持原值，评测结果没有写回学习数据库。英文解释功能已在代码中接入原有释义字符串，接口路径、字段及类型保持不变。

后续已扩展测试用户列出的九款 Gemini，并增加随机真实材料和完整流程核对。最新选型建议见[九款 Gemini 与 DeepSeek 对比](translation-model-comparison-20260915.md)；本文保留首次两模型测试的原始结果。

## 测试条件

| 项目 | 新模型 | 当前模型 |
| --- | --- | --- |
| 请求地址 | `https://api.ncnb.me/v1/chat/completions` | `https://tokenrhythm.studio/v1/chat/completions` |
| 请求模型 | `gemini-3.8-flash-high` | `deepseek-v4-flash-0731` |
| 第一组响应中的模型标识 | `gemini-3.8-flash` | `deepseek-v4-flash-0731` |
| 温度 | 0.2 | 0.2 |
| 第一组：8 句一次请求 | 9.942 秒 | 7.646 秒 |
| 第一组完整返回 | 8 句、24 张含英文解释的词卡 | 8 句、24 张含英文解释的词卡 |
| 第二组：现有流程 | 第 106、107 句均成功 | 第 106、107 句均成功 |

第一组使用相同的简短通用提示词，包含用户提供的两句和另外六句构造例句，不提供逐句答案或邻句。耗时是一批八句的单次观察，不是每句耗时或稳定的性能基准。

第二组使用项目当前的上下文、初译、终审、词卡校验和分块流程，保留实际数据库中的重点词与邻句。两种模型使用相同代码指纹；每分钟最多 12 次请求、同时处理两句，因此耗时包含排队和多阶段处理。

第 107 句的纠正规则已加入第二组提示词。这一组用于检查应用最终效果，不能单独用来证明模型自身的翻译能力提升。第一组没有提供这条纠正规则。

网关返回的模型标识省略了请求名中的 `-high`，并报告了推理 token。以下结论针对该网关按指定请求名实际返回的内容，不据此确认其内部路由。

## 第 107 句

原文：

> Good governance rests on an understanding of the inherent worth of each individual.

原有译文：

> 善治依赖于对每个人内在固有价值的理解。

“善治”是成立的专业术语，原译基本意思正确。可改善之处是名词结构偏生硬、“内在固有”重复，以及词卡把 `each` 的“每个”归入了 `individual`。

第一组新模型原样输出：

> 良好的治理建立在对每个人固有价值的理解之上。

第一组当前模型原样输出：

> 良好的治理依赖于对每个个体固有价值的理解。

新模型在这里更清楚地表达了 `rests on` 的基础关系；两者都保留了主要含义。

通过完整流程后，新模型原样输出：

> 良好的治理建立在认识到每个人都具有内在价值的基础之上。

对应词卡：

| 重点词 | 中文句中义 | 英文解释 |
| --- | --- | --- |
| rests | 用于 rest on，表示以……为基础 | used with 'on' to mean to be based on or depend on something |
| inherent | 内在的 | existing as a natural and permanent quality or characteristic |
| individual | 个人（each 表示“每个”） | a single human being considered separately from others |

当前模型在同一流程下输出“良好的治理建立在认识到每个人都具有内在价值这一基础上”，也已改善。它对 `individual` 的英文解释是 `a single person`，更简短。因此英语解释的简明程度并非新模型全面占优。

## 其他样本的核对

| 样本 | 观察 |
| --- | --- |
| 第 106 句，For another… | 通用提示下两者都写“另一方面”，不符合本材料中另一个人的指代；完整流程后两者都恢复“对另一个人而言”。上下文和规则仍然必要。 |
| The medicine may reduce pain, but it does not necessarily address the underlying cause. | 两者都保留“可能减轻疼痛，但未必解决根本原因”的范围。 |
| The policy was intended to protect small businesses, not to prevent larger firms from entering the market. | 两者都保留目的对比；都把 larger firms 简化成“大企业/大公司”，“规模较大的企业”能更明确保留比较。 |
| What matters is not how many facts students can recall, but whether they can use them to solve unfamiliar problems. | 两者均保留“不是记住多少，而是能否运用”的对比。 |
| Only after the results had been independently verified did the team announce its discovery. | 两者整句都译出“验证之后才宣布”。新模型词卡增加“客观中立地”，当前模型增加“由外部单方”，均超出 independently 在原文能直接证明的内容。 |
| Each participant was asked to rate how approachable the manager seemed, rather than how competent she was. | 新模型写“看起来有多平易近人”，当前模型写“看起来有多大亲和力”；新模型表达更顺。两者保留亲和力与能力的区别。 |
| The service is inexpensive, but that does not make it affordable for everyone. | 两者整句均正确保留“不贵不代表人人负担得起”。当前模型的 affordable 英文释义额外引入 most people，新模型没有增加这个数量限定。 |

新模型完整流程中也有可润色之处，例如 `perceived` 的中文句中义写成“视为”，标明“被视为”更有助于学习被动结构。本地格式和引文校验通过，不等于所有词义措辞都已达到人工审定标准。

## 接口兼容与验证

英文解释沿用 `word_translations[word]` 和 `items[].translation` 的字符串值，例如：

```json
{
  "word_translations": {
    "approachable": "本义：平易近人的；句中：平易近人；英文：friendly and easy to talk to"
  }
}
```

这只是字段内容增加，客户端仍按原有 `Map<String, String>` 读取。网页编辑页通过既有翻译接口补充缺失英文解释，保留已有中文释义，保存后生效。历史中文词义继续兼容。

已通过前端 25 项测试、构建、Python 编译、模块边界检查、后端可靠性检查和差异空白检查。绕过 shell 代理直连本机健康接口返回 `200 {"status":"ok"}`。回归覆盖英文释义缺失时的定向重试、中文词义修正后英文的保留、历史数据读写及请求/响应结构不变。OpenAPI 修改仅涉及说明和示例。

## 原始记录

实测发生于北京时间 2026-09-15，JSONL 内时间使用 UTC。原始记录保留提示词、全部八句输出、模型标识及两句完整流程结果，不含凭据：

- [新模型通用提示测试](../backend/data/audits/gemini-translation-trial-20260915/raw-candidate.json)
- [当前模型通用提示测试](../backend/data/audits/gemini-translation-trial-20260915/raw-baseline.json)
- [新模型完整流程](../backend/data/audits/gemini-translation-trial-20260915/pipeline-candidate.jsonl)
- [当前模型完整流程](../backend/data/audits/gemini-translation-trial-20260915/pipeline-baseline.jsonl)

这些样本是针对问题选择的两句真实材料和六句构造例句，没有进行随机全库评测，也没有重复采样，结论限于本次观察。
