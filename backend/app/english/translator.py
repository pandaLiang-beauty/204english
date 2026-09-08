from __future__ import annotations

import json
import os
import re
from collections import OrderedDict
from typing import Any

from ..platform.ai_transport import AIProviderError, _chat_completion
from .translation_transport import translation_completion
from .translation_glossary import ground_sentence_terms, ground_word_cards
from .translation_quality import (
    segmentation_advisory_issues,
    translation_result_issues,
    validate_translation_result,
    word_translation_issues,
)


WORD_PATTERN = re.compile(r"[A-Za-z]+(?:['-][A-Za-z]+)*")
# Segment positions must count quantities as well as alphabetic words.  If
# ``20%`` is omitted from the numbered sequence, a model can intend to cut
# after the amount but accidentally place the boundary before ``by about``.
SEGMENT_TOKEN_PATTERN = re.compile(
    r"[A-Za-z]+(?:['-][A-Za-z]+)*|\d+(?:[.,]\d+)*(?:%|['’]s)?"
)
FINAL_SOURCE_ATTRIBUTION_PATTERN = re.compile(
    r",\s*(?:(?:said|says?|wrote|writes?|reported|reports?|argued|argues?|noted|notes?|"
    r"added|adds?)\s+[^,;:!?]+|according\s+to\b[^,;:!?]*)[.!?]\s*$",
    re.I,
)
LEADING_TRANSLATION_ATTRIBUTION_PATTERN = re.compile(
    r"^(?P<who>[^，,:：。！？!?]{1,60}?)(?P<verb>说|表示|写道|指出|称|报道|认为|补充道|评论道)"
    r"[：，,]\s*[“\"]?(?P<body>.+?)[”\"]?[。.!！?？]?$"
)
LEADING_ACCORDING_TRANSLATION_PATTERN = re.compile(
    r"^据(?P<who>[^，,:：。！？!?]{1,60}?)(?:所述|称|表示|指出)?[，,]\s*(?P<body>.+)$"
)
BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
INLINE_CHINESE_ANNOTATION_PATTERN = re.compile(r"\[[^\]]*[\u4e00-\u9fff][^\]]*\]")
ENGLISH_AI_PREFIX = "STUDY_ENGLISH_AI"
SENTENCE_OR_WORD_ISSUE_PREFIXES = (
    "empty_sentence_translation",
    "segmented_sentence_translation",
    "literal_translation:",
    "question_translation_missing",
    "sentence_translation_slash",
    "missing_word_translation:",
    "bad_word_translation_format:",
    "bad_word_evidence:",
    "bad_tip:",
)

# Keep the measured translation corrections in one short contract shared by
# the draft and review calls.  These are decision rules, not a corpus-wide
# dictionary: the surrounding words still decide the final Chinese wording.
TRANSLATION_PRECISION_RULES = (
    "已验证的易错模式（仍须以本句证据为准）：\n"
    "- 先锁定中心词、修饰范围和并列层级。`define X what Y explained as Z` 是“把过去由 Y 解释为 Z 的行为/现象界定为 X”；具体到 `define as addictions what earlier generations explained as weakness of will` 时，被界定的是“早期世代解释为意志薄弱的行为/现象”，绝不是“早期世代”本身。`A has V1 ... or V2 ...` 的 or 若连接两个谓语，必须保留并列，不能改成因果、方式或“或者说”。`either A or B results ...` 的 A/B 都是主语时，用“无论是 A 还是 B，都会……”。\n"
    "- 逐一保留小词和范围：few/less/relatively/too/only/still/same/successfully、百分比、时间长度（如 `in two days`）、性别与单复数均不得漏掉或擅自加强。`do much of anything` 是“几乎做任何事情”，不是“做很多事情”。\n"
    "- 否定与比较的作用域要先还原再汉化：`not ... any but X` 表示被否定的任务不涉及 X 以外的任何项，即范围仅限 X，不能译反。`pursuit less of A than of B` 的中心词是名词 pursuit，应译成“追求的与其说是 A，不如说是 B”，不能写成“无法控制地追求的”这种悬空结构。`too + 形容词 + to do` 是完整的程度—结果关系，必须保留“太/过于……而无法……”。\n"
    "- 代词必须沿用实体类型：policies/measures/programs 用“它们/这些措施”，不用“他们”；若提供的连续上下文明确给出 it/they/he 等的先行词，中文应自然还原为“该法院/这些措施”等实体或使用恰当代词，不能仍用含混或类型错误的“它/他们”；只有无法确认先行词时才用中性指代。未说明性别的 child 不擅自写“嫁入”；关系代词开头的文章截句（如 `who could ...`）保留为“能够……的人”等关系片段，不能改成“哪些人”这种独立疑问。\n"
    "- 固定关系不能靠中文习惯改写：`discourage X from doing` 必须明确译出否定目的，如“劝 X 不要做/阻止 X 做”，不能写成有歧义的“劝阻 X 做”，也不能叠成“劝阻 X 不要做”而造成双重否定；`rather than just focusing` 是“不只是/并非仅仅关注”，不是“不再关注”；with、分词、based on、to do 不擅自改成因果；`hidden from view` 是“不被看见/隐而不见”，不是主体“看不见”。\n"
    "- `Instead,` 独立起句时用“相反/取而代之的是/而”，不能写成缺少“不是”前项的“而是，”。句末 `instead` 必须保留“改为/而是”的替代关系；只有确有反向结果才译“反而”。`For another` 作代词时保留“对另一个人/另一种情况而言”，不能一律弱化成“此外”。\n"
    "- 按领域选择实体义：学术出版中的 papers 是“论文”；legal `preempt laws` 是“排除法律适用/使法律失效”；deregulate 是“放松监管”，不自动加强为“完全取消监管”；policy interest 要“服务于/实现重要政策利益（目标）”，不能“应对/回应政策利益”；成本语境的 price tag 是“价格/费用”，不是实体标签；`counterparts` 继承前面的中心名词，`revenue from print` 不擅自缩窄成印刷广告收入。\n"
    "- 名词中心与同位语的指向不得错挂：`two-paycheck status` 是家庭“靠两份工资/双收入的状态”，不是“双份工资”；照料老人语境的 `physical assistance` 是“生活或行动上的帮助/照料”，不是“对身体的援助”。`neuroticism, a personality dimension associated with self-consciousness and anxiety,` 中的同位语只解释 neuroticism，绝不能改挂到后面的 eye contact；所有“名词，同位语，新主语+谓语”结构都要如此复核。\n"
    "- 中文必须可独立成立。避免“情有可原地看起来”“夜间睡觉地方”“其正试图”“我们（这个）宇宙中心”“这些诸多”“去流利掌握”“为了不顾一切地”以及以“例如……时”收尾等搭配或结构残缺；`another tragic reminder` 是“又一次令人悲痛的提醒”，不能把 tragic 改成“悲惨地”修饰提醒动作；专名在同一材料中保持一致。\n"
    "- 称号/地点语境中，若 fill hotel bedrooms、bring in arts events/press 等谓语表明 holders/those 是地方，就译“获得该称号的城市或地区”，不要造“称号获得城市”，也不要把 hotel/events/press 缩窄。`for a year` 依语境译“在获称号的一年中/持续一年”。\n"
    "- 疑似 OCR 或截断先保留原词词性和不确定性；只有句内搭配明确排除字面义时作最小修复（`satisfy ... need for rapid content` 可按疑似 contentment 译为“迅速获得满足感”，但不能推广到普通 content）。`Shakespeare, who earns their living` 这类主谓指代明显冲突的残片不能写成已故莎士比亚“以此为生”，应作最小自然处理为“人们赖以谋生的莎士比亚”，只选一个译法，不用斜杠列备选。标题和截句保留未完成状态，不补结论。\n"
    "- 其他已测词义：抽象能力的 slippage 是“下滑/削弱”；came much slower 是“来得/进展慢得多”；payments 是付款/款项；affair 不自动加“盛大”；disruption 是干扰/不便；the argument goes 是“有人这样辩称”；elsewhere 是其他地方/情境；is the cure-all 不添加“被视为”；while ... suffers 不改成使役。\n"
    "- `as diverse as X, Y` 可译“形形色色，既有 X，也有 Y”；`Here's what X reveals about Y` 保留指示结构；`successfully insisted that Seymour's pictures illustrate his own story instead` 要译出“成功坚持要求改由西摩的画为自己的故事配图”，不能虚构“别的故事”；`skin-deep—and bone-showing` 按只重外表并推崇骨感理解；`constant health scares` 保持“反复的健康警报/健康恐慌（或担忧）”这一名词结构；`among the biggest rises` 是“涨幅位居最高之列”。"
    "\n- 上下文消歧时尤其复核领域义：时尚文章的 runways 是“T 台/走秀台”；文学出版语境的 published sketch 是“已发表的小品/随笔”，不是素描；科学出版语境的 Labour 若表示投入则是“劳动”，不是英国工党；neurology 是“神经学”，不是“神经病学”；出版业的 legal ecosystem 可指“合法出版体系/环境”，不能机械译作“法律生态系统”。"
    "\n- 动词和习语按宾语与语境落义：address needs 是“满足/回应需求”，不是“应对需求”；data went astray 是数据丢失、流失、误投或落入错误之手，不是笼统的“数据出错”；hold one's nose at 表示厌恶或嫌弃，不能改成“不屑一顾”；all too often 是“往往/常常（令人遗憾地）”，不能写成“太常常”。`at one's own expense` 既可能是“自费”，也可能是“由自己付出代价”，必须由上下文决定。"
    "\n- 大写不等于作品名。没有引号、斜体或明确作品语境时，不给普通大写复数名词擅加书名号，也不得改单复数；`Hamlet Hamburger Bars` 应保留为复数的哈姆雷特主题汉堡吧。town 是“城镇”，不能为顺口一律改成 city“城市”。"
    "\n- 再查容易被中文调序掩盖的关系：`Indian tribute` 是印第安人缴纳的贡赋，不要无依据颠倒收缴情形；`in a wide range of pursuits` 要落在研究范围上；`less secured payments` 是保障程度较低的款项/收入；`feelings of inadequacy` 是不足感/能力不足感，不自动缩成自卑感；`for the substantial sums ... paying` 表示所付费用与应得服务的对价，不只是普通因果。"
    "\n- 生成终稿前做中文结构复核：`a shelter that gives them three meals ... and a place to sleep` 应写成收容所“提供三餐和睡觉的地方”等清楚并列，避免“一个能……地方的收容所”的嵌套病句；`modern times have seen...` 必须给“经历”补出句内可证的中文主语（如“现代社会/人类经历了……”），不能形成“现代以来见证/经历了”的无主句；our common sense 要保留“我们的”；目的/结果不定式（如 provide enough food ... to reduce）不能随意改成无关联的并列动作。"
    "\n- 后置信息再复核一次中心词：`the kind of sustained concentration they will need for most jobs` 是“他们在大多数工作中所需的那种持续专注力”，避免“需要……所需”重复；截句 `component of a journalist` 须译成“记者的一项可取素质/组成部分”，不能是“一项可取组成”。关系词截句中若后面又出现 can/may/must 等独立情态谓语，要保留该谓语的断言作用，不能把全部内容都压成“……的人”修饰片段。"
    "\n- 上下文已能唯一确定代词时，终稿应自然还原中心实体：紧接 `The infrastructure required ... isn't just expensive;` 的 `it's excessive` 应说“这套基础设施还过于庞大/冗余”，不写“这显得过度”；承接 `print edition` 的 `discontinue it` 是“停办/取消纸质版”，不是整份报纸“停刊”。"
    "\n- 不要用副词破坏名词结构：`another tragic reminder` 必须是“又一次令人悲痛的提醒”，不能是“令人悲痛地提醒”。`the ones that feel bad` 在情感语境中是“让人感觉糟糕的/负面的情感”，不要无据缩成身体“不适”。`understandably` 用“不难理解，……”或“可以理解的是，……”组成完整句，不在主语后硬插“可以理解的是”。"
    "\n- 动宾关系不能因词面重复而打结：`protect stressed people from the increased risk for colds` 是“使承受压力者免受增高的感冒风险/降低其感冒风险”，不能是“降低感冒风险上升”。`most recent measures` 通常是“最新的衡量结果/指标”，不能倒装成“最新的大多数指标”；只有上下文明示数量范围时，most 才译“大多数”。英文同位名词短语在中文中若单放会成为无谓语残句，就应用破折号、“即/这是”或前置定语将它与主句自然衔接。"
    "\n- 最后朗读一次中文并消除直译痕迹：`only when there are comprehensive programs` 写成“只有在建立/有了综合性项目时”，不能出现“只有有”；`achieve fluency in other languages` 用“熟练掌握/流利使用其他语言”，不写“达到流利使用的程度”。同一短句中避免“需要……所需”、“要求出版商……的需求”、“真正成功的获此称号的城市或地区是那些……城市或地区”等重复套层，在不损失信息的前提下改成单层主干。"
    "\n- 其他已验证搭配：`earned him a modest reputation` 是“为他赢得了一些名气/使他小有名气”，不是“赢得了小有声誉”；`health scares end up with no one listening` 是“健康警报最终无人再理会”，不是“让谁也不再听了”；`terms ... render publishing easier for scientists` 的主语仍是 terms，不得凭空增加“让出版商使……”。源文疑似 OCR 或误录时不静默替换词形；按句内证据作最少、保守且自然的解释，必要时在词卡注明疑似误录，不凭领域常识增添颜色、时长或其他事实。"
    "\n- 数量和并列范围也要落到正确中心上：`oxytocin increased the amount of eye contact` 表示眼神交流的时长/次数/量增加，不是含糊的“眼神交流程度”。`services, punctuated by regular chaos when timetables are changed, or planned maintenance is managed incompetently` 中，or 并列的是引发混乱的两种情形，不是把“维护管理不善”与“忍受服务”并列。"
    "\n- position、expense 等多义词不得脱离话题机械套用：`the position of the Church` 在讨论权力安排时通常是“教会的地位”，只有明确谈观点才是“教会的立场”；`make countryside` 在土地稀缺语境是“无法再创造更多乡村土地”，不是建设既有乡村。"
    "\n- 介词和同位复述决定论元关系：`praise X for Y` 是“因 Y 而赞扬 X”，不能把 Y 误作被赞扬对象。`give organizations a basis, a basis for planning to meet the possibilities of ...` 中后一个 a basis 是对前一个 basis 的同位复述，含义是“为规划如何应对可能出现的不同环境提供依据”，不能改成“应对该环境带来的各种可能性”。"
    "\n- 把英文比较结构改成自然的中文主干：`promises ... came much slower` 在承诺语境中是“承诺兑现/落实得慢得多”，不是“承诺来得慢”；`differences are swamped by how well each person encodes` 是“个体差异会被各自的信息编码质量/效果所淹没”，不要硬译成“被……编码得有多好盖过”。`budgeted to the limits of their new two-paycheck status` 是家庭已依靠/按照双收入把预算安排到极限，不是存在一个“双收入状态的极限”。`a weak elderly parent` 用“年迈体弱的父亲或母亲/老人”，不能把 one 写成“一位……的父母”。"
    "\n- 疑问语气要同时看句法和标点。原始材料即使末尾漏了问号，`what is ...`、`how much can ...`、`which of the following ... is ...`、`why did ...` 等直接疑问仍须译成中文问句并补问号；但 `who/which` 引导的关系截句，以及 `How ... is still a mystery` 这类作主语的名词性从句，不是独立问句。"
)

