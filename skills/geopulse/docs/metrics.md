# GeoPulse v2 指标字典

## 1. 有效样本与实体判定

设一次预期样本为 `prompt_item × engine × round`。Provider 样本只有同时满足以下条件才进入有效集合 `V`：

- `answer.status == "succeeded"`；
- `raw_text` 非空；
- Provider 未标为空回答或截断回答。

Consumer Web 使用 `succeeded_nonempty_evidence_v1`：除成功处理和非空原文外，还必须完成不可变提交，并保留通过 bytes/hash/size/magic 校验的有效截图及一致的实际页面/冻结上下文。该规则同时适用于人工与授权浏览器采集；自动任务的原文、截图、HTML、引用和上下文必须在同一事务提交。只有完整提交且处理成功才持久化 `valid_sample=1`。

失败、取消、空、截断、排队和执行中样本不进入 `V`，也不能解释成“未提及”。无有效样本时页面和报告写“无法诊断”，而不是输出业务上的 0%。

实体 observation 只有满足以下条件才是有效提及：

```text
entity_status = confirmed AND mentioned = true
```

`unknown / ambiguous / wrong_entity` 不进入有效提及、推荐或 SoV。`candidate` 角色不进入正式竞品池。

有效推荐还要求：

```text
depth = recommended AND sentiment != negative
```

Top Choice 必须同时是有效推荐且 `top_choice=true`。

## 2. 聚合单元与冻结权重

主聚合单元是：

```text
g = canonical_intent_id × engine_config_id
```

同一 intent 的多个自然表述和多轮回答先在 `g` 内聚合。Wave 创建时保存 `stratum_weights`，查找顺序为：

1. canonical intent 权重；
2. dimension 权重；
3. query_type 权重；
4. 默认 1。

权重小于 0 时按 0 处理；总权重为 0 时加权值为 0。冻结后不能因结果不理想而调整。

## 3. 比率、原始计数与 Wilson 区间

比率结构统一返回：

```json
{
  "hits": 3,
  "n": 8,
  "value": 37.5,
  "ci_low": 13.68,
  "ci_high": 69.43,
  "limited": true
}
```

`hits/n` 是未加权原始计数；`value` 在主 Coverage、推荐覆盖、北极星和 SoV 中可以是冻结权重聚合值。因此使用非 1 权重时，`value` 不必等于 `hits/n×100`，两者不可混写成一个公式。

默认阈值为 `n<30` 小样本。小样本只展示原始计数、区间和方向，不用颜色暗示确定胜负。

Wilson score interval：

```text
p = hits / n
z = 1.959963984540054（默认 95%）
denominator = 1 + z²/n
center = (p + z²/(2n)) / denominator
margin = z × sqrt((p(1-p) + z²/(4n))/n) / denominator
CI = [max(0, center-margin), min(1, center+margin)]
```

`n=0` 时当前实现返回 value=0、CI=[0,0]，同时保留无有效样本限制。这对空集合是占位显示，不是业务零值结论。

## 4. 主指标

### 4.1 意图覆盖率 Coverage

某组有效命中：

```text
covered(g) = 1，当组内至少一轮主品牌 confirmed mentioned；否则 0
```

主指标：

```text
Coverage = Σ(weight(g) × covered(g)) / Σweight(g) × 100%
```

原始计数为 `covered 组数 / 有效组数`。四维和引擎下钻使用各自子集的未加权原始组计数。

### 4.2 稳定命中率 Hit Rate

```text
Hit Rate = 主品牌 confirmed mentioned 的有效回答数 / 有效回答数 × 100%
```

它按有效轮次计算，与 Coverage 的“同 intent 至少一轮命中”不同。失败或缺失轮次不补成未命中。

### 4.3 推荐覆盖率 Recommendation Coverage

某组 `recommended_covered(g)=1`，当组内至少一轮主品牌是有效推荐。之后使用与 Coverage 相同的组和冻结权重聚合。

### 4.4 有效推荐率 Effective Recommendation Rate

```text
有效推荐回答数 / 全部有效回答数 × 100%
```

负面、劝退和对比败者不能算有效推荐。

### 4.5 北极星 North Star

只保留同时满足以下条件的组：

- `query_type=discovery`；
- `priority>=4`；
- `eligibility ∈ {eligible, client_confirmed}`。

然后对 `recommended_covered(g)` 使用相同冻结权重聚合。导航型品牌词不能混入抬高北极星。

### 4.6 Top Choice Rate

