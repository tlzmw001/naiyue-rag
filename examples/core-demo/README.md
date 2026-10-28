# 独立 RAG 核心示例（完全合成）

5 份 Markdown 只描述虚构订单计费和日志规则，不是用户真实资料。新需求、上级模块、历史需求和一行一个用例的 Markdown 表格用于验证结构/来源/检索接线；参数是可比较的起点，不代表最优值。

## 配置与运行

`app.example.yaml` 引用各层独立 YAML；将其中 `project_root` 改成自己的仓库绝对路径。凭证只通过所选环境变量 `NAIYUE_RAG_ZHIPU_API_KEY` 或该项目 `.env` 解析，不复制真实 Key 到 YAML。模型标准 API 是否可用由实际账号决定。

在仓库根目录执行（会调用所配置的真实模型；不会自动下载本地模型）：

```bash
.venv/bin/python -m naiyue_rag.app --config examples/core-demo/app.example.yaml ingest --expected-revision 0
.venv/bin/python -m naiyue_rag.app --config examples/core-demo/app.example.yaml documents
.venv/bin/python -m naiyue_rag.app --config examples/core-demo/app.example.yaml query --expected-revision 1 --query '移除折扣开关需要参考哪些历史需求和用例？'
```

第一次成功摄取后 revision 通常为 1；以后从 documents 的实际返回取得 revision，不能反复用 0。重复且无变化的摄取复用旧版本，不重复编码。产物在本示例 `data/`，受 Git 忽略，不能把未克隆的产物视为存在。

只查看文档列表不加载模型。query 的 `--scope doc-...` 限定文档，`--scope` 不带 ID 表示显式空范围；省略 scope 为全库。`--exclude doc-...` 排除文档；这些都是检索过滤，不是权限管理。query 未给 `--query` 时可从 stdin 读取。

关闭重排对照：在自己复制的配置中设置 rerank.enabled=false、app.rerank_backend=none、app.model_settings=null。仍会执行查询 Embedding 与双路召回，不能因此称为零模型请求。

结果为核心 JSON：status、answerability=unknown、固定 active 版本、context_text、带实际 body_span/完整正文及 contexts 的 evidence，以及分账 observations。内部向量不在结果中。证据不够预算时整片遗漏并列出 reason；JSON 整体超限报错。检索相关性和引用存在不能代替答案正确或业务质量。

## 小型固定样本

`questions.json` 的标签由助手构造，未获用户逐题审阅；通过唯一文件路径/正文锚点绑定本版 chunk。前三题计算片段级 Recall@5；第四题无依据，分母为零记 null，系统 answerability 仍 unknown，不假装已经有无答案分类器。

已摄取本示例后，可显式运行有界对照（每题一次 Embedding 加一次 GLM 重排，4题最多8 HTTP；基线与重排使用相同候选池）：

```bash
.venv/bin/python -m naiyue_rag.validation.retrieval_smoke \
  --config examples/core-demo/app.example.yaml \
  --questions examples/core-demo/questions.json \
  --output-dir data/validation/core-demo-01 \
  --max-requests 8 --deadline-seconds 240
```

输出目录必须尚不存在；保留实际失败，不覆盖结果。外层监督超时后服务端完成与费用可为未知，不能推定远端请求已取消。质量比较是本小样本证据，不代表真实知识库或性能容量验收。本地后端的依赖处理/安装与 CPU 验证见 Spec0043；其当前状态以 handoff 为准。

## 本地 Cross-Encoder：配置与显式准备

2026-10-16，本机已验证 macOS arm64 / Python3.12 的单环境兼容组合。原有包只调整 hub 2.2.0→1.33.0；其余版本保持。版本入口为仓库根目录 `requirements-reranking.txt`，对应 wheel 哈希在 `requirements-reranking.lock.txt`；该哈希锁针对当前平台，不能直接视为 Windows/Linux 安装验收。

已具备原有项目依赖时，安装新增运行依赖：

```bash
.venv/bin/python -m pip install -r requirements-reranking.txt
.venv/bin/python -m pip check
```

复现本机增量 wheel 集合时，可合并使用以下锁文件（实验基础环境应已安装）：

```bash
.venv/bin/python -m pip install --no-deps --require-hashes --only-binary=:all: \
  -r requirements-chroma.lock.txt -r requirements-encoding.lock.txt \
  -r requirements-reranking.lock.txt
```

本地配置为 `cross-encoder.example.yaml`，显式固定模型、Hub commit、CPU、batch_size=4、max_pair_tokens=512、权重总字节上限。这里只对一套多语言模型做过本机验证，不承诺任意模型结构均可直接替换。当前准备工具支持本示例使用的未分片 safetensors 和 tokenizer 文件。

先显式准备公开模型（首次会下载约493 MB，失败不自动删除部分文件）：

```bash
.venv/bin/python -m naiyue_rag.validation.prepare_local_model \
  --settings examples/core-demo/cross-encoder.example.yaml
```

该命令按固定 commit 核对远端文件身份，下载时不提供 Hugging Face token，不执行远程代码；仅保存安全权重/配置/tokenizer/模型卡，写入本地 manifest。已有合法模型只审计复用，未知非空目录拒绝覆盖。模型文件在受Git忽略的本示例 `data/models/`，克隆仓库后需要自行准备。

已摄取同一示例知识库后，切换查询后端：

```bash
.venv/bin/python -m naiyue_rag.app --config examples/core-demo/app-cross-encoder.example.yaml \
  query --expected-revision 1 --query '移除折扣开关需要参考哪些历史需求和用例？'
```

这里使用相同摄取、双路检索、RRF和证据合同。核心查询只读本地模型，不自动下载；输入整对分词后超出512 tokens会整次报错，不截断用例。512是该示例模型的上限，max_pair_tokens配置不能突破模型自然容量。运行时只加载已审计的本地文件，CPU批次参数实际传入predict。

**本地化的是重排。查询 Embedding 仍使用 encoding 配置指定的服务**；要完全离线运行，还需要另外验证本地 Embedding 服务。当前没有做这项部署。

固定四题同候选池：跨文档题必要片段Recall@5分别为关闭重排1/3、本地2/3、已保存真实GLM3/3；其余两题均1/1，无依据题仍unknown。此小样本不足以定型模型或证明真实资料质量。GLM和本地后端由配置选择；失败不会隐式换成另一后端。