SEGMENTATION_CONTRACT = (
    "目标：在不重新翻译的前提下，把英文原文与既有中文译文切成英中对应的阅读块。\n"
    "输出：只返回 JSON object：{\"source_breaks\":[\"英文切点前的原文短语\"],\"translation_breaks\":[\"对应中文切点前的原文短语\"]}。只列内部切点，不列句末。每个引文必须逐字复制自给定原文，含该切点前的几个词或若干中文字及标点，且在该文本剩余部分只出现一次。程序在引文末尾切分，无须数词或重复整句。例：英文 First we listen, then we act. 与中文 先听，再行动。可返回 {\"source_breaks\":[\"First we listen,\"],\"translation_breaks\":[\"先听，\"]}。\n"
    "硬约束：两个切点数组长度相同且逐项对应；引文按原文顺序排列，不得改写、概括、跳词或用省略号代替原文。程序会从原文截取所有块，不能增词、删词或交换语序。若中英自然语序无法逐块对应，两数组均返回 []，保留整句一块。\n"
    "块数决策：短句、标题、文章截句，或中英倒序会使停顿不自然时保留 1 块。完整句达到约 18 词且有两个以上清楚的语义动作/层次时，先尝试 2—4 块；14 词以上若有两个完整并列谓语（尤其是 `or` 连接的谓语），也应优先尝试 2 块。优先在背景/条件→主句、让步/转折、并列或结果、冒号说明、句末署名处停顿。22 词以上且以短时间/地点背景开头（如 `Last Thursday,`、`From the early days ...,`）时，只要中文也同序开头，就应把该背景或其后的完整主句作为明确停顿；24 词以上含一对破折号插入说明时，应尝试在完整插入语两侧形成 2—4 个层次。没有安全切点才回到 1 块。收到任何 `undersegmented_...` 提示时，本次必须先实际尝试至少 2 块，仍不能逐块对齐才回退一块。英文句末的 if/when/as 等内容已被中文整体调到句首时，为了不错位而保留一块就是正确回退。\n"
    "块的完整性：每块应是一个可理解的短语或阅读动作；句首完整的时间/地点/背景/条件短语可以单独成块，但不要孤立 it/they/are there/or/and/but、助动词或介词，也不要以并列或从属连词结尾。禁止在限定词/数量/形容词与其中心名词之间切（如 `such / trends`、`middle class / family`、`elite / soccer players`、`about / 20%`）；不要在 those/that/which/who 等关系引导词后立即切断。不要把短主语与谓语拆开；已经完整列完且较长的复杂主语（尤其 either A or B）可以作为学习块，再接共同谓语。\n"
    "动词与必需补语保持整体：`results in fines`、`has sided with`、`approval to a law`、`depend on`、`lead to`、`apply to`、`said/admitted/reveal that...` 等不能在动词、名词或介词前后截断；同样不能切成 `acceleration / of...`、`too small / to satisfy`、`struck / terror`、`the fact / that...`、`is / a matter...`、`were / captured`。系动词要带表语，助动词要带后续动词。也不要停在 first（后接 by）、partly（后接 because）、in the same way（后接 that）或疑问助动词 should 后。短直接引语要与 `saying/said + 引号` 作为同一阅读动作。冒号/分号是候选切点：要么恰好在其后切，要么保留整个说明，不能吞入一两个说明词再切。\n"
    "保持整体：fears/concern/worry + that 从句、would ... if ...（中文需‘如果…就…’）、It's/It is not obvious how|whether|why...、answer questions、关系词及其定语从句，以及中文必须提前的句尾时间/条件/比较成分，应放在同一自然块内。不要在 before/after/when/while/if/because/with + 主语之后、从句谓语或分词谓语之前切；不要拆 Paragraphs 5 and 6、from 2008 to 2012。若英文 `for a year`、`over nearly two decades` 等时间范围在后块，而中文已把“一年/近二十年”提前，就合并相关块，不能错位。Born/Called/Named/Known 引出的句首背景若已完整到逗号，可独立成块；若会产生倒装或英中错位则合并。\n"
    "切点示例：疑问句 `How can the train operators possibly justify ...?` 不要拆成孤立的 `How can the train operators`；`Are there divisive issues ...?` 不要把 `Are there` 单独成块。并列 `either...or`/`not only...but` 若共享同一个主句谓语，先把所有并列主语放在同一块，再在完整主语与谓语之间切；若连接两个各自完整的谓语，可在第二个 or 谓语前切，但不要把 or/and 单独留下。不要切成 `whatever ..., those differences / are...`、`Given ..., they / did...`、`the defining characteristic of IQ tests / has changed` 或 `... answer / questions ...`。署名示例：\"... results in fines ... officials, says one researcher.\" 可切为 [\"... by about 20%\", \"results ... officials,\", \"says one researcher.\"]，对应中文 [\"我们估计……约20%，\", \"通常会使……低40%，\", \"一位研究人员说。\"]；切点必须在整个署名动词之前，绝不能切成 `..., wrote / Chief Justice...`。`..., he said. / The move...` 是在完整署名和句号后切分，可以保留。即使整句中文把署名提前，分块时也必须将署名移回最后一个中文块并与最后英文块对应。\n"
    "最终逐边界检查三遍：① 切点左右没有拆开限定词+名词、动词+补语、从属主语+谓语；②每个中文块只对应同序英文块，没有把后一块含义提前；③所有引文确实逐字存在于输入文本。任一项不满足就删除该切点；宁可少切，也不要制造孤立词、改写或英中错位。"
)

