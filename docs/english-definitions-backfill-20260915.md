# 已有重点词英文释义补齐记录

2026-09-15 已补齐现有句库的 **710 句、2333 个重点词**。刷新页面即可读取英文解释；线上继续使用 `deepseek-v4-flash-0731`，API 路径、字段、类型和 `translation_pending` 的含义不变。

用户截图中的“本轮第 118 句”对应数据库 ID `322`：

> Previous studies on CSR have had trouble differentiating these effects because consumers can be affected by all three.

| 重点词 | 已保存的英文解释 |
| --- | --- |
| Previous | done or existing before the time being discussed |
| differentiating | recognizing or showing the difference between things |
| affected | influenced or changed by something |

这些解释追加在原有 `word_translations[word]` 字符串后面，格式仍为 `本义：…；句中：…；英文：…`。

## 原因

此前上线了新词卡的中英文生成能力，但没有回填已有词卡。截图中这句的释义保存于 9 月 8 日；排查时，全部 710 个现有句子都只有中文词义，共缺 2333 个英文解释。

页面直接展示完整释义字符串，没有过滤英文。已有非空中文不会触发缺失翻译恢复；之前的 100 句模型评测也按只读方式运行，没有写回学习数据。因此只验证生成接口并不足以让日常复习的旧词卡出现英文。

## 修复范围

- 先通过线上词卡接口生成并保存截图中三个词的英文解释。
- 对剩余 709 句，只生成英文解释并追加到已有字符串，不重新生成整句中文或替换原有中文词义。
- 首批补齐 629 句、2003 个词；80 句因引文标点、词条尾部标点或输出格式未通过校验。保留已成功结果，修正标点处理并缩小批次后，补齐剩余 80 句、327 个词。
- 每批由 DeepSeek 生成，再由同一模型另一次调用检查。助手逐句阅读全部英文解释，并进一步修正 153 项词义、词性、搭配或表达问题；这些是对已追加英文的修正，不重复计入新增数量。
- 例如修正了 `correlated` 被解释为因果关系、`wear` 被解释成名词、`satellite` 被混入邻词 `data` 的含义，以及责任语境中 `rests on` 被解释成“以……为基础”的问题。

修改前保存了完整句子快照。写入时再次核对原文、整句中文和词义映射；遇到并发编辑就跳过。实际 SQL 只更新 `word_translations_json` 和 `updated_at`，没有重建复习安排或更换模型，也不需要重启应用。

## 验证

- 全部 710 句、2333 个重点词均有英文解释，缺失数为 0；通过现有词卡格式检查。
- 所有原词条键和原中文词义逐项保持一致；句子表中除上述两个字段外，其他字段均与修改前快照一致，包括原文、整句译文、分块、音频信息、播放计数和复习记录。
- Python 编译、模块边界、前端 25 项测试、前端构建和后端可靠性检查通过。新增的检查覆盖异常候选拒绝、旧词条标点保留、重复写入保护，以及生成期间发生的内容编辑和学习计数变化。
- 对线上现有接口读取结果、公开页面和健康检查进行验证；OpenAPI 与前次部署版本完全相同。临时验证会话在使用后清理。

原始记录位于 `backend/data/audits/legacy-english-definitions-20260915/`：

- [修改前快照](../backend/data/audits/legacy-english-definitions-20260915/before-sentences.json)
- [首批结果](../backend/data/audits/legacy-english-definitions-20260915/summary.json)及[漏项补齐结果](../backend/data/audits/legacy-english-definitions-20260915/retry/summary.json)
- [助手复核与修正](../backend/data/audits/legacy-english-definitions-20260915/assistant-corrections-applied.json)
- [全库数据核验](../backend/data/audits/legacy-english-definitions-20260915/data-verification.json)
- [线上接口与公开页面验证](../backend/data/audits/legacy-english-definitions-20260915/live-verification.json)
- [代码检查结果](../backend/data/audits/legacy-english-definitions-20260915/checks.json)

可复用脚本为 `backend/scripts/english/backfill_english_definitions.py`。默认仅列出待补齐范围；`--generate` 生成并复核候选，`--apply` 在核对当前数据后追加英文。脚本使用现有专用英语 AI 环境配置，要求先有中文词义；不会替换已有英文。后续需要为单条中文词卡补充英文时，也可继续使用网页“编辑 → 生成翻译 → 保存”。
