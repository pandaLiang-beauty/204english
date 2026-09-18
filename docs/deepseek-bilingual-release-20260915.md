# DeepSeek 重点词中英文释义上线

北京时间 2026-09-15 已上线，继续使用 `deepseek-v4-flash-0731`。新生成的重点词包含中文本义、中文句中义和简单英文解释。

线上真实接口返回示例：

```text
approachable = 本义：可接近的，友好的；句中：平易近人的，容易接近的；英文：friendly and easy to talk to
individual = 本义：个人；个体；句中：个人（each 表示“每个”）；英文：a single person
```

整句翻译接口对第 107 句返回：

> 良好的治理建立在认识到每个人都具有内在价值这一基础之上。

英文解释沿用 `word_translations[word]` 和 `items[].translation` 字符串。上线前后 OpenAPI 的接口路径、字段、类型和约束一致；变化仅涉及文档说明和示例，现有 Android 客户端无需改接口。

首次上线只更新了生成流程，没有回填已有词卡。随后已[补齐现有 710 句、2333 个重点词的英文解释](english-definitions-backfill-20260915.md)，刷新页面即可查看。后续单条中文词卡仍可通过“编辑 → 生成翻译 → 保存”补充英文；原有中文释义和整句译文会保留。新增词卡及重新生成的词卡会自动带英文解释。

已重启英语后端加载新代码，前端继续提供已构建的新版本。公开地址 `https://204.xpliang.tech/` 返回 200，首页内容与本地构建一致。两个真实接口 `/api/english/translate/words`、`/api/english/translate` 均返回完整中英文释义，测试会话已清理，测试草稿没有写入学习句子。

上线前已完成 Python 编译、模块边界检查、前端 25 项测试、前端构建、后端可靠性检查和差异检查。原始记录位于本地 `backend/data/audits/deepseek-bilingual-deployment-20260915/`：

- [部署与健康状态](../backend/data/audits/deepseek-bilingual-deployment-20260915/deployment.json)
- [词卡接口实测](../backend/data/audits/deepseek-bilingual-deployment-20260915/live-api-359.json)
- [整句接口实测](../backend/data/audits/deepseek-bilingual-deployment-20260915/live-api-477.json)
- [公开入口验证](../backend/data/audits/deepseek-bilingual-deployment-20260915/public-entry.json)

`gemini-3.7-flash-high` 的 [100 句对照评测已完成](translation-gemini-37-100-20260915.md)。线上仍使用本次已上线的 DeepSeek。