MAX_REFERENCE_CONTEXT_ITEMS = 3
MAX_REFERENCE_CONTEXT_CHARS = 2400


class TranslationQualityError(AIProviderError):
    def __init__(self, user_message: str, diagnostic: str, candidate: dict[str, Any]):
        super().__init__(user_message, diagnostic)
        self.candidate = candidate


def _fidelity_focus(sentence: str, context_before=None, context_after=None) -> str:
    rules = [
        "先确认指代对象和中心词：代词不得因离某名词近就指向它；无明确先行词时保持中性。多个 of 短语或并列修饰语共有的中心词必须覆盖全部并列项。",
        "严格区分比较的维度：程度、发生概率、绝对水平、变化幅度不是一回事。less of a problem 是问题程度较轻，不是问题更不可能发生；low prices 是价格低，不等于价格下跌；how much more effective 问的是有效性提高多少。",
        "保留每个有意义的限定与关系，尤其 in return 等交换关系及 new and unexplored 这类并列性质；不能只保留其中一个意思。",
        "不把含糊表述升级为确定事实：讨论或流转不等于正式审议；媒体呈现某人不必然是刊登照片；某种态度不等于已发表言论；不可擅加原文未给出的载体、程序或行为。",
        "数值和数量以本句为准，上下文只帮助确认指代，不追加本句未出现的数量或背景事实。",
        "并列谓语必须分别能与中文主语搭配；若把集合名词具体化为数量、规模等，只能用于相应谓语，不能让数量去抗拒、赞同或思考。情态或否定范围内的 any 不自动等于所有人都实际发生了某事。",
        "动作及结果要同时保留：hunted to extinction 的灭绝是猎杀造成的，不是仅仅容易被猎杀后自行灭绝；by doing 表示手段，不要只写成先后动作。",
        "最后按自然中文重组，而不是照抄英文词序：修饰语应贴合正确中心词；happily married 是婚姻幸福，不是幸福已婚；be proved/prove 作系动词时不必硬写将证明是。中文必须能独立、流畅地读懂。",
    ]
    lowered = sentence.casefold()
    if "national trust" in lowered:
        rules.append("National Trust 在自然/历史遗产保护语境是国民信托组织，不是金融信托基金；不确定正式译名时保留原名，不能错换机构类型。")
    if re.search(r"\bthe times\b", lowered):
        context = " ".join([sentence, *(context_before or []), *(context_after or [])]).casefold()
        if "new york times" in context:
            rules.append("上下文明确出现 The New York Times，若本句 Times 指同一报刊应为《纽约时报》，不能换成英国《泰晤士报》。")
        else:
            rules.append("本句 the Times 没有完整报刊名可确认时保守译为《时报》，不能自行认定是英国《泰晤士报》。")
    if re.search(r"\bvocal\b", lowered):
        rules.append("vocal 修饰表达诉求的群体时是积极发声、敢于表达意见，不是字面上嗓门响亮。")
    if "high-profile" in lowered:
        rules.append("high-profile 表示备受关注或引人注目，不等于高规格、高级别。")
    if "elevating" in lowered and "culture" in lowered:
        rules.append("文化语境的 elevating 指陶冶情操、提升精神境界，不只是情绪振奋。")
    if re.search(r"\ba parent\b", lowered):
        rules.append("a parent 指一位家长（父亲或母亲），不应把一个人的角色译成两个人的父母。")
    if re.search(r"\bsomehow\b", lowered):
        rules.append("somehow 指以某种方式或不知为何，不是表示程度的 somewhat；不能翻成在某种程度上。")
    if re.search(r"\bfrankly\s+(?:dislike|hate|resent|prefer|love)\b", lowered):
        rules.append("frankly 修饰态度时可以表达毫不掩饰，不表示这些人已说过或公开表示了该态度；不要擅自增加表示、宣称等言语行为。")
    if re.search(r"\bconfide\b", lowered):
        rules.append("confide something to someone 是向某人吐露某事；中文应保留向、对等介词，不能让接受者误成吐露的主语或被吐露的内容。")
        rules.append("could not confide 中的情态是不能吐露；保留能力或处境限制，不擅自归因于主观意愿。")
    if "food police" in lowered:
        rules.append("food police 通常比喻干预、说教他人饮食的饮食卫士，并不当然是政府食品监管机构；没有明确机构证据时保留比喻。")
    if re.search(r"\bsuccessful\s+holders?\b", lowered):
        rules.append("successful 修饰 holders，指获得称号者表现成功，不是成功获得称号这个动作。for a year 表示持续一年，应紧贴它限定的活动，不能孤悬为句末的那一年。")
    if re.search(r"\beither\b.+\bor\b.+\bresults?\b", lowered):
        rules.append("either A or B 是共同主语时，中文必须有完整谓语；可以用无论A还是B，都使……，不要写成无论A还是B，所导致的……这种悬空结构。")
    if re.search(r"\bdoing the rounds\b", lowered):
        rules.append("doing the rounds 指流传、传阅或在某个圈子中被讨论；proposed legislation 指立法提案。保留提案流转这个层级，不确定其具体法律程序。")
    if "mystery" in lowered and re.search(r"\bshould\b.+\bany\b", lowered):
        rules.append("这里 should ... any 表示哪怕有一个人出现这种反应都令人不解；any 的范围是任一、哪怕一位，不是所有人均已如此。")
    if re.search(r"\bready for\b", lowered):
        rules.append("ready for 表示为某事做好准备；原文概括准备状态时，译文也保持概括，不自行细分准备种类。")
    if "guilty pleasure" in lowered:
        rules.append("guilty pleasure 的中心是令人内疚的享受或乐趣；guilty 表示这份愉悦会让人内疚，中文应构成完整自然的定中短语。")
    if "cascade" in lowered and "burdensome" in lowered:
        rules.append("cascade 在连续出现的费用语境是一连串；名词前用一连串的等完整数量结构。burdensome and costly 应自然表述负担沉重、成本高昂，prove 作系动词表示日后显现的实际状况。")
    if re.search(r"\bless of an?\b", lowered):
        rules.append("less of a/an 比较性质或程度，中文要明确表达程度较轻、作用较小等程度差异；can 保留可能性，但 less 本身不是发生概率。")
    if re.search(r"\brsc\b", lowered) and "actors" in lowered:
        rules.append("演员和戏剧语境中的 RSC 指皇家莎士比亚剧团（Royal Shakespeare Company），按剧团的机构类型翻译其专名。")
    if "painful reminder" in lowered:
        rules.append("a painful reminder 是让人忆起痛苦往事的提醒。view X as A and B 中 A、B 都是对 X 的看法，保留它既是A、也是B的并列关系和共同指代。")
    return "本次特别核对（必须仍以原文证据为准）：\n" + "\n".join(f"- {rule}" for rule in rules) + "\n\n"


def _focused_sentence(sentence: str) -> str:
    matches = [match.group(1) for match in BOLD_PATTERN.finditer(sentence or "")]
    if matches:
        return " ".join(matches)
    return ""


