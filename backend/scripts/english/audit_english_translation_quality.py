from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.english.translation_quality import (  # noqa: E402
    segmentation_advisory_issues,
    stored_translation_issues,
    translation_result_issues,
)
from app.english.translator import extract_words  # noqa: E402
from app.platform.db import get_connection, rows_to_dicts  # noqa: E402


def _result(
    *,
    sentence_translation: str,
    sentence_segments: list[str],
    translation_segments: list[str],
    word_translations: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "sentence_translation": sentence_translation,
        "sentence_segments": sentence_segments,
        "translation_segments": translation_segments,
        "word_translations": word_translations or {},
        "word_tips": {},
    }


REGRESSION_CASES: list[dict[str, Any]] = [
    {
        "name": "advisory_flags_sentence_final_attribution",
        "source": (
            "We estimate that either eliminating a substantial labour-rights concern, such as child labour, "
            "or increasing corporate giving by about 20% results in fines that generally are 40% lower than "
            "the typical punishment for bribing foreign officials, says one researcher."
        ),
        "result": _result(
            sentence_translation="我们估计，消除劳工权益问题或增加企业捐赠会使罚款降低，一位研究人员说。",
            sentence_segments=[
                "We estimate that either eliminating a substantial labour-rights concern, such as child labour, or increasing corporate giving by about 20% results in fines that generally are 40% lower than the typical punishment for bribing foreign officials, says one researcher."
            ],
            translation_segments=["我们估计，消除劳工权益问题或增加企业捐赠会使罚款降低，一位研究人员说。"],
        ),
        "advisory": ["undersegmented_attribution"],
    },
    {
        "name": "does_not_treat_truncated_attribution_as_sentence_final",
        "source": "The basic compact, wrote Chief Justice Roberts for the court",
        "result": _result(
            sentence_translation="首席大法官罗伯茨代表法院写道，这项基本契约……",
            sentence_segments=["The basic compact, wrote Chief Justice Roberts for the court"],
            translation_segments=["首席大法官罗伯茨代表法院写道，这项基本契约……"],
        ),
        "expect_advisory_absent": ["undersegmented_attribution"],
    },
    {
        "name": "advisory_flags_parallel_finite_or",
        "source": (
            "According to Paragraphs 2 and 3, scientific publisher Elsevier has thrived mainly "
            "on university libraries or financed researchers generously."
        ),
        "result": _result(
            sentence_translation=(
                "根据第2段和第3段，科学出版商爱思唯尔主要依靠大学图书馆蓬勃发展，"
                "或者慷慨资助研究人员。"
            ),
            sentence_segments=[
                "According to Paragraphs 2 and 3, scientific publisher Elsevier has thrived mainly "
                "on university libraries or financed researchers generously."
            ],
            translation_segments=[
                "根据第2段和第3段，科学出版商爱思唯尔主要依靠大学图书馆蓬勃发展，"
                "或者慷慨资助研究人员。"
            ],
        ),
        "advisory": ["undersegmented_parallel_or"],
    },
    {
        "name": "rejects_front_moved_attribution_in_paired_blocks",
        "source": "The policy lowers costs, says one researcher.",
        "result": _result(
            sentence_translation="一位研究人员说，这项政策会降低成本。",
            sentence_segments=["The policy lowers costs,", "says one researcher."],
            translation_segments=["一位研究人员说，这项政策会降低成本，", "。"],
        ),
        "expect": ["sentence_final_attribution_missing_from_last_translation_segment"],
    },
    {
        "name": "rejects_bare_function_word_blocks",
        "source": "It excludes GDP as an indicator.",
        "result": _result(
            sentence_translation="它不把国内生产总值作为衡量指标。",
            sentence_segments=["It", "excludes GDP as an indicator."],
            translation_segments=["它", "不把国内生产总值作为衡量指标。"],
        ),
        "expect": ["weak_sentence_segment", "weak_translation_segment"],
    },
    {
        "name": "question_mark_is_semantic",
        "source": "According to Paragraph 2, CSR helps a company by guarding it against malpractices or protecting it from being defamed?",
        "result": _result(
            sentence_translation="根据第2段，企业社会责任通过防止不当行为或保护公司免遭诽谤来帮助公司。",
            sentence_segments=[
                "According to Paragraph 2, CSR helps a company by guarding it against malpractices or protecting it from being defamed?"
            ],
            translation_segments=["根据第2段，企业社会责任通过防止不当行为或保护公司免遭诽谤来帮助公司。"],
        ),
        "expect": ["question_translation_missing"],
    },
    {
        "name": "interrogative_syntax_requires_question_mark_even_if_source_lost_it",
        "source": "Why did most Victorians look stern in photographs",
        "result": _result(
            sentence_translation="为什么大多数维多利亚时代的人在照片中表情严肃",
            sentence_segments=["Why did most Victorians look stern in photographs"],
            translation_segments=["为什么大多数维多利亚时代的人在照片中表情严肃"],
        ),
        "expect": ["question_translation_missing"],
    },
    {
        "name": "how_much_auxiliary_requires_question_mark_when_source_lost_it",
        "source": "how much can we learn about it from neurology and genetics",
        "result": _result(
            sentence_translation="我们能从神经学和遗传学中了解到多少相关信息",
            sentence_segments=["how much can we learn about it from neurology and genetics"],
            translation_segments=["我们能从神经学和遗传学中了解到多少相关信息"],
        ),
        "expect": ["question_translation_missing"],
    },
    {
        "name": "how_much_of_subject_requires_question_mark_when_source_lost_it",
        "source": "How much of intelligence can be specified",
        "result": _result(
            sentence_translation="智力中有多少可以被明确界定",
            sentence_segments=["How much of intelligence can be specified"],
            translation_segments=["智力中有多少可以被明确界定"],
        ),
        "expect": ["question_translation_missing"],
    },
    {
        "name": "which_of_following_requires_question_mark_when_source_lost_it",
        "source": "Which of the following proverbs is closest to the message",
        "result": _result(
            sentence_translation="下列哪条谚语最接近该信息",
            sentence_segments=["Which of the following proverbs is closest to the message"],
            translation_segments=["下列哪条谚语最接近该信息"],
        ),
        "expect": ["question_translation_missing"],
    },
    {
        "name": "nominal_how_clause_is_not_forced_to_be_a_question",
        "source": "How the whole image is assembled remains a mystery.",
        "result": _result(
            sentence_translation="整幅图像如何组合起来仍是一个谜。",
            sentence_segments=["How the whole image is assembled remains a mystery."],
            translation_segments=["整幅图像如何组合起来仍是一个谜。"],
        ),
        "expect_absent": ["question_translation_missing"],
    },
    {
        "name": "truncated_who_relative_clause_is_not_forced_to_be_a_question",
        "source": "who could enter the workforce if the main earner became ill",
        "result": _result(
            sentence_translation="如果主要收入者生病，能够进入劳动力市场的人",
            sentence_segments=["who could enter the workforce if the main earner became ill"],
            translation_segments=["如果主要收入者生病，能够进入劳动力市场的人"],
        ),
        "expect_absent": ["question_translation_missing"],
    },
    {
        "name": "compact_cut_keeps_opening_quote",
        "source": '"Pathological gambling" involves risk.',
        "result": _result(
            sentence_translation="“病理性赌博”涉及风险。",
            sentence_segments=['"Pathological gambling"', "involves risk."],
            translation_segments=["“病理性赌博”", "涉及风险。"],
        ),
        "expect_absent": ["source_segment_coverage_mismatch"],
    },
    {
        "name": "rejects_conjunction_cut_ending",
        "source": "They gather all the data they can, not just performance statistics but also laboratory results.",
        "result": _result(
            sentence_translation="他们尽可能收集所有数据，不仅包括表现统计数据，也包括实验室结果。",
            sentence_segments=["They gather all the data they can, not", "just performance statistics but also laboratory results."],
            translation_segments=["他们尽可能收集所有数据，不仅", "包括表现统计数据，也包括实验室结果。"],
        ),
        "expect": ["weak_sentence_segment_ending", "weak_translation_segment_ending"],
    },
    {
        "name": "rejects_chinese_block_ending_with_yi",
        "source": "They could intervene to avoid the problem.",
        "result": _result(
            sentence_translation="他们可以介入，以避免该问题。",
            sentence_segments=["They could intervene", "to avoid the problem."],
            translation_segments=["他们可以介入，以", "避免该问题。"],
        ),
        "expect": ["bad_translation_segment_suffix"],
    },
    {
        "name": "rejects_dependent_subject_before_verb_cut",
        "source": "He had never gambled before the casino sent him a coupon.",
        "result": _result(
            sentence_translation="在赌场给他寄优惠券之前，他从未赌博。",
            sentence_segments=["He had never gambled before the casino", "sent him a coupon."],
            translation_segments=["在赌场给他寄优惠券之前，", "他从未赌博。"],
        ),
        "expect": ["dependent_subject_split_before_predicate"],
    },
    {
        "name": "rejects_numbered_pair_cut",
        "source": "According to Paragraphs 5 and 6, the policy changed.",
        "result": _result(
            sentence_translation="根据第5段和第6段，该政策发生了变化。",
            sentence_segments=["According to Paragraphs 5", "and 6, the policy changed."],
            translation_segments=["根据第5段和第6段，", "该政策发生了变化。"],
        ),
        "expect": ["numbered_pair_split"],
    },
    {
        "name": "rejects_cut_after_partial_colon_explanation",
        "source": "You will find a pattern: elite players start earlier.",
        "result": _result(
            sentence_translation="你会发现一个规律：精英运动员开始得更早。",
            sentence_segments=["You will find a pattern: elite", "players start earlier."],
            translation_segments=["你会发现一个规律：", "精英运动员开始得更早。"],
        ),
        "expect": ["cut_after_partial_colon_explanation"],
    },
    {
        "name": "flags_thought_as_background_before_was",
        "source": (
            "The thought of holding a fixed grin as the camera performed its magical duties "
            "was too much to contemplate."
        ),
        "result": _result(
            sentence_translation="一想到要在相机发挥神奇作用时保持固定的咧嘴笑，就让人难以忍受。",
            sentence_segments=[
                "The thought of holding a fixed grin as the camera performed its magical duties",
                "was too much to contemplate.",
            ],
            translation_segments=[
                "一想到要在相机发挥神奇作用时保持固定的咧嘴笑",
                "就让人难以忍受。",
            ],
        ),
        "expect": ["undersegmented_subject_background"],
    },
    {
        "name": "allows_thought_as_background_when_split",
        "source": (
            "The thought of holding a fixed grin as the camera performed its magical duties "
            "was too much to contemplate."
        ),
        "result": _result(
            sentence_translation="一想到要保持固定的咧嘴笑，在相机发挥神奇作用时，就让人难以忍受。",
            sentence_segments=[
                "The thought of holding a fixed grin",
                "as the camera performed its magical duties",
                "was too much to contemplate.",
            ],
            translation_segments=[
                "一想到要保持固定的咧嘴笑",
                "在相机发挥神奇作用时",
                "就让人难以忍受。",
            ],
        ),
        "expect_absent": ["undersegmented_subject_background"],
    },
    {
        "name": "flags_prospect_when_background_before_seemed",
        "source": (
            "The prospect of rebuilding the old local system when public support was already fading "
            "seemed unrealistic."
        ),
        "result": _result(
            sentence_translation="在公众支持已经减弱时，重建旧地方体系的前景似乎并不现实。",
            sentence_segments=[
                "The prospect of rebuilding the old local system when public support was already fading",
                "seemed unrealistic.",
            ],
            translation_segments=[
                "在公众支持已经减弱时，重建旧地方体系的前景",
                "似乎并不现实。",
            ],
        ),
        "expect": ["undersegmented_subject_background"],
    },
    {
        "name": "allows_prospect_when_background_when_split",
        "source": (
            "The prospect of rebuilding the old local system when public support was already fading "
            "seemed unrealistic."
        ),
        "result": _result(
            sentence_translation="重建旧地方体系的前景，在公众支持已经减弱时，似乎并不现实。",
            sentence_segments=[
                "The prospect of rebuilding the old local system",
                "when public support was already fading",
                "seemed unrealistic.",
            ],
            translation_segments=[
                "重建旧地方体系的前景",
                "在公众支持已经减弱时",
                "似乎并不现实。",
            ],
        ),
        "expect_absent": ["undersegmented_subject_background"],
    },
    {
        "name": "flags_problem_while_background_before_is",
        "source": (
            "The problem of measuring social progress while economic life keeps changing "
            "is more difficult than it first appears."
        ),
        "result": _result(
            sentence_translation="在经济生活不断变化时衡量社会进步的问题，比最初看起来更难。",
            sentence_segments=[
                "The problem of measuring social progress while economic life keeps changing",
                "is more difficult than it first appears.",
            ],
            translation_segments=[
                "在经济生活不断变化时衡量社会进步的问题",
                "比最初看起来更难。",
            ],
        ),
        "expect": ["undersegmented_subject_background"],
    },
    {
        "name": "does_not_force_short_background_split",
        "source": "The idea as a whole is useful.",
        "result": _result(
            sentence_translation="这个想法整体上是有用的。",
            sentence_segments=["The idea as a whole", "is useful."],
            translation_segments=["这个想法整体上", "是有用的。"],
        ),
        "expect_absent": ["undersegmented_subject_background"],
    },
    {
        "name": "rejects_cut_after_such_determiner",
        "source": "If left alone, such trends will continue.",
        "result": _result(
            sentence_translation="如果任其发展，这些趋势将会继续。",
            sentence_segments=["If left alone, such", "trends will continue."],
            translation_segments=["如果任其发展，这些", "趋势将会继续。"],
        ),
        "expect": ["weak_sentence_segment_ending"],
    },
    {
        "name": "rejects_short_direct_quote_split",
        "source": 'They were discouraged from saying "I have no idea."',
        "result": _result(
            sentence_translation="应劝他们不要说“我不知道”。",
            sentence_segments=['They were discouraged from saying "', 'I have no idea."'],
            translation_segments=["应劝他们不要说", "“我不知道”。"],
        ),
        "expect": ["short_direct_quote_split"],
        "expect_advisory_absent": ["undersegmented_multiple_sentences"],
    },
    {
        "name": "rejects_trailing_time_modifier_chinese_block",
        "source": "Most immigrants spoke English well after ten years of residence.",
        "result": _result(
            sentence_translation="大多数移民在居住十年后都能说好英语。",
            sentence_segments=["Most immigrants spoke English well", "after ten years of residence."],
            translation_segments=["大多数移民都能说好英语，", "在居住十年后。"],
        ),
        "expect": ["trailing_modifier_translation_segment"],
    },
    {
        "name": "rejects_segmenter_retranslation",
        "source": "The policy caused a serious problem.",
        "result": _result(
            sentence_translation="这项政策造成了一个严重问题。",
            sentence_segments=["The policy", "caused a serious problem."],
            translation_segments=["这一政策", "引发了严重问题。"],
        ),
        "expect": ["translation_segment_content_mismatch"],
    },
    {
        "name": "allows_opening_born_background_block",
        "source": "Born during the crisis, many leaders supported representative government.",
        "result": _result(
            sentence_translation="许多领导人诞生于危机时期，并支持代议制政府。",
            sentence_segments=["Born during the crisis,", "many leaders supported representative government."],
            translation_segments=["诞生于危机时期，", "许多领导人支持代议制政府。"],
        ),
        "expect_absent": ["standalone_born_modifier"],
    },
    {
        "name": "allows_abbreviations_without_multiple_sentence_advice",
        "source": "Dr. Worm works at a major U. S. university.",
        "result": _result(
            sentence_translation="沃姆博士在美国一所重要大学任职。",
            sentence_segments=["Dr. Worm works at a major U. S. university."],
            translation_segments=["沃姆博士在美国一所重要大学任职。"],
        ),
        "expect_advisory_absent": ["undersegmented_multiple_sentences"],
    },
    {
        "name": "allows_noun_alternatives_without_parallel_predicate_advice",
        "source": "The plan supports unemployment insurance or disability insurance for families.",
        "result": _result(
            sentence_translation="该计划为家庭提供失业保险或伤残保险支持。",
            sentence_segments=["The plan supports unemployment insurance or disability insurance for families."],
            translation_segments=["该计划为家庭提供失业保险或伤残保险支持。"],
        ),
        "expect_advisory_absent": ["undersegmented_parallel_or"],
    },
    {
        "name": "allows_final_noun_that_looks_like_predicate",
        "source": "Countries adopted new international tax provisions.",
        "result": _result(
            sentence_translation="各国通过了新的国际税收规定。",
            sentence_segments=["Countries adopted", "new international tax provisions."],
            translation_segments=["各国通过了", "新的国际税收规定。"],
        ),
        "expect_absent": ["bad_translation_segment_suffix"],
    },
    {
        "name": "rejects_attribution_verb_speaker_split",
        "source": "The principle matters, wrote Chief Justice Roberts.",
        "result": _result(
            sentence_translation="首席大法官罗伯茨写道，这项原则很重要。",
            sentence_segments=["The principle matters, wrote", "Chief Justice Roberts."],
            translation_segments=["这项原则很重要，", "首席大法官罗伯茨写道。"],
        ),
        "expect": ["attribution_verb_speaker_split"],
    },
    {
        "name": "rejects_time_range_moved_to_earlier_chinese_block",
        "source": "The event welcomed thousands of people over nearly two decades before closing.",
        "result": _result(
            sentence_translation="这项活动在近二十年间吸引了数千人，随后停办。",
            sentence_segments=[
                "The event welcomed thousands of people",
                "over nearly two decades before closing.",
            ],
            translation_segments=["这项活动在近二十年间吸引了数千人，", "随后停办。"],
        ),
        "expect": ["temporal_meaning_moved_to_earlier_translation_segment"],
    },
    {
        "name": "rejects_subject_left_after_long_opening_clause",
        "source": (
            "Whatever inborn differences two people may exhibit in their abilities to memorize, "
            "those differences are swamped by encoding."
        ),
        "result": _result(
            sentence_translation="无论两人的记忆能力有何先天差异，这些差异都会被编码效果掩盖。",
            sentence_segments=[
                "Whatever inborn differences two people may exhibit in their abilities to memorize, those differences",
                "are swamped by encoding.",
            ],
            translation_segments=["无论两人的记忆能力有何先天差异，", "这些差异都会被编码效果掩盖。"],
        ),
        "expect": ["short_subject_split_before_predicate"],
    },
    {
        "name": "rejects_short_six_word_subject_before_predicate",
        "source": "The defining characteristic of IQ tests has changed.",
        "result": _result(
            sentence_translation="智商测试的核心特征已经改变。",
            sentence_segments=["The defining characteristic of IQ tests", "has changed."],
            translation_segments=["智商测试的核心特征", "已经改变。"],
        ),
        "expect": ["short_subject_split_before_predicate"],
    },
    {
        "name": "rejects_not_obvious_how_boundary",
        "source": "It's not obvious how this capacity helps people.",
        "result": _result(
            sentence_translation="尚不清楚这种能力如何帮助人们。",
            sentence_segments=["It's not obvious", "how this capacity helps people."],
            translation_segments=["尚不清楚，", "这种能力如何帮助人们。"],
        ),
        "expect": ["required_phrase_split"],
    },
    {
        "name": "rejects_answer_questions_boundary",
        "source": "This capacity enables one to answer questions that puzzled philosophers.",
        "result": _result(
            sentence_translation="这种能力使人能够回答令哲学家困惑的问题。",
            sentence_segments=["This capacity enables one to answer", "questions that puzzled philosophers."],
            translation_segments=["这种能力使人能够回答", "令哲学家困惑的问题。"],
        ),
        "expect": ["required_phrase_split"],
    },
    {
        "name": "allows_long_completed_either_or_subject",
        "source": (
            "Either eliminating a substantial labour-rights concern such as child labour or increasing "
            "corporate giving by about 20% results in lower fines."
        ),
        "result": _result(
            sentence_translation="无论是消除童工等重大劳工权益问题，还是将企业捐赠增加约20%，都会使罚款降低。",
            sentence_segments=[
                "Either eliminating a substantial labour-rights concern such as child labour or increasing corporate giving by about 20%",
                "results in lower fines.",
            ],
            translation_segments=["无论是消除童工等重大劳工权益问题，还是将企业捐赠增加约20%，", "都会使罚款降低。"],
        ),
        "expect_absent": ["short_subject_split_before_predicate"],
    },
    {
        "name": "allows_complete_attribution_before_new_sentence",
        "source": "It was seen as a blunder, he said. The move was foresighted.",
        "result": _result(
            sentence_translation="他说，这被视为失误。这个举措很有远见。",
            sentence_segments=["It was seen as a blunder, he said.", "The move was foresighted."],
            translation_segments=["他说，这被视为失误。", "这个举措很有远见。"],
        ),
        "expect_absent": ["incomplete_sentence_segment_suffix", "attribution_verb_speaker_split"],
    },
    {
        "name": "allows_complete_clause_before_including_modifier",
        "source": (
            "Oxytocin promotes attachment in relationships, including that between mothers and babies."
        ),
        "result": _result(
            sentence_translation="催产素促进关系中的依恋，包括母亲与婴儿之间的依恋。",
            sentence_segments=[
                "Oxytocin promotes attachment in relationships,",
                "including that between mothers and babies.",
            ],
            translation_segments=["催产素促进关系中的依恋，", "包括母亲与婴儿之间的依恋。"],
        ),
        "expect_absent": ["dependent_subject_split_before_predicate"],
    },
    {
        "name": "rejects_nested_place_to_sleep_shelter_phrase",
        "source": "They found a shelter that gives them meals and a place to sleep.",
        "result": _result(
            sentence_translation="他们找到一个为他们提供饭食和睡觉的地方的收容所。",
            sentence_segments=["They found a shelter that gives them meals and a place to sleep."],
            translation_segments=["他们找到一个为他们提供饭食和睡觉的地方的收容所。"],
        ),
        "expect": ["literal_translation"],
    },
    {
        "name": "rejects_lower_risk_increase_collocation",
        "source": "Hugging protects people from the increased risk for colds.",
        "result": _result(
            sentence_translation="拥抱能降低人们的感冒风险上升。",
            sentence_segments=["Hugging protects people from the increased risk for colds."],
            translation_segments=["拥抱能降低人们的感冒风险上升。"],
        ),
        "expect": ["literal_translation"],
    },
    {
        "name": "rejects_promise_came_slowly_literal_collocation",
        "source": "Promises to end the tax came much slower.",
        "result": _result(
            sentence_translation="终止该税的承诺来得慢得多。",
            sentence_segments=["Promises to end the tax came much slower."],
            translation_segments=["终止该税的承诺来得慢得多。"],
        ),
        "expect": ["literal_translation"],
    },
    {
        "name": "rejects_two_paycheck_status_as_possessing_a_limit",
        "source": "Families budgeted to the limits of their new two-paycheck status.",
        "result": _result(
            sentence_translation="家庭把预算安排到了新形成的双收入状态的极限。",
            sentence_segments=["Families budgeted to the limits of their new two-paycheck status."],
            translation_segments=["家庭把预算安排到了新形成的双收入状态的极限。"],
        ),
        "expect": ["literal_translation"],
    },
    {
        "name": "rejects_one_parent_as_plural_parent_noun",
        "source": "the odds of having a weak elderly parent",
        "result": _result(
            sentence_translation="有一位年老体弱的父母的几率",
            sentence_segments=["the odds of having a weak elderly parent"],
            translation_segments=["有一位年老体弱的父母的几率"],
        ),
        "expect": ["literal_translation"],
    },
    {
        "name": "rejects_swamped_by_how_well_literal_structure",
        "source": "Those differences are swamped by how well each person encodes the information.",
        "result": _result(
            sentence_translation="那些差异会被每个人对信息“编码”得有多好远远盖过。",
            sentence_segments=["Those differences are swamped by how well each person encodes the information."],
            translation_segments=["那些差异会被每个人对信息“编码”得有多好远远盖过。"],
        ),
        "expect": ["literal_translation"],
    },
    {
        "name": "rejects_discourage_from_without_negative_purpose",
        "source": "They should be discouraged from saying that.",
        "result": _result(
            sentence_translation="应劝阻他们说那句话。",
            sentence_segments=["They should be discouraged from saying that."],
            translation_segments=["应劝阻他们说那句话。"],
        ),
        "expect": ["literal_translation"],
    },
    {
        "name": "rejects_most_recent_as_latest_majority",
        "source": "By most recent measures, output has risen.",
        "result": _result(
            sentence_translation="按最新的大多数指标来看，产出有所上升。",
            sentence_segments=["By most recent measures, output has risen."],
            translation_segments=["按最新的大多数指标来看，产出有所上升。"],
        ),
        "expect": ["literal_translation"],
    },
    {
        "name": "rejects_praise_for_as_praising_the_reason_object",
        "source": "He praised the UK for its GDP.",
        "result": _result(
            sentence_translation="他赞扬英国的GDP。",
            sentence_segments=["He praised the UK for its GDP."],
            translation_segments=["他赞扬英国的GDP。"],
        ),
        "expect": ["literal_translation"],
    },
    {
        "name": "rejects_basis_possibilities_as_environment_consequences",
        "source": "It gives them a basis for planning to meet the possibilities of a different environment.",
        "result": _result(
            sentence_translation="它为规划如何应对不同环境所带来的各种可能性提供依据。",
            sentence_segments=["It gives them a basis for planning to meet the possibilities of a different environment."],
            translation_segments=["它为规划如何应对不同环境所带来的各种可能性提供依据。"],
        ),
        "expect": ["literal_translation"],
    },
    {
        "name": "rejects_middle_class_family_split",
        "source": "Demographics are working against the middle class family.",
        "result": _result(
            sentence_translation="人口结构正对中产阶级家庭不利。",
            sentence_segments=["Demographics are working against the middle class", "family."],
            translation_segments=["人口结构正对中产阶级", "家庭不利。"],
        ),
        "expect": ["required_phrase_split"],
    },
    {
        "name": "rejects_acceleration_of_split",
        "source": "It looks like a frightening acceleration of the shift in risk.",
        "result": _result(
            sentence_translation="这像是风险转移的可怕加速。",
            sentence_segments=["It looks like a frightening acceleration", "of the shift in risk."],
            translation_segments=["这像是一种可怕加速", "风险转移的。"],
        ),
        "expect": ["required_phrase_split"],
    },
    {
        "name": "rejects_too_adjective_to_split",
        "source": "The salary seems too small to satisfy that need.",
        "result": _result(
            sentence_translation="这份工资似乎太低，无法满足那一需求。",
            sentence_segments=["The salary seems too small", "to satisfy that need."],
            translation_segments=["这份工资似乎太低，", "无法满足那一需求。"],
        ),
        "expect": ["required_phrase_split"],
    },
    {
        "name": "rejects_struck_terror_split",
        "source": "The campaign struck terror into local parties.",
        "result": _result(
            sentence_translation="这场运动让当地政党感到恐慌。",
            sentence_segments=["The campaign struck", "terror into local parties."],
            translation_segments=["这场运动", "让当地政党感到恐慌。"],
        ),
        "expect": ["required_phrase_split"],
    },
    {
        "name": "rejects_need_for_actor_to_split",
        "source": "The ruling reinforces the need for citizens, not courts, to ensure equal access.",
        "result": _result(
            sentence_translation="该裁决强化了由公民而非法院确保平等接触的必要性。",
            sentence_segments=[
                "The ruling reinforces the need for citizens, not courts,",
                "to ensure equal access.",
            ],
            translation_segments=["该裁决强化了由公民而非法院", "确保平等接触的必要性。"],
        ),
        "expect": ["required_phrase_split"],
    },
    {
        "name": "rejects_end_any_object_split",
        "source": "The analysis should end any self-contentedness.",
        "result": _result(
            sentence_translation="该分析应当终结任何自满情绪。",
            sentence_segments=["The analysis should end", "any self-contentedness."],
            translation_segments=["该分析应当终结", "任何自满情绪。"],
        ),
        "expect": ["required_phrase_split"],
    },
    {
        "name": "rejects_ought_not_split",
        "source": "The success ought not to be confined to cities.",
        "result": _result(
            sentence_translation="这项成功不应局限于城市。",
            sentence_segments=["The success ought", "not to be confined to cities."],
            translation_segments=["这项成功", "不应局限于城市。"],
        ),
        "expect": ["required_phrase_split"],
    },
    {
        "name": "rejects_at_a_time_when_split",
        "source": "Profits rose at a time when publishing was in crisis.",
        "result": _result(
            sentence_translation="利润上升时，出版业正陷入危机。",
            sentence_segments=["Profits rose at a time", "when publishing was in crisis."],
            translation_segments=["利润上升，", "而此时出版业正陷入危机。"],
        ),
        "expect": ["required_phrase_split"],
    },
    {
        "name": "rejects_the_fact_that_split",
        "source": "He alluded to the fact that mouths were unhealthy.",
        "result": _result(
            sentence_translation="他暗指口腔当时并不健康这一事实。",
            sentence_segments=["He alluded to the fact", "that mouths were unhealthy."],
            translation_segments=["他暗指这一事实：", "口腔当时并不健康。"],
        ),
        "expect": ["required_phrase_split"],
    },
    {
        "name": "rejects_copula_complement_split",
        "source": "Exactly when it will happen is a matter of debate.",
        "result": _result(
            sentence_translation="它究竟何时发生仍有争议。",
            sentence_segments=["Exactly when it will happen is", "a matter of debate."],
            translation_segments=["它究竟何时发生，", "仍有争议。"],
        ),
        "expect": ["copula_or_auxiliary_split"],
    },
    {
        "name": "rejects_passive_auxiliary_split",
        "source": "These actions were captured by a Latin phrase.",
        "result": _result(
            sentence_translation="这些行动被一个拉丁语短语概括。",
            sentence_segments=["These actions were", "captured by a Latin phrase."],
            translation_segments=["这些行动", "被一个拉丁语短语概括。"],
        ),
        "expect": ["copula_or_auxiliary_split"],
    },
    {
        "name": "allows_that_is_discourse_marker",
        "source": "That is, the rule applies to every firm.",
        "result": _result(
            sentence_translation="也就是说，该规则适用于每家公司。",
            sentence_segments=["That is,", "the rule applies to every firm."],
            translation_segments=["也就是说，", "该规则适用于每家公司。"],
        ),
        "expect_absent": ["copula_or_auxiliary_split"],
    },
    {
        "name": "rejects_trailing_while_connector",
        "source": "Labour is provided free, while huge profits are made.",
        "result": _result(
            sentence_translation="劳动是无偿提供的，而企业赚取巨额利润。",
            sentence_segments=["Labour is provided free, while", "huge profits are made."],
            translation_segments=["劳动是无偿提供的，", "而企业赚取巨额利润。"],
        ),
        "expect": ["weak_sentence_segment_ending"],
    },
    {
        "name": "rejects_relative_where_connector_split",
        "source": "Some remains in the brain, where it influences mood.",
        "result": _result(
            sentence_translation="有一些留在大脑中，并在那里影响情绪。",
            sentence_segments=["Some remains in the brain, where", "it influences mood."],
            translation_segments=["有一些留在大脑中，", "并在那里影响情绪。"],
        ),
        "expect": ["weak_sentence_segment_ending"],
    },
    {
        "name": "rejects_like_example_as_standalone_block",
        "source": "People who scored highly for negative emotions like anxiety looked away.",
        "result": _result(
            sentence_translation="焦虑等负面情绪得分较高的人会移开视线。",
            sentence_segments=[
                "People who scored highly for negative emotions",
                "like anxiety looked away.",
            ],
            translation_segments=["焦虑等负面情绪得分较高的人", "会移开视线。"],
        ),
        "expect": ["standalone_modifier_segment"],
    },
    {
        "name": "allows_like_comparison_with_its_own_clause",
        "source": "Health remains; like the sun behind a cloud, it can be hidden.",
        "result": _result(
            sentence_translation="健康依然存在；它就像云后的太阳，可能会被遮住。",
            sentence_segments=[
                "Health remains;",
                "like the sun behind a cloud, it can be hidden.",
            ],
            translation_segments=["健康依然存在；", "它就像云后的太阳，可能会被遮住。"],
        ),
        "expect_absent": ["standalone_modifier_segment"],
    },
    {
        "name": "rejects_short_subject_with_parenthetical_before_rely",
        "source": "The measures, however, rely too much on punishment.",
        "result": _result(
            sentence_translation="然而，这些措施过于依赖惩罚。",
            sentence_segments=["The measures, however,", "rely too much on punishment."],
            translation_segments=["然而，这些措施", "过于依赖惩罚。"],
        ),
        "expect": ["short_subject_split_before_predicate"],
    },
    {
        "name": "rejects_opening_modifier_and_subject_before_admitted",
        "source": "In signing the measure, Governor Brown admitted that it was flawed.",
        "result": _result(
            sentence_translation="在签署该措施时，布朗州长承认它存在缺陷。",
            sentence_segments=["In signing the measure, Governor Brown", "admitted that it was flawed."],
            translation_segments=["在签署该措施时，布朗州长", "承认它存在缺陷。"],
        ),
        "expect": ["short_subject_split_before_predicate"],
    },
    {
        "name": "advisory_flags_internal_whereas_contrast",
        "source": (
            "The study concludes that whereas prosecutors should evaluate a case on its merits, "
            "they seem to be influenced by a company's record."
        ),
        "result": _result(
            sentence_translation="研究认为，检察官本应根据案件本身评估，但似乎受公司记录影响。",
            sentence_segments=[
                "The study concludes that whereas prosecutors should evaluate a case on its merits, "
                "they seem to be influenced by a company's record."
            ],
            translation_segments=["研究认为，检察官本应根据案件本身评估，但似乎受公司记录影响。"],
        ),
        "advisory": ["undersegmented_contrast_clause"],
    },
    {
        "name": "advisory_flags_dash_explanation",
        "source": (
            "That demand has been almost impossible to fill—in part because of pushback "
            "from providers and the courts."
        ),
        "result": _result(
            sentence_translation="该需求几乎无法得到满足，部分原因是供应商和法院的反对。",
            sentence_segments=[
                "That demand has been almost impossible to fill—in part because of pushback "
                "from providers and the courts."
            ],
            translation_segments=["该需求几乎无法得到满足，部分原因是供应商和法院的反对。"],
        ),
        "advisory": ["undersegmented_dash_explanation"],
    },
    {
        "name": "advisory_flags_long_sentence_with_opening_time_context",
        "source": (
            "Last Thursday, the senate passed a digital services tax, which would impose a new levy "
            "on large companies providing services to users in the country."
        ),
        "result": _result(
            sentence_translation="上周四，参议院通过了数字服务税，将对向该国用户提供服务的大公司征收新税。",
            sentence_segments=[
                "Last Thursday, the senate passed a digital services tax, which would impose a new levy "
                "on large companies providing services to users in the country."
            ],
            translation_segments=["上周四，参议院通过了数字服务税，将对向该国用户提供服务的大公司征收新税。"],
        ),
        "advisory": ["undersegmented_opening_context"],
    },
    {
        "name": "advisory_does_not_treat_in_all_as_time_context",
        "source": (
            "In all, the study concludes that prosecutors should evaluate each case on its merits "
            "and should record their reasons carefully for later independent review."
        ),
        "result": _result(
            sentence_translation="总的来说，研究认为检察官应根据案情评估案件，并认真记录理由以供日后独立审查。",
            sentence_segments=[
                "In all, the study concludes that prosecutors should evaluate each case on its merits "
                "and should record their reasons carefully for later independent review."
            ],
            translation_segments=["总的来说，研究认为检察官应根据案情评估案件，并认真记录理由以供日后独立审查。"],
        ),
        "expect_advisory_absent": ["undersegmented_opening_context"],
    },
    {
        "name": "advisory_flags_long_paired_dash_parenthetical",
        "source": (
            "The team analyzed satellite data showing annual forest loss from 2008 to 2012—"
            "including during the program's introduction—in thousands of villages across the country."
        ),
        "result": _result(
            sentence_translation="团队分析了卫星数据，其中包括项目推行期间全国数千个村庄的年度森林损失。",
            sentence_segments=[
                "The team analyzed satellite data showing annual forest loss from 2008 to 2012—"
                "including during the program's introduction—in thousands of villages across the country."
            ],
            translation_segments=["团队分析了卫星数据，其中包括项目推行期间全国数千个村庄的年度森林损失。"],
        ),
        "advisory": ["undersegmented_dash_parenthetical"],
    },
    {
        "name": "advisory_flags_coordinated_pronoun_clause",
        "source": (
            "Customers would get the product they favor, the idea goes, and they would feel "
            "that they were sustaining its quality."
        ),
        "result": _result(
            sentence_translation="这种说法认为，顾客会得到偏爱的产品，并觉得自己在维持它的品质。",
            sentence_segments=[
                "Customers would get the product they favor, the idea goes, and they would feel "
                "that they were sustaining its quality."
            ],
            translation_segments=["这种说法认为，顾客会得到偏爱的产品，并觉得自己在维持它的品质。"],
        ),
        "advisory": ["undersegmented_coordinated_clause"],
    },
]


