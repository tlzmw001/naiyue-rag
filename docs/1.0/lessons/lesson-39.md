# Lesson 39：阶段B·6.2 标注单位、Recall@k与固定样本对照

> 2026-10-26。目标：用同一个需求手算召回率，区分文档/片段/业务证据单位，沿现有合成评测追踪标签到得分；理解跨分块对照的边界。仅学习和既有验证，不实现新的标注系统。

## 输入与评价对象

沿examples/core-demo/questions.json的Q1：移除折扣后，参考哪些历史需求/用例，回归哪些保留行为？现有标签先列三项required：

| 课堂短名 | source_path | 正文anchor | 业务用途 |
|---|---|---|---|
| R | L1_module.md | 基础金额使用原始单价乘以数量 | 保留规则 |
| H | L2_previous.md | discount_enabled=0 时不使用折扣 | 历史开关行为 |
| C | L2_previous_测试用例.md | \| TC-01 \| | 回归用例参考 |

短名只用于手算，不是实际Chunk ID。此标签集是助手构造、未用户审核；只能称“相对于当前所列required集合的覆盖”，不能声称已经穷尽所有相关证据。新L2是任务依据；它的自命中不能替代历史参考。

## 三种标注单位

| 单位 | 命中含义 | 局限 |
|---|---|---|
| 文档 | 相关文档至少有一个片段进入选中集合 | 可能只命中文档标题，没拿到需要的规则 |
| 精确片段 | 标注的具体Chunk ID进入选中集合 | 依赖当前分块结果；同一文档其他片段不算 |
| 业务证据单元 | 所需规则/边界条件/完整用例要素被返回内容覆盖 | 需定义来源、适用条件和完整覆盖/部分覆盖标准 |

当前smoke的unit是exact_current_chunk_selected_by_unique_source_and_body_anchor。人工审核标签、助手合成标签、模型相关性评分是不同来源。这里gold指当前参照集合，不自动等于人工金标准。

## Recall@k手算

对某个已排序阶段的前k条结果：

```text
Recall@k = 前k条中命中的唯一必需单位数 / 标注的唯一必需单位总数
```

分母不是k，也不是返回总数。required={R,H,C}，给出两个课堂排序：

```text
A：[R, X, Y, H, C]
B：[C, H, R, X, Y]
```

| 排序/截取 | 命中集合 | Recall |
|---|---|---|
| A前3 | {R} | 1/3 |
| A前5 | {R,H,C} | 3/3=1 |
| B前3 | {C,H,R} | 3/3=1 |
| B前5 | {C,H,R} | 3/3=1 |

同一固定排序扩大k，召回率不降，但返回量和上下文成本可能增加；不能用A@5对B@3直接宣布整体方案更优。前k内部改变次序但成员不变时，Recall@k不变，因此它不区分第1与第k名；也不直接度量噪声比例、回答正确性或任务完成度。

与之不同，Precision@k关注“实际取出的前k条里有多少相关”。如果恰好取满5条且只有R/H/C三条相关，Precision@5=3/5，而Recall@5=3/3。本节只做概念对照；现有score_ids未实现Precision或位置敏感排序指标。标签不完整时，不能简单将所有未标注条目视为无关。

返回[R,R,X]只命中一个唯一单位，Recall=1/3。去重只是计分不重复加分，不会把列表自动补成三条不同候选。

## 当前源码怎样算

`validation/retrieval_smoke.py:14–16`：

```python
def score_ids(selected, required):
    gold = set(required)
    hits = len(set(selected) & gold)
    return dict(
        hits=hits,
        required=len(gold),
        recall=hits / len(gold) if gold else None,
    )
```

代入selected=['a','a','x']、required=['a','b']：gold={'a','b'}，选中集合={'a','x'}，交集={'a'}，hits=1，required=2，recall=.5。selected为空、gold非空返回0；gold为空返回None，JSON为null，避免除0或无依据计100%。

函数本身没有k参数，也不做截取。worker传入各阶段已选好的ID列表；本课数字探针显式ranked[:k]后调用。把完整候选列表传入，再把结果命名Recall@3，会造成口径错误。

当前Q4为空gold且unanswerable=true，但并非任何required=[]都自动代表已确认无答案。无答案问题应单独检查是否错误声称可回答、是否给出支持不足的结果；当前answerability固定unknown，尚无无答案分类器，recall=null不是分类通过。

## 标签到实际ID的调用链

```text
questions.json（问题、来源路径、正文anchor、标签来源）
    → validate_labels（结构/类型/问题ID等检查）
    → hybrid=search.search(query)
    → 读取hybrid绑定版本的Bundle
    → resolve_gold(bundle.chunks, required)
       每项按source_path且anchor在chunk.text中匹配
       必须恰好1个 → 保存其真实Chunk ID
    → score_ids(各阶段selected IDs, gold IDs)
    → 每题pool/baseline/reranked/packed报告
```

resolve_gold零匹配或多匹配都抛smoke_ambiguous_labels，不悄悄少算一项或挑第一条。路径对上但anchor仅在contexts、不在chunk.text也不会命中。validate_labels只校结构，不判业务相关性或标签充分性；其来源枚举固定为助手未审核合成标签，当前不是通用人工标注入口。