def extract_words(sentence: str) -> list[str]:
    scoped = _focused_sentence(sentence)
    seen = set()
    words: list[str] = []
    for match in WORD_PATTERN.finditer(scoped):
        word = match.group().strip()
        lowered = word.lower()
        if not word or lowered in seen:
            continue
        seen.add(lowered)
        words.append(word)
    return words


def _normalize_words(words: list[str] | None, sentence: str) -> list[str]:
    candidates = words if words is not None else extract_words(sentence)
    seen = set()
    result: list[str] = []
    for raw in candidates:
        # Historical focus markers occasionally include adjacent sentence
        # punctuation (for example ``**bone-showing.**``).  That punctuation
        # is not part of the word the model is asked to return, so retaining it
        # here would make an otherwise correct response fail exact key matching.
        word = str(raw or "").strip().strip(".,;:!?，。；：！？、()[]{}\"“”‘’")
        lowered = word.lower()
        if not word or lowered in seen:
            continue
        seen.add(lowered)
        result.append(word)
    return result[:40]


def _translation_source(sentence: str) -> str:
    """Return the English source that should be sent to translation tasks.

    Focus markers are display metadata, while square brackets containing Chinese
    are author annotations. Neither is part of the English sentence to translate.
    English-only bracketed source content is retained (for example, citations).
    """
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", str(sentence or ""))
    cleaned = INLINE_CHINESE_ANNOTATION_PATTERN.sub("", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _normalize_reference_context(
    values: list[str] | tuple[str, ...] | None,
    *,
    keep_last: bool,
) -> list[str]:
    """Return a small, source-only context window safe to place in a prompt."""
    cleaned: list[str] = []
    for value in values or []:
        source = _translation_source(str(value or ""))[:MAX_REFERENCE_CONTEXT_CHARS].strip()
        if source:
            cleaned.append(source)
    if keep_last:
        return cleaned[-MAX_REFERENCE_CONTEXT_ITEMS:]
    return cleaned[:MAX_REFERENCE_CONTEXT_ITEMS]


def _reference_context_note(
    context_before: list[str] | tuple[str, ...] | None,
    context_after: list[str] | tuple[str, ...] | None,
) -> str:
    """Format optional neighbouring source without making it translation input."""
    before = _normalize_reference_context(context_before, keep_last=True)
    after = _normalize_reference_context(context_after, keep_last=False)
    if not before and not after:
        return ""
    return (
        "参考上下文使用边界：以下相邻英文只用于判断目标句中的代词先行词、多义词、专名、"
        "领域和截句关系；不得翻译、复述或补入目标译文。相邻项可能来自另一道题或另一篇文章，"
        "主题或指代链不连续时必须忽略。目标句本身仍是唯一需要翻译的内容。\n"
        f"<context_before>{json.dumps(before, ensure_ascii=False)}</context_before>\n"
        f"<context_after>{json.dumps(after, ensure_ascii=False)}</context_after>\n"
    )


def _translation_aligned_for_final_attribution(sentence: str, translation: str) -> str:
    """Move a Chinese fronted attribution back for paired reading blocks.

    Chinese naturally prefers ``X说，正文`` while the source may end with
    ``..., said X``.  The whole-sentence translation stays untouched; only the
    text handed to the block editor is reordered so its final Chinese block can
    correspond to the final English attribution.
    """
    source = str(sentence or "").strip()
    target = str(translation or "").strip()
    if not FINAL_SOURCE_ATTRIBUTION_PATTERN.search(source):
        return target

    match = LEADING_TRANSLATION_ATTRIBUTION_PATTERN.match(target)
    if match:
        body = match.group("body").strip().rstrip("”\"。.!！?？")
        if body:
            return f"{body}，{match.group('who')}{match.group('verb')}。"

    match = LEADING_ACCORDING_TRANSLATION_PATTERN.match(target)
    if match:
        body = match.group("body").strip().rstrip("。.!！?？")
        if body:
            return f"{body}，{match.group('who')}称。"
    return target


def _strip_code_fence(text: str) -> str:
    cleaned = (text or "").strip()
    fence_match = re.match(r"^```(?:json|JSON)?\s*(.*?)\s*```$", cleaned, flags=re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json|JSON)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    return cleaned


def _decode_json_object_from_text(text: str) -> dict[str, Any] | None:
    cleaned = _strip_code_fence(text)
    decoder = json.JSONDecoder()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed

    start = cleaned.find("{")
    if start < 0:
        return None
    try:
        candidate, _ = decoder.raw_decode(cleaned[start:])
    except json.JSONDecodeError:
        return None
    if isinstance(candidate, dict):
        return candidate
    return None


def _extract_json_object(
    text: str,
    *,
    user_message: str = "AI 返回格式异常，请重试。",
    diagnostic_label: str = "AI JSON",
) -> dict[str, Any]:
    parsed = _decode_json_object_from_text(text)
    if parsed is None:
        cleaned = _strip_code_fence(text)
        raise AIProviderError(user_message, f"{diagnostic_label} parse failed: {cleaned[:1000]}")
    return parsed


def _repair_json_object(
    raw: str,
    *,
    user_message: str,
    diagnostic_label: str,
    expected_schema: str,
) -> dict[str, Any]:
    messages = [
        {
            "role": "system",
            "content": (
                "你是 JSON 修复器。只输出一个合法 JSON object，不输出 Markdown、代码块、解释或额外文字。"
                "不要新增原输出中没有的信息；缺失字段用空字符串、空数组或空对象。"
            ),
        },
        {
            "role": "user",
            "content": (
                "下面是另一个模型返回的非标准内容，请把它转换成合法 JSON object。\n"
                "目标结构：\n"
                f"{expected_schema}\n\n"
                "原始内容：\n"
                f"{str(raw or '').strip()[:6000]}"
            ),
        },
    ]
    options = _english_ai_options()
    fixed = translation_completion(messages, options=options, completion=_chat_completion)
    parsed = _decode_json_object_from_text(fixed)
    if parsed is None:
        raise AIProviderError(user_message, f"{diagnostic_label} repair failed: {str(fixed or '')[:1000]}")
    return parsed


def _compose_word_translation(payload: dict[str, Any]) -> str:
    existing = str(payload.get("translation") or "").strip()
    base = str(
        payload.get("base_translation")
        or payload.get("base_meaning")
        or payload.get("literal_meaning")
        or ""
    ).strip()
    context = str(
        payload.get("context_translation")
        or payload.get("context_meaning")
        or payload.get("meaning_in_sentence")
        or ""
    ).strip()
    base = re.sub(r"^(?:本义\s*[:：]\s*)+", "", base).strip()
    context = re.sub(r"^(?:句中\s*[:：]\s*)+", "", context).strip()
    base = re.sub(r"^[A-Za-z][A-Za-z'-]*\s*[:：]\s*", "", base).strip()
    if not any(marker in base for marker in "()（）"):
        base = "；".join(dict.fromkeys(part.strip() for part in re.split(r"[；;]", base) if part.strip()))
    if base and context:
        return f"本义：{base}；句中：{context}"
    if context:
        return f"句中：{context}"
    if base:
        return f"本义：{base}"
    return existing


def _clean_tip(word: str, tip: str) -> str:
    cleaned = str(tip or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(rf"^{re.escape(word)}\s*[:：]\s*", "", cleaned, flags=re.IGNORECASE).strip()
    if not cleaned or len(cleaned) > 40:
        return ""
    banned = (
        "重音",
        "音标",
        "音节",
        "拼读",
        "拉丁",
        "来自",
        "源自",
        "词源",
        "单音节",
        "双音节",
        "三音节",
        "四音节",
    )
    if any(item in cleaned for item in banned):
        return ""
    if re.search(r"[读发]\s*/", cleaned):
        return ""
    return cleaned


def _normalize_segment_list(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_items = [item.strip() for item in re.split(r"\s*/\s*", value) if item.strip()]
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []
    segments: list[str] = []
    for item in raw_items:
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", str(item or "").strip())
        text = text.replace("**", "")
        text = re.sub(r"\s+", " ", text)
        if text:
            segments.append(text)
    return segments[:40]


def _segments_from_anchors(text: str, anchors: Any) -> list[str] | None:
    if not isinstance(anchors, list):
        return None
    segments: list[str] = []
    start = 0
    for anchor in anchors:
        if not isinstance(anchor, str) or not anchor.strip():
            return None
        anchor = anchor.strip()
        position = text.find(anchor, start)
        if position < 0 or text.find(anchor, position + 1) >= 0:
            return None
        end = position + len(anchor)
        while end < len(text) and text[end] in " \t\r\n,.;:!?，。；：！？":
            end += 1
        segment = text[start:end].strip()
        if not segment or not text[end:].strip():
            return None
        segments.append(segment)
        start = end
    tail = text[start:].strip()
    return [*segments, tail] if tail else None


def _anchored_segment_payload(sentence: str, translation: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    if "source_breaks" not in payload and "translation_breaks" not in payload:
        return None
    sources = _segments_from_anchors(sentence, payload.get("source_breaks"))
    targets = _segments_from_anchors(translation, payload.get("translation_breaks"))
    if not sources or not targets or len(sources) != len(targets):
        return None
    return {"sentence_segments": sources, "translation_segments": targets}


def _compact_segment_payload(sentence: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Expand the compact ``cut_after`` response into ordinary text blocks.

    Repeating a 40–80 word English sentence in JSON often hits provider output
    limits. Asking for cumulative word/number token positions keeps the response small and
    lets us enforce exact source coverage locally.
    """
    raw_cuts = payload.get("cut_after")
    if raw_cuts is None and isinstance(payload.get("segment_lengths"), list):
        running = 0
        converted: list[int] = []
        for length in payload["segment_lengths"]:
            try:
                running += int(length)
            except (TypeError, ValueError):
                converted = []
                break
            converted.append(running)
        raw_cuts = converted
    if raw_cuts is None:
        raw_cuts = payload.get("word_breaks") or payload.get("breaks") or payload.get("cuts")
    if isinstance(raw_cuts, (int, float)) and not isinstance(raw_cuts, bool):
        raw_cuts = [raw_cuts]
    if isinstance(raw_cuts, str):
        raw_cuts = re.findall(r"\d+", raw_cuts)
    if not isinstance(raw_cuts, list):
        return None

    word_matches = list(SEGMENT_TOKEN_PATTERN.finditer(sentence))
    word_count = len(word_matches)
    if word_count <= 0:
        return None
    cuts: list[int] = []
    for raw in raw_cuts:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None
        if value <= 0 or value > word_count or (cuts and value <= cuts[-1]):
            return None
        cuts.append(value)
    if not cuts:
        cuts = [word_count]
    elif cuts[-1] < word_count:
        # Be forgiving when the model lists only internal breaks; the final
        # block always ends at the source sentence end.
        cuts.append(word_count)
    if cuts[-1] != word_count:
        return None

    translation_segments = _normalize_segment_list(payload.get("translation_segments"))
    if len(translation_segments) != len(cuts):
        return None

    sentence_segments: list[str] = []
    start_word = 0
    for end_word in cuts:
        # Preserve opening quotes, dashes, ellipses and other source
        # punctuation in the first block.  Starting at the first token would
        # silently drop that display text (for example the opening quote in
        # ``"pathological gambling"``).
        start_char = 0 if start_word == 0 else word_matches[start_word].start()
        end_char = len(sentence) if end_word == word_count else word_matches[end_word].start()
        segment = sentence[start_char:end_char].strip()
        if not segment:
            return None
        sentence_segments.append(segment)
        start_word = end_word
    return {
        "sentence_translation": "",
        "sentence_segments": sentence_segments,
        "translation_segments": translation_segments,
    }


def _normalize_translation_payload(payload: dict[str, Any], words: list[str]) -> dict:
    sentence_translation = str(
        payload.get("sentence_translation")
        or payload.get("natural_translation")
        or payload.get("translation")
        or ""
    ).strip()
    sentence_segments = _normalize_segment_list(
        payload.get("sentence_segments")
        or payload.get("english_segments")
        or payload.get("source_segments")
    )
    translation_segments = _normalize_segment_list(
        payload.get("translation_segments")
        or payload.get("chinese_segments")
        or payload.get("target_segments")
    )
    pairs = payload.get("segments") or payload.get("segment_pairs") or []
    if isinstance(pairs, list) and (not sentence_segments or not translation_segments):
        pair_sentence_segments: list[str] = []
        pair_translation_segments: list[str] = []
        for item in pairs:
            if not isinstance(item, dict):
                continue
            source = str(item.get("english") or item.get("source") or item.get("text") or "").strip()
            target = str(item.get("chinese") or item.get("translation") or item.get("target") or "").strip()
            if source:
                pair_sentence_segments.append(source)
            if target:
                pair_translation_segments.append(target)
        if not sentence_segments:
            sentence_segments = _normalize_segment_list(pair_sentence_segments)
        if not translation_segments:
            translation_segments = _normalize_segment_list(pair_translation_segments)
    word_items = payload.get("words") or payload.get("items") or payload.get("word_translations") or []
    if isinstance(word_items, dict):
        word_items = [{"word": key, "translation": value} for key, value in word_items.items()]
    if not isinstance(word_items, list):
        word_items = []

    by_lower: dict[str, dict[str, Any]] = {}
    for item in word_items:
        if not isinstance(item, dict):
            continue
        word = str(item.get("word") or "").strip()
        if word:
            by_lower[word.lower()] = item

    ordered = OrderedDict()
    tips: dict[str, str] = {}
    for word in words:
        item = by_lower.get(word.lower(), {})
        translation = _compose_word_translation(item) if item else ""
        if not translation:
            translation = str(item.get("meaning") or item.get("context_translation") or "").strip()
        ordered[word] = translation
        tip = _clean_tip(word, str(item.get("tip") or item.get("spelling_tip") or "").strip())
        if tip:
            tips[word] = tip

    items = []
    for word, translation in ordered.items():
        item = {"word": word, "translation": translation, **({"tip": tips[word]} if word in tips else {})}
        original = by_lower.get(word.lower(), {})
        for field in ("source_quote", "translation_quote"):
            if field in original:
                item[field] = str(original[field] or "").strip()
        items.append(item)
    return {
        "items": items,
        "word_translations": dict(ordered),
        "word_tips": tips,
        "sentence_translation": sentence_translation,
        "sentence_segments": sentence_segments,
        "translation_segments": translation_segments,
    }


def translation_configured() -> bool:
    base_url = os.getenv(f"{ENGLISH_AI_PREFIX}_BASE_URL", "").strip()
    api_key = os.getenv(f"{ENGLISH_AI_PREFIX}_API_KEY", "").strip()
    model = os.getenv(f"{ENGLISH_AI_PREFIX}_MODEL", "").strip()
    return bool(base_url and api_key and model)


def _english_bool_env(name: str) -> bool | None:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return None
    return value in {"1", "true", "yes", "on"}


def _english_number_env(name: str, parser, *, user_label: str) -> Any | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    try:
        return parser(value)
    except (TypeError, ValueError) as exc:
        raise AIProviderError(
            f"英语翻译 AI 配置无效，请检查{user_label}。",
            f"English AI {name} is invalid: {exc}",
        ) from exc


def _english_ai_options() -> dict[str, Any]:
    base_url = os.getenv(f"{ENGLISH_AI_PREFIX}_BASE_URL", "").strip()
    api_key = os.getenv(f"{ENGLISH_AI_PREFIX}_API_KEY", "").strip()
    if not base_url or not api_key:
        raise AIProviderError("英语翻译 AI 服务未完整配置")
    model = os.getenv(f"{ENGLISH_AI_PREFIX}_MODEL", "").strip()
    if not model:
        raise AIProviderError("英语翻译 AI 模型未配置")
    options: dict[str, Any] = {
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
    }

    temperature = _english_number_env(
        f"{ENGLISH_AI_PREFIX}_TEMPERATURE",
        float,
        user_label="温度参数",
    )
    if temperature is not None:
        options["temperature"] = temperature

    timeout = _english_number_env(
        f"{ENGLISH_AI_PREFIX}_TIMEOUT_SECONDS",
        float,
        user_label="超时参数",
    )
    if timeout is not None:
        options["timeout_seconds"] = timeout

    disable_thinking = _english_bool_env(f"{ENGLISH_AI_PREFIX}_DISABLE_THINKING")
    if disable_thinking is not None:
        options["disable_thinking"] = disable_thinking

    reasoning_effort = os.getenv(f"{ENGLISH_AI_PREFIX}_REASONING_EFFORT", "").strip()
    if reasoning_effort:
        options["reasoning_effort"] = reasoning_effort

    return options


def _json_from_chat(
    messages: list[dict[str, str]],
    *,
    user_message: str,
    diagnostic_label: str,
    expected_schema: str,
) -> dict[str, Any]:
    raw = translation_completion(messages, options=_english_ai_options(), completion=_chat_completion)
    if not raw:
        raise AIProviderError(user_message)
    try:
        return _extract_json_object(
            raw,
            user_message=user_message,
            diagnostic_label=diagnostic_label,
        )
    except AIProviderError:
        return _repair_json_object(
            raw,
            user_message=user_message,
            diagnostic_label=diagnostic_label,
            expected_schema=expected_schema,
        )


def _translate_sentence_only(
    sentence: str,
    *,
    feedback: str = "",
    audit: dict[str, Any] | None = None,
    context_before: list[str] | tuple[str, ...] | None = None,
    context_after: list[str] | tuple[str, ...] | None = None,
) -> str:
    retry_feedback = str(feedback or "").strip()
    feedback_note = (
        "上一次结果被质量审查拒绝，原因是："
        f"{retry_feedback}。\n"
        "这次只修正整句中文译文，不要解释。\n\n"
        if retry_feedback
        else ""
    )
    payload = _json_from_chat(
        [
            {
                "role": "system",
                "content": (
                    "你是英语学习材料的英汉翻译器。只翻译明确标出的目标英文；"
                    "相邻英文若提供，只能按使用边界辅助消歧。只输出 JSON，不输出解释。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "返回 JSON：{\"anchors\":[{\"source\":\"有歧义或易漏的原文短语\",\"meaning\":\"简短中文对应或明确的指代对象\"}],\"sentence_translation\":\"中文译文\"}。先列最多六个必要语义锚点，再写译文；简单句可用空数组，不要长篇分析。\n"
                    "翻译合同：\n"
                    "1. 语义准确优先于文采。逐项保留主语、谓语、宾语、修饰关系、否定、情态、比较/数量、条件、转折、因果、并列、时态和语气；不得漏译、增译或改换逻辑。\n"
                    "2. 输入可能是文章截句、标题或短语。没有句号不表示可以补写结论；保留原文的未完成状态，不替它接上前后文。\n"
                    "3. 代词或指代在片段中无明确先行词时，用中性的“其/该对象/他们/它们”等表达，不能凭空命名“秘密”“服务”等先行词。\n"
                    "4. 按词性、搭配和语境选词，不把名词改成动作，不把相近词臆换（如 content 不自动改成 contentment，models 在 fashion/images 语境通常是“模特”）。先确认每个短语的主语、中心名词和修饰范围，再做自然汉化；不要把定语/伴随结构改成因果、把并列改成使役或把中性词改成更强的评价。若原文疑似 OCR/截断或搭配明显不合语法，避免输出无意义直译，可依据句内证据作最小、自然的解释，但不要编造新事实。习语可自然意译，但不得加入原文没有的评价或因果。\n"
                    "5. 代词和集合名词要保持实体类型：those/holders 若由 hotel、city、event 等谓语说明是地方或机构，不要默认翻成“人”；先行词不明时用中性表达。\n"
                    "6. 保留疑问句（包括 whether/or 选择）、省略号、百分比、专名、缩写和必要的标点；不要漏掉 same、too、successfully、男性/女性等限定信息；普通英文词不能残留，** 只是显示标记。\n"
                    f"{TRANSLATION_PRECISION_RULES}\n\n"
                    f"{_fidelity_focus(sentence, context_before, context_after)}"
                    f"{feedback_note}"
                    f"{_reference_context_note(context_before, context_after)}"
                    f"<target_sentence>{sentence}</target_sentence>"
                ),
            },
        ],
        user_message="AI 翻译返回格式异常，请重试。",
        diagnostic_label="sentence translation JSON",
        expected_schema='{"sentence_translation": "自然完整中文译文"}',
    )
    translation = str(
        payload.get("sentence_translation")
        or payload.get("natural_translation")
        or payload.get("translation")
        or ""
    ).strip()
    if not translation:
        raise AIProviderError("AI 翻译返回了空译文")
    if audit is not None:
        audit["draft_anchors"] = payload.get("anchors") if isinstance(payload.get("anchors"), list) else []
    return translation


def _structure_review_hint(sentence: str) -> str:
    source = sentence.casefold()
    if re.search(r"\btracks?\b.+\bemergence\b.+\band with it,?\s+(?:an?|the)\b", source):
        return (
            "结构骨架：某事物的兴起与两个相伴出现的事物在时间上对应；后置从句描述其中相应的事物。"
            "and with it 后的名词与前面的名词同受 emergence 支配。先识别两个并列对象，"
            "再把后置关系从句写成完整的中文分句，表达同步和伴随关系，保留原文的程度与指代。"
        )
    if re.search(r"\bview(?:s|ed|ing)?\b.+\bas\b.+\band\b.+\bpainful reminder\b", source):
        hint = (
            "结构骨架：主体将某对象视为第一种事物，也视为第二种事物。"
            "view 的对象不变，as 后两个补语都保持完整名词短语。painful reminder 可作为对某一往事的沉痛提醒。"
            "依照实际原文确认主语、时间、指代和修饰关系。"
        )
        if re.search(r"\bsmall\b.+\bbut\b.+\bvocal\b", source):
            hint += "群体人数不多与积极发声之间的转折也要明确保留。"
        if "what was once a sovereign nation" in source:
            hint += "what 指曾是主权国家的政治或地域实体，被占领的对象不是主句中的人群。该短语可还原为那个曾经的主权国家；保留历史指涉，不自行添加如今才被占领等时间说明。"
        return hint
    return ""


def _review_from_source_structure(
    sentence: str,
    hint: str,
    *,
    feedback: str = "",
    audit: dict[str, Any] | None = None,
    context_before: list[str] | tuple[str, ...] | None = None,
    context_after: list[str] | tuple[str, ...] | None = None,
) -> str:
    payload = _json_from_chat(
        [
            {
                "role": "system",
                "content": "你是专业英汉译者。先还原英文的句法关系，再独立写出自然、忠实的中文。完整覆盖已有信息；输入是截句时保留未完成状态，不补缺失谓语或结论。允许把一个长英文句写成两句中文，但所有信息及其关系必须保留。只输出 JSON。",
            },
            {
                "role": "user",
                "content": (
                    '输出 {"structure":"一句话说明主干和并列项关系","sentence_translation":"完整中文译文"}。\n'
                    f"本次结构提示：{hint}\n"
                    "只依据英文及可确认的指代翻译，不追加因果、时间或事实。完整原句的译文须语法连贯；原文未完成的从句和名词片段保持原有边界，可用省略号提示截断，不强行补成完整判断。\n"
                    "源文已有的短句或名词片段也要译出；没有作品名称依据时不加书名号或编造标题。\n"
                    "恢复代词时仅用最短、必要的实体名称，自然融入句子；不要用括号插入上下文中的地点或背景说明。\n"
                    f"需修正的已知问题：{feedback or '无；仍需逐项核对原文。'}\n"
                    f"{_reference_context_note(context_before, context_after)}"
                    f"<target_sentence>{sentence}</target_sentence>"
                ),
            },
        ],
        user_message="AI 翻译结构复核返回格式异常，请重试。",
        diagnostic_label="source structure review JSON",
        expected_schema='{"structure":"句法关系","sentence_translation":"中文译文"}',
    )
    reviewed = str(payload.get("sentence_translation") or "").strip()
    if not reviewed:
        raise AIProviderError("AI 翻译结构复核返回了空译文")
    if audit is not None:
        audit["review_strategy"] = "independent_source_structure"
        audit["structure_summary"] = str(payload.get("structure") or "")
    return reviewed


def _review_sentence_only(
    sentence: str,
    translation: str,
    *,
    feedback: str = "",
    audit: dict[str, Any] | None = None,
    context_before: list[str] | tuple[str, ...] | None = None,
    context_after: list[str] | tuple[str, ...] | None = None,
) -> str:
    """Review a sentence translation without mixing in blocks or word cards."""
    structure_hint = _structure_review_hint(sentence)
    if structure_hint:
        return _review_from_source_structure(
            sentence,
            structure_hint,
            feedback=feedback,
            audit=audit,
            context_before=context_before,
            context_after=context_after,
        )
    retry_feedback = str(feedback or "").strip()
    feedback_note = (
        "上一次结果被本地检查拒绝，原因是："
        f"{retry_feedback}。只修正与该问题有关的中文译文。\n\n"
        if retry_feedback
        else ""
    )
    payload = _json_from_chat(
        [
            {
                "role": "system",
                "content": (
                    "你是英汉翻译终审编辑。目标英文是唯一待译内容；相邻英文若提供，"
                    "只能用于指代、词义、专名、领域和截句消歧。逐项核对候选中文；"
                    "只输出 JSON，不做分块、词卡或讲解。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "返回 JSON：{\"issues_found\":[{\"source\":\"触发问题的英文\",\"problem\":\"候选问题\",\"fix\":\"如何修正\"}],\"sentence_translation\":\"终审后的中文译文\"}\n"
                    "先逐短语审计候选，再给终稿；issues_found 只记录实际发现的问题，候选完全正确时写 []。无论是否修改，都必须完成下面全部核对。\n"
                    "核对顺序：\n"
                    "1. 先确认句型和范围：陈述/疑问/祈使、主谓宾、否定、情态、条件、让步、转折、因果、比较、数量和时间；再核对每个后置修饰和代词。\n"
                    "2. 逐个检查容易被润色掩盖的词：either/or、neither/nor、only、still、too、may/would、more/less、百分比、专名和缩写。名词不可擅自改成动词，近义词不可凭感觉替换（fashion models 是“模特”）。or 必须区分并列选择与同位解释：前者保留或/要么，不能改成因果或解释；确在重述前项的后者可译即/也就是，不能机械套用为二选一。\n"
                    "3. 片段没有提供先行词或后文时，不补背景、不把残句改成完整判断；保持中性指代和未完成状态。明显 OCR/截断短语若直译会无意义，依据句内搭配做最小自然修正，但不要扩写事实。\n"
                    "4. 核对实体类型和代词：hotel、city、event 等谓语指向地方/机构时，those/holders 不要默认译成“人”；them/it 先行词不明时不要擅自命名。\n"
                    "5. 将英文中的数字、时间、专名、代词、连词和程度/限定词逐个在终稿中找到对应项；尤其复核 same、too、successfully、instead、CCTs、性别和单复数。习语可自然表达，但不添加“反而、被视为、兑现、服务”等原文没有的关系或对象。\n"
                    f"6. {TRANSLATION_PRECISION_RULES}\n"
                    f"{_fidelity_focus(sentence, context_before, context_after)}"
                    "7. 最后单独做中文语法检查：结构助词、主谓搭配、介宾搭配、重复限定词和句末是否悬空。若不能指出英文中的具体依据，不为文采改写；草稿正确时原样返回。普通英文词不能残留；不输出评分、Markdown 或结构外字段。\n\n"
                    f"{feedback_note}"
                    f"{_reference_context_note(context_before, context_after)}"
                    f"<target_sentence>{sentence}</target_sentence>\n"
                    f"<translation_draft>{translation}</translation_draft>"
                ),
            },
        ],
        user_message="AI 翻译终审返回格式异常，请重试。",
        diagnostic_label="sentence review JSON",
        expected_schema='{"issues_found": [], "sentence_translation": "自然完整中文译文"}',
    )
    reviewed = str(
        payload.get("sentence_translation")
        or payload.get("natural_translation")
        or payload.get("translation")
        or ""
    ).strip()
    if not reviewed:
        raise AIProviderError("AI 翻译终审返回了空译文")
    if audit is not None:
        audit.setdefault("review_issues", []).extend(payload.get("issues_found") if isinstance(payload.get("issues_found"), list) else [])
    return reviewed


def _translate_words_only(
    sentence: str,
    words: list[str],
    *,
    feedback: str = "",
    sentence_translation: str = "",
    context_before: list[str] | tuple[str, ...] | None = None,
    context_after: list[str] | tuple[str, ...] | None = None,
) -> dict:
    if not words:
        return {"items": [], "word_translations": {}, "word_tips": {}}
    retry_feedback = str(feedback or "").strip()
    feedback_note = (
        "上一次词义结果被质量审查拒绝，原因是："
        f"{retry_feedback}。\n"
        "这次必须修正词义格式或内容。\n\n"
        if retry_feedback
        else ""
    )
    payload = _json_from_chat(
        [
            {
                "role": "system",
                "content": (
                    "你是英语学习材料的重点词释义编辑。只给目标英文中的指定单词作词卡；"
                    "相邻英文若提供，只能辅助判断该词在目标句中的含义，不得为相邻句制卡。"
                    "不讲解；只输出 JSON。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "返回 JSON：\n"
                    '{"words":[{"word":"原词","source_quote":"包含原词的连续英文原文","translation_quote":"逐字摘自中文定稿的连续原文","base_translation":"不带标签的词典义","context_translation":"不带标签的本句一项实际义","tip":""}]}\n'
                    "要求：\n"
                    "1. words 必须与给定列表完全同序、同量，不增删或改写单词拼写。\n"
                    "2. base_translation 是简洁的词典本义（可列 1—2 个常用义），context_translation 是该片段中实际义；两者都要有证据，不能把相近词、词性或不同词形混在一起。若原文词形/搭配疑似截断，词卡仍以给定原词为准，不把它静默改成另一个词。\n"
                    "3. 句中义优先看词性、搭配和指代：fashion models 是“模特”；content 不应凭感觉改成 contentment，但若 `satisfy ... need for rapid content` 这类明显截断搭配只能作最小修复，词卡要保留 content 并注明中性/疑似义；片段不足以判定时选择中性释义。\n"
                    "4. 不生成 translation 字段，程序会加上“本义：…；句中：…”标签，两个 meaning 字段不得重复这些标签。tip 只有非常确定且有助记忆时才写，20 字以内；禁止音标、重音、音节、泛泛拼读和词源故事，不确定留空。\n\n"
                    "5. source_quote 必须逐字摘自目标英文并包含给定词。若提供中文定稿，先在定稿中定位该词的实际表达，逐字摘录为 translation_quote，再写与之相符的句中义；不另选另一种解释，不把邻近名词的译义张冠李戴。功能词没有独立译词时，引用承载其功能的最短中文短语；不可修改定稿或编造引文。未提供中文定稿时 translation_quote 留空。\n"
                    "6. 本义与句中义都要保持词性和词形：名词不能解释成动作，分词要依据句内语法解释；短语整体的含义不能直接冒充其中每个单词的词义。\n\n"
                    "7. 严格按字段顺序先复制两个引文再解释，不能先编词义再杜撰引文。引文不使用省略号，不拼接分散文字；功能词无法单独摘录时扩大到原定稿完整短语或从句，仍须逐字复制。\n"
                    "8. 句中义只给本句实际采用的一义，不罗列互不相同的候选。若单词只作为固定短语组成部分起作用，写明‘用于[原短语]，整体意为…’，不要误教成这个词单独就有整段含义；例如 slot 不等于老虎机，side 不等于负面的，suit 不等于效仿。\n\n"
                    "9. 中文引文可以包含邻词，但句中义只解释给定词：不能把邻近的否定、数量、比较或中心名词吸入词义。sustainable 即使在 aren't sustainable 中也仍是可持续的，不能释成难以为继；checked-baggage 修饰 fees 时是托运行李的，不是费用。引文包含否定时，仍保持词本身的正反义，另用括号说明整段结构。\n"
                    f"整句翻译已验证的词义规则同样适用于词卡：\n{TRANSLATION_PRECISION_RULES}\n\n"
                    f"{feedback_note}"
                    f"{_reference_context_note(context_before, context_after)}"
                    f"<target_sentence>{sentence}</target_sentence>\n"
                    f"<approved_translation>{sentence_translation}</approved_translation>\n"
                    f"单词列表：{', '.join(words)}"
                ),
            },
        ],
        user_message="AI 词义返回格式异常，请重试。",
        diagnostic_label="word translation JSON",
        expected_schema='{"words":[{"word":"原词","source_quote":"连续英文原文","translation_quote":"连续中文定稿原文","base_translation":"词典义","context_translation":"本句义","tip":""}]}',
    )
    result = _normalize_translation_payload(payload, words)
    ground_word_cards(result, sentence, sentence_translation)
    result["word_evidence_required"] = True
    return result


def _merge_feedback(*parts: str) -> str:
    return "\n\n".join(str(part).strip() for part in parts if str(part or "").strip())


def _translate_verified_words(
    sentence: str,
    words: list[str],
    *,
    feedback: str = "",
    sentence_translation: str = "",
    context_before: list[str] | tuple[str, ...] | None = None,
    context_after: list[str] | tuple[str, ...] | None = None,
) -> dict:
    result = _translate_words_only(
        sentence,
        words,
        feedback=feedback,
        sentence_translation=sentence_translation,
        context_before=context_before,
        context_after=context_after,
    )
    for attempt in range(3):
        issues = word_translation_issues(result, words, source_text=sentence, sentence_translation=sentence_translation)
        if not issues:
            return result
        if attempt == 2:
            break
        affected = {issue.split(":", 2)[1] for issue in issues if ":" in issue}
        repair_words = [word for word in words if word in affected] or words
        repaired = _translate_words_only(
            sentence,
            repair_words,
            feedback=_merge_feedback(feedback, "; ".join(issues) + "。只重做这些词；中文引文可复制完整从句，但不能同义替换或添加省略号。"),
            sentence_translation=sentence_translation,
            context_before=context_before,
            context_after=context_after,
        )
        by_word = {item["word"]: item for item in result.get("items", []) if item["word"] not in repair_words}
        by_word.update({item["word"]: item for item in repaired.get("items", [])})
        result["items"] = [by_word[word] for word in words if word in by_word]
        for field in ("word_translations", "word_tips"):
            result[field] = {word: value for word, value in result.get(field, {}).items() if word not in repair_words}
            result[field].update(repaired.get(field) or {})
    raise TranslationQualityError(
        "AI 词义结果未通过本地校验，请重试。",
        "word translation validation failed: " + "; ".join(issues),
        {**result, "sentence_translation": sentence_translation},
    )


def translate_words(
    text: str,
    *,
    words: list[str] | None = None,
    feedback: str = "",
    sentence_translation: str = "",
    context_before: list[str] | tuple[str, ...] | None = None,
    context_after: list[str] | tuple[str, ...] | None = None,
) -> dict:
    """Generate missing focus-word meanings without revisiting a valid translation."""
    source_sentence = _translation_source(text)
    if not source_sentence:
        raise AIProviderError("句子不能为空")
    selected_words = _normalize_words(words, str(text or ""))
    if not selected_words:
        return {"items": [], "word_translations": {}, "word_tips": {}}

    result = _translate_verified_words(
        source_sentence,
        selected_words,
        feedback=feedback,
        sentence_translation=sentence_translation,
        context_before=context_before,
        context_after=context_after,
    )
    return {
        "items": result.get("items") or [],
        "word_translations": result.get("word_translations") or {},
        "word_tips": result.get("word_tips") or {},
    }


def _single_segment_fallback(sentence: str, result: dict[str, Any]) -> dict[str, Any]:
    fallback = dict(result)
    translation = str(result.get("sentence_translation") or "").strip()
    fallback["sentence_segments"] = _normalize_segment_list([sentence])
    fallback["translation_segments"] = [translation] if translation else []
    return fallback


def _valid_translation_candidate(sentence: str, words: list[str], result: dict[str, Any]) -> tuple[bool, str]:
    return validate_translation_result(result, words, source_text=sentence)


def _is_sentence_or_word_issue(issue: str) -> bool:
    return str(issue or "").startswith(SENTENCE_OR_WORD_ISSUE_PREFIXES)


def _segmentation_problem_set(
    result: dict[str, Any],
    words: list[str],
    *,
    source_text: str,
) -> tuple[list[str], list[str]]:
    hard = [
        issue
        for issue in translation_result_issues(result, words, source_text=source_text)
        if not _is_sentence_or_word_issue(issue)
    ]
    return hard, segmentation_advisory_issues(result, source_text=source_text)


def _segmentation_candidate_score(
    result: dict[str, Any],
    words: list[str],
    *,
    source_text: str,
) -> tuple[int, int, int]:
    hard, advisory = _segmentation_problem_set(result, words, source_text=source_text)
    segment_count = len(result.get("sentence_segments") or [])
    # Hard violations always lose.  With equal validation status, prefer the
    # candidate that resolved more under-segmentation advice, then the one that
    # offers more useful reading beats.
    return len(hard), len(advisory), -min(segment_count, 4)


def translate_text(
    text: str,
    *,
    words: list[str] | None = None,
    feedback: str = "",
    context_before: list[str] | tuple[str, ...] | None = None,
    context_after: list[str] | tuple[str, ...] | None = None,
) -> dict:
    source_sentence = _translation_source(text)
    if not source_sentence:
        raise AIProviderError("句子不能为空")
    selected_words = _normalize_words(words, str(text or ""))

    audit: dict[str, Any] = {}

    # V2 keeps semantic work separate from presentation work. The Chinese
    # sentence is locked before either word cards or reading blocks are made.
    try:
        final_translation = _translate_sentence_only(
            source_sentence,
            feedback=feedback,
            audit=audit,
            context_before=context_before,
            context_after=context_after,
        )
    except AIProviderError:
        raise
    final_translation = _review_sentence_only(
        source_sentence,
        final_translation,
        feedback=feedback,
        audit=audit,
        context_before=context_before,
        context_after=context_after,
    )
    final_translation = ground_sentence_terms(
        source_sentence,
        final_translation,
        context_before=context_before,
        context_after=context_after,
        audit=audit,
    )

    word_payload = _translate_verified_words(
        source_sentence,
        selected_words,
        feedback=feedback,
        sentence_translation=final_translation,
        context_before=context_before,
        context_after=context_after,
    )
    segment_payload = segment_translation(source_sentence, final_translation, feedback=feedback)

    def build_result() -> dict:
        return {
            "items": word_payload.get("items") or [],
            "word_translations": word_payload.get("word_translations") or {},
            "word_tips": word_payload.get("word_tips") or {},
            "word_evidence_required": word_payload.get("word_evidence_required", False),
            "sentence_translation": final_translation,
            "sentence_segments": segment_payload.get("sentence_segments") or [],
            "translation_segments": segment_payload.get("translation_segments") or [],
            "quality_audit": audit,
        }

    result = build_result()
    # Hard issues reject the candidate; advisory segmentation signals request
    # one focused retry but do not make an otherwise accurate translation fail.
    hard_issues = translation_result_issues(result, selected_words, source_text=source_sentence)
    advisory_issues = segmentation_advisory_issues(result, source_text=source_sentence)
    issues = [*hard_issues, *advisory_issues]
    if issues:
        issue_feedback = _merge_feedback(feedback, "; ".join(issues[:6]))
        if any(
            not _is_sentence_or_word_issue(issue)
            for issue in issues
        ):
            segment_payload = segment_translation(source_sentence, final_translation, feedback=issue_feedback)
        if any(
            issue.startswith(
                (
                    "empty_sentence_translation",
                    "segmented_sentence_translation",
                    "literal_translation:",
                    "question_translation_missing",
                    "sentence_translation_slash",
                )
            )
            for issue in issues
        ):
            revised_translation = _review_sentence_only(
                source_sentence,
                final_translation,
                feedback=issue_feedback,
                audit=audit,
                context_before=context_before,
                context_after=context_after,
            )
            revised_translation = ground_sentence_terms(
                source_sentence,
                revised_translation,
                context_before=context_before,
                context_after=context_after,
                audit=audit,
            )
            if revised_translation != final_translation:
                final_translation = revised_translation
                word_payload = _translate_verified_words(
                    source_sentence,
                    selected_words,
                    feedback=issue_feedback,
                    sentence_translation=final_translation,
                    context_before=context_before,
                    context_after=context_after,
                )
                # Existing Chinese blocks were made from the previous draft;
                # regenerate them so a repaired question/meaning cannot leave
                # stale block text behind.
                segment_payload = segment_translation(
                    source_sentence,
                    final_translation,
                    feedback=issue_feedback,
                )
        result = build_result()

    # A long sentence can need more than one focused correction: the first
    # retry may fix the number of blocks but introduce a bad cut or move a
    # sentence-final attribution to the wrong Chinese block. Keep the best
    # candidate and allow two cheap, segmentation-only retries before falling
    # back to one block.
    best_result = result
    best_segment_payload = segment_payload
    latest_result = result
    for _ in range(2):
        remaining_hard, remaining_advisory = _segmentation_problem_set(
            latest_result,
            selected_words,
            source_text=source_sentence,
        )
        if not remaining_hard and not remaining_advisory:
            break
        retry_segment_payload = segment_translation(
            source_sentence,
            final_translation,
            feedback=_merge_feedback(feedback, "; ".join([*remaining_hard, *remaining_advisory][:8])),
        )
        latest_result = {
            "items": word_payload.get("items") or [],
            "word_translations": word_payload.get("word_translations") or {},
            "word_tips": word_payload.get("word_tips") or {},
            "word_evidence_required": word_payload.get("word_evidence_required", False),
            "sentence_translation": final_translation,
            "sentence_segments": retry_segment_payload.get("sentence_segments") or [],
            "translation_segments": retry_segment_payload.get("translation_segments") or [],
            "quality_audit": audit,
        }
        if _segmentation_candidate_score(
            latest_result,
            selected_words,
            source_text=source_sentence,
        ) < _segmentation_candidate_score(
            best_result,
            selected_words,
            source_text=source_sentence,
        ):
            best_result = latest_result
            best_segment_payload = retry_segment_payload
    result = best_result
    segment_payload = best_segment_payload

    ok, reason = _valid_translation_candidate(source_sentence, selected_words, result)
    if ok:
        return result
    sentence_or_word_issue = any(
        _is_sentence_or_word_issue(issue)
        for issue in translation_result_issues(result, selected_words, source_text=source_sentence)
    )
    if not sentence_or_word_issue:
        # Reading blocks are supplementary presentation data. If a focused
        # segmentation request cannot satisfy the strict block rules, preserve
        # the independently validated translation and word cards as one block.
        fallback = _single_segment_fallback(source_sentence, result)
        fallback_ok, _ = _valid_translation_candidate(source_sentence, selected_words, fallback)
        if fallback_ok:
            return fallback
    raise TranslationQualityError(
        "AI 翻译结果未通过本地校验，请重试。",
        f"split translation validation failed: {reason or 'unknown'}",
        result,
    )


def segment_translation(text: str, sentence_translation: str, *, feedback: str = "") -> dict:
    """Create short, semantically aligned reading blocks.

    Verbatim bilingual end anchors avoid model token-counting errors. Legacy
    token positions remain readable for existing fixtures and saved responses.
    """
    sentence = str(text or "").strip()
    original_translation = str(sentence_translation or "").strip()
    translation = _translation_aligned_for_final_attribution(sentence, original_translation)
    retry_feedback = str(feedback or "").strip()
    if not sentence:
        raise AIProviderError("句子不能为空")
    if not original_translation:
        raise AIProviderError("整句翻译不能为空")
    if _structure_review_hint(sentence):
        return _single_segment_fallback(sentence, {"sentence_translation": original_translation})
    if (
        re.search(r"\bonly if\b", sentence, re.I)
        and not re.match(r"^only if\b", sentence, re.I)
        and re.search(r"只有.+才", translation)
    ):
        return _single_segment_fallback(sentence, {"sentence_translation": original_translation})

    source_words = SEGMENT_TOKEN_PATTERN.findall(sentence)
    if not source_words:
        return {
            "sentence_translation": original_translation,
            "sentence_segments": [sentence],
            "translation_segments": [original_translation],
        }

    feedback_note = (
        "上一次输出触发了质量提示："
        f"{retry_feedback}。只修正该提示；若提示以 undersegmented_ 开头，必须实际尝试新增安全切点，"
        "不要原样返回；只有逐项检查后仍无安全切点才保留一块。\n\n"
        if retry_feedback
        else ""
    )
    messages = [
        {
            "role": "system",
            "content": (
                "你是英汉阅读分块编辑。整句中文已确定；只设计英中对应的阅读停顿，"
                "不重新翻译。只输出 JSON，不输出解释。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"{SEGMENTATION_CONTRACT}\n\n"
                f"{feedback_note}"
                f"英文原句：{sentence}\n"
                f"既有中文译文：{translation}"
            ),
        },
    ]
    raw = translation_completion(messages, options=_english_ai_options(), completion=_chat_completion)
    if not raw:
        raise AIProviderError("AI 分块返回了空结果")
    try:
        payload = _extract_json_object(
            raw,
            user_message="AI 分块返回格式异常，请重试。",
            diagnostic_label="segment JSON",
        )
    except AIProviderError:
        payload = _repair_json_object(
            raw,
            user_message="AI 分块返回格式异常，请重试。",
            diagnostic_label="segment JSON",
            expected_schema='{"source_breaks": ["英文切点前的原文短语"], "translation_breaks": ["对应中文切点前的原文短语"]}',
        )
    anchored = _anchored_segment_payload(sentence, translation, payload)
    compact = _compact_segment_payload(sentence, payload)
    normalized = anchored or compact or _normalize_translation_payload(payload, [])
    normalized["sentence_translation"] = original_translation
    return normalized