```text
同时满足有效推荐和 top_choice 的回答数 / 全部有效回答数 × 100%
```

### 4.7 负面风险率 Negative Risk Rate

```text
主品牌 confirmed mentioned 且 sentiment=negative 的回答数
──────────────────────────────────────────────
主品牌 confirmed mentioned 的有效回答数
```

分母不是全部回答。没有有效提及时不能解读成“品牌没有负面风险”。

## 5. 声量份额 SoV

对每条有效回答 `a`，设其中 confirmed mentioned 的正式实体数为 `C(a)`。实体 `e` 在该回答中的份额为：

```text
share(e,a) = 1/C(a)，当 e 在该回答 confirmed mentioned；否则 0
```

没有 confirmed 实体的回答对全部实体贡献 0，不为任何品牌补分母。随后：

1. 在 intent×engine 组内按有效回答平均；
2. 用同一组冻结权重跨组加权平均。

主品牌和每个竞品使用完全相同的组集合、有效回答集合和权重，不能一个按原始回答平均、另一个按 intent 平均。`competitors` 中主品牌行的 SoV 应与 `share_of_voice.value` 一致。

SoV 只表示本次冻结实体池内的相对提及份额，不是全市场真实声量。

## 6. 来源引用率与来源结构

仅当整个 Wave 都是 `search` 模式时计算：

```text
Citation Rate = 主品牌 confirmed mentioned 且关联至少一个白名单 citation URL 的回答数
                / 全部有效回答数
```

Memory 模式返回 `citation_rate=null`，页面明确“不计算来源引用率”，不能显示虚构的 0% 或引用 URL。

来源结构按 `source_type × domain × entity_role` 汇总引用数和去重来源数。分类支持官网、百科、UGC、新闻、行业、研报、投诉和其他。项目设置以规范化 hostname 配置域名类别，只默认应用于之后写入的 Citation，不静默改写历史来源或旧报告。Provider 引用为 `origin=provider_returned`；人工实际看到的页面引用为 `origin=manual_page`，授权浏览器从当前回答区域提取的引用为 `origin=browser_page`。两类页面引用只记录页面实际展示的 URL、标题和卡片文本，不自动访问 URL，也不宣称已核验正文与主张的支持关系。报告统一称为 Consumer Web 页面引用，同时保留冻结采集方法，不与 Provider 来源混称。

## 7. 数据质量

| 字段 | 定义 |
|---|---|
| `expected_samples` | 本次 Run 的全部预期样本 |
| `valid_samples` | 有效回答数 |
| `failed_samples` | 失败样本数 |
| `cancelled_samples` | 取消样本数 |
| `valid_sample_rate` | 有效回答 / 预期样本 |
| `entity_confirmation_rate` | 主品牌 confirmed observation / 有效回答 |
| `judge_fallback_rate` | 任一 observation 为 rules-fallback 的回答 / 有效回答 |
| `pending_review_answers` | 任一当前 observation 待复核的回答数 |
| `measurement_modes` | 当前有效回答的 memory/search 集合 |
| `measurement_targets` | 当前有效回答的 provider_api/consumer_web 集合 |
| `awaiting_collection` | 尚待人工提交或授权浏览器采集的任务数，不进入有效分母 |
| `collection_status_counts` | 待采集、采集中、待提交复核、完成、失败、需重采的计数 |
| `collection_failure_counts` | 验证码、登录失效、空、截断、错误页、流式中断等失败计数 |
| `retrieval_status_counts` | 人工记录或浏览器按冻结联网状态提取的 on/off/unavailable/unknown 计数 |
| `evidence_coverage` | 具有完整 Consumer Web 证据的有效样本数 / Consumer Web 有效样本数 |
| `is_demo` | 全部有效回答来自 demo 引擎 |

只要样本中含 demo，`limitations` 就明确“包含演示引擎，结果不代表真实 AI 表现”。不同模式不能合并成正常汇总。

`delivery_quality` 另从当前事实派生补判覆盖、active JudgeBatch、rules/evidence fallback、fallback 推荐待复核、provisional 推荐、人工 revision、配置/实际模型和交付 readiness，不新建第二套手工状态机。`pending` 不会在本版本被静默从历史公式分母中删除，但待复核推荐必须标为 provisional，且不能进入已批准客户结论。负面向推荐仍按上文降级，不成立 Top Choice 或有效推荐。