def _has_issue(issues: list[str], expected: str) -> bool:
    return any(issue == expected or issue.startswith(f"{expected}:") for issue in issues)


def run_regressions() -> int:
    failures: list[dict[str, Any]] = []
    for case in REGRESSION_CASES:
        issues = translation_result_issues(case["result"], [], source_text=case["source"])
        for expected in case.get("expect", []):
            if not _has_issue(issues, expected):
                failures.append({"case": case["name"], "missing": expected, "issues": issues})
        for absent in case.get("expect_absent", []):
            if _has_issue(issues, absent):
                failures.append({"case": case["name"], "unexpected": absent, "issues": issues})
        for expected in case.get("advisory", []):
            advisory = segmentation_advisory_issues(case["result"], source_text=case["source"])
            if not _has_issue(advisory, expected):
                failures.append({"case": case["name"], "missing_advisory": expected, "advisory": advisory})
        for absent in case.get("expect_advisory_absent", []):
            advisory = segmentation_advisory_issues(case["result"], source_text=case["source"])
            if _has_issue(advisory, absent):
                failures.append({"case": case["name"], "unexpected_advisory": absent, "advisory": advisory})
    if failures:
        print(json.dumps({"ok": False, "failures": failures}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"ok": True, "checked": len(REGRESSION_CASES)}, ensure_ascii=False))
    return 0