worker第95行每题新搜索，绑定该次选中Bundle，再分别关闭/启用重排共用同一hybrid，控制重排实验的候选池。pool是fusion_top_k后的集合；baseline/reranked由rerank.top_k限制；packed按实际完整证据预算选取，宜称预算后覆盖，不伪装成固定返回k条。全部用同一题gold比较。

## 为什么改分块后不能直接沿用旧Chunk标签

保持原文与问题不变：方案A把一条规则放一个Chunk；方案B把规则切成三段。两者Chunk ID/数量可变，精确Chunk Recall的分母与完整语义覆盖不再自然等价。即使ID标签重新映射，也需确认每个方案用相同业务内容判断“找齐”。

当前source_path+anchor只在匹配唯一时能映射到新ID；anchor被切断会零匹配，重叠使其出现于多个Chunk会多匹配，明确失败。这保护标签有效性，但不自动验证整个规则是否完整，更不实现跨方案公平评测。

跨分块对照建议（未来评测设计，本课未实现）：先固定原文快照/内容SHA、问题、任务角色和业务证据单元，例如R基础规则/H历史条件/C完整用例；分别把各方案返回片段映射回这些单位，预先定义“多片联合覆盖”“部分信息”“可替代来源”的计分标准。固定共同业务分母，另报精确Chunk指标及实际字符/token预算。不要看到某方案结果后修改标签让它更高。

## 固定样本对照的最小合同

- 同一组问题/原文与版本、相同scope/exclude和任务依据；先固定标签并标明来源/审核状态。
- 明确统计阶段、单位、k与上下文预算；候选k和重排k分别记录。
- 一次改变一个实验因素；重排对照尽量复用候选池；改分块则允许按同一原文分别建索引，比较共同业务证据单位，不能强求产物ID相同。
- 查看逐题结果并区分跨文档、具体用例、无答案等题型；不只看总平均。
- 若汇总，说明算法：两题3/3与0/1，逐题平均macro=(1+0)/2=.5，累计micro=3/4=.75，回答不同权重问题。空gold题不作为100%塞入普通Recall均值，应单列计数和无答案表现。当前smoke保存逐题结果，没有实现这两种汇总。
- 调参样本与后续保留验证样本分开，避免只记住当前几题；小样本用于发现具体失败，不作真实规模结论。当前仅4题，不新增数据或宣称统计显著性。

## Debug Test入口与分支

1. `tests/test_retrieval_smoke.py::test_recall_uses_gold_count_and_deduplicated_ids`，无参数ID。Test Explorer→Debug Test，F11进入score_ids，第15行执行后看gold/hits，selected仍是原始列表；第16行返回字典，回测试第7行核.5，再走8行空selected=0、9行空gold=None。无IO或模型替身，真实计分函数执行。
2. `test_fixed_labels_are_resolved_to_unique_saved_chunk`，无参数ID。测试15行构造一个SimpleNamespace模拟Chunk，16行进入resolve_gold；第22行执行后看label、found，第24行result追加'a'。测试17行chunks*2注入重复匹配，第23行抛smoke_ambiguous_labels，pytest.raises捕获，测试仍通过。此夹具仅证明唯一定位算法，未建真实索引或检验相关性。
3. `test_labels_cannot_escape_output_or_change_the_schema[invalid_gold]`，测试30行注入多余gold字段；validate_labels第44–47行拒绝，测试32行捕获。其他参数[path/duplicate/empty_query/extra/unanswerable]覆盖相应结构问题；重复的是问题ID，不是重复证据命中。

只观察当前帧已产生的selected/required/gold/hits或label/found/result；无需在WATCH重新调用函数。单元测试不会进入worker或请求服务。

## 本次实际验证

```sh
.venv/bin/python -m pytest -q tests/test_retrieval_smoke.py
# 8 passed in 0.13s
```

另用临时Python标准输入脚本，直接导入生产score_ids，对课堂构造排序先[:k]再计分，实际输出：

```text
top3: hits1/required3, recall0.3333333333333333
top5: hits3/required3, recall1.0
reordered_top3: hits3/required3, recall1.0
duplicates_top3: hits1/required3, recall0.3333333333333333
empty_gold: hits0/required0, recall null
```

这是确定性算术探针，不是真实检索结果；无模型/网络/索引调用。L1：现有标签、解析/计分及报告代码存在；L2：真实集合计分/唯一定位/严格结构验证执行；L3：单测实际调用这些函数，worker消费链由源码核对，本课未执行服务worker。没有实现新指标、业务证据映射或无答案判定。

仅维护学习文档，源码/.env/运行配置/依赖/原索引不改。构建不适用，未跑全量或真实资料质量实验；git diff --check与git diff --cached --check退出0。

## 学习证据与唯一下一步

6.2已讲解，用户理解待反馈，独立调试/实现未评估。讲解覆盖31/34节，余第6章3节。唯一下一步：6.3失败归因与单变量实验。
