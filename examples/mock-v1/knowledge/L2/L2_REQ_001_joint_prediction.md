# L2：联合模型预测与派生分

> 材料性质：完全合成。
> 文档ID：MOCK-L2-001
> 需求编号：MOCK-REQ-001
> 变更日期：2026-01-10
> 所属模块：策略编排、分数计算
> 前置依赖：[策略模块](../L1/Dispatcher/L1_dispatch.md)、[校准模块](../L1/Scoring/L1_calibration.md)
> 文档摘要：一次预测返回三个基础值，计算三种派生分，按历史规则逐字段校准。
> 文档索引：§1 背景；§2.1 公式（L999-L1005）；§2.2 历史校准；§3 边界。

## 1. 需求背景

原实现分别请求不同输出，本次以一次联合模型预测提供 p、v_short、v_long。
这是一份保留当时内容的历史需求，不是整个系统的现行规则全集。

## 2. 功能与实现

### 2.1 原始计算公式

```text
pv_short_raw = p * v_short * weight_short
pv_long_raw = p * v_long * weight_long
pv_total_raw = pv_short_raw + pv_long_raw
```

三个派生原始值均先于校准计算，不使用已经校准过的基础分数。
公式中的 p、v_short、v_long 表示预测原始值。参数 weight_short、weight_long 来自配置，不从正文数字取运行参数。
合成算例：p=0.2，v_short=5，v_long=10，weight_short=2，weight_long=3。
由此 pv_short_raw=2，pv_long_raw=6，pv_total_raw=8。

### 2.2 历史校准

2026-01-10 时，prob_score、short_value、long_value、pv_short、pv_long、pv_total 都按字段应用 gain。
开关开启且字段匹配时 output=raw*gain；开关关闭或字段未匹配时保留 raw。
上述算例在所有字段 gain=1.5 时，三个派生输出为 3、9、12。
这条历史行为可能被后续需求局部改变，不能仅因文档较旧而整篇排除。

## 3. 边界与异常

缺少某个预测头时将该原始值记为 0；缺少短期价值只让短期派生分为 0，长期派生分仍按其公式计算。
输入值为负数或非有限数时整次请求回退到基线，并记录 INVALID_PREDICTION。
权重缺失属于配置错误，记录 MISSING_WEIGHT，不用算例里的数值自动补齐。
四条 route 均遵循同一组公式和校准先后顺序。