def _load_long_sentence_rows(limit: int) -> list[dict[str, Any]]:
    with get_connection() as conn:
        column_rows = conn.execute("PRAGMA table_info(english_sentences)").fetchall()
        columns = {str(row["name"]) for row in column_rows}
        required = {
            "text",
            "sentence_translation",
            "sentence_segments_json",
            "translation_segments_json",
            "word_translations_json",
            "word_tips_json",
        }
        missing = sorted(required - columns)
        if missing:
            raise RuntimeError(f"english_sentences schema is missing columns: {', '.join(missing)}")
        return rows_to_dicts(
            conn.execute(
                """
                SELECT id, text, sentence_translation, sentence_segments_json, translation_segments_json,
                       word_translations_json, word_tips_json
                FROM english_sentences
                WHERE COALESCE(deleted_at, '') = ''
                  AND COALESCE(sentence_translation, '') <> ''
                  AND COALESCE(sentence_segments_json, '[]') NOT IN ('', '[]')
                  AND LENGTH(text) >= 120
                ORDER BY id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        )


def scan_db(limit: int) -> int:
    try:
        rows = _load_long_sentence_rows(limit)
    except RuntimeError as exc:
        print(json.dumps({"checked": 0, "skipped": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    issue_counts: Counter[str] = Counter()
    advisory_counts: Counter[str] = Counter()
    issue_rows: list[dict[str, Any]] = []
    for row in rows:
        words = extract_words(str(row.get("text") or ""))
        issues = stored_translation_issues(row, words)
        advisory = segmentation_advisory_issues(
            {
                "sentence_segments": json.loads(row.get("sentence_segments_json") or "[]"),
                "translation_segments": json.loads(row.get("translation_segments_json") or "[]"),
            },
            source_text=str(row.get("text") or ""),
        )
        for issue in issues:
            issue_counts[issue.split(":", 1)[0]] += 1
        for issue in advisory:
            advisory_counts[issue.split(":", 1)[0]] += 1
        if issues or advisory:
            issue_rows.append(
                {
                    "id": row["id"],
                    "issues": issues[:8],
                    "advisory": advisory[:8],
                    "text": str(row.get("text") or "")[:220],
                }
            )
    print(
        json.dumps(
            {
                "checked": len(rows),
                "issue_rows": len(issue_rows),
                "issue_counts": dict(issue_counts.most_common()),
                "advisory_counts": dict(advisory_counts.most_common()),
                "samples": issue_rows[:10],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if issue_rows else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit English translation quality rules without calling AI.")
    parser.add_argument("--scan-db", action="store_true", help="Scan stored long English sentence translations.")
    parser.add_argument("--limit", type=int, default=30, help="Maximum stored rows to scan with --scan-db.")
    args = parser.parse_args()

    regression_status = run_regressions()
    if args.scan_db:
        db_status = scan_db(max(1, args.limit))
        raise SystemExit(regression_status or db_status)
    raise SystemExit(regression_status)


if __name__ == "__main__":
    main()