Run metrics 和新报告快照带 `metric_appendix`，定义版本为 `geo-metrics-v2.1`。每项同时给出公式、原始 hits/n、当前 value/CI、聚合单元、冻结权重和限制；它复用本文件公式，不形成另一套指标计算。小样本仍可带限制交付，但活跃/混合补判、disabled Judge 未补齐、fallback 推荐和 provisional 推荐会阻断报告审批。

## 8. 严格比较与迁移

基线和复测都必须由管理员指定正式 Run。协议检查覆盖：

- prompt set hash、实体版本、竞品池 hash；
- engine signature、repeats，以及归一化后的按回答引擎 `answer_execution` / `judge_execution` 有效参数；
- language、market、judge version、`judge_mode`；
- 补判后的 effective Judge status/signature、有效 Answer 覆盖数和活跃批次 ID。只有原口径一致或全部有效 Answer 都由同一补判配置覆盖时才可严格比较；只补一边、部分覆盖、配置不同或批次活跃均拒绝严格 delta；
- memory/search、measurement target、`use_judge`；
- Consumer Web 的 collection protocol、product URL、platform、collection method、browser Driver 和独立 Judge signature；
- 有效样本定义、stratum weights。

配对键为 `engine_config_id:canonical_intent_id`：

```text
pair_completeness = |baseline keys ∩ current keys| / |baseline keys ∪ current keys|
sample_completeness = min(baseline valid_sample_rate, current valid_sample_rate)
effective_completeness = min(pair_completeness, sample_completeness)
```

`effective_completeness < 当前 Wave 冻结阈值` 时拒绝严格变化输出，默认阈值 90%。

每个共同配对键分为：持续提及、持续缺席、新增提及、失去提及。指标变化使用百分点 `pp`；基线为 0 时 `relative=null`，不输出无限相对提升。供应商返回模型版本变化时只标探索性比较。

API/Web 或不同 surface/session 上下文属于 `comparison_scope=cross_surface`：`comparable=false`、`exploratory=true`，只返回 baseline/current 各自摘要，`delta=null`、`transitions=[]`。不得把跨产品端差异写成同口径提升或下降。

## 9. 机会评分

候选只有经管理员确认 `eligible/client_confirmed` 后才评分。因子为：

- 商业价值：管理员 1–5 / 5；
- 适用性置信：client_confirmed=1，eligible=0.8；
- 竞争缺口：缺席 1、深度落后 0.7、被贬 0.9、实体歧义 0.85；
- 证据可靠：`min(1, 有效关联回答数/3) ×（有竞品证据 1，否则 0.4）`；
- 可执行性：管理员 1–5 / 5。

使用 **Wave 冻结的 score_weights** 做加权几何聚合：

```text
score = 100 × Π max(0.0001, factor_i)^(weight_i / Σweight)
```

权重总和必须大于 0，否则拒绝评分。事后修改项目默认权重不会改变已有 Wave 的机会评分。

## 10. Intervention cohort 复测

一个 Action 是一个 Intervention cohort。同期多个 Content Asset 和 Channel Publication 不分别计算效果，API、界面和报告均不返回 per-asset delta。

- 创建 D7/D14/D28 节点时固定 Opportunity baseline Wave 当时的 official Run；每轮使用不同的 target Wave。
- 管理员评估时固定 target 当时的 official Run，按固定 Run ID 重新计算指标，再执行与第 8 节相同的严格协议和完整度比较。
- 保存完整 comparison、SHA-256、Answer/Observation revision/Citation refs、成功标准和理由；之后更换 baseline 或 target official Run 不改写已冻结评估。
- `measured` 只表示严格同口径且达到项目小样本阈值；`insufficient_evidence` 表示样本或完整度不足；`incomparable` 表示协议不匹配；`legacy_unavailable` 表示历史记录没有可补造的固定证据。
- 只有 `measured` 才按 Opportunity 缺口类型描述 `improved/not_improved`。其余状态均为 `observed_change=unknown`，不能转化为总体改善结论。
- 所有轮的 `attribution_status=not_attributable`。观察到改善不等于某篇资产、某个渠道或 GEO Action 导致了改善。
- Provider 调度只创建 Run，不自动指定 official Run 或评估；Consumer Web 只去重提醒，仍需显式采集与管理员评估。

原文清理后，冻结 comparison/hash 和 refs 不变；Answer ref 标为 `raw_purged`，不能据此重新核验原文或伪造历史结论。

## 11. 解释边界

- 小样本 Wilson 区间不是显著性实验结论。
- 两次共时测量不是随机对照实验。
- 内容发布、外部事件和指标变化只能并列呈现。
- 不自动把变化归因于 GEO Action，不承诺排名或引用率。
