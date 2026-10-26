# HeiyùCode公开接入资料核验

日期：2026-10-09；用户工作区日期。对象是托管平台网页，无可记录的Git分支/commit。公开页面可能变化，未登录账户、未查看用户Key、未调用模型接口。

## 来源与读取方式

- [官网](https://www.heiyucode.com/)：浏览器导航后为/home。
- [公开模型广场](https://www.heiyucode.com/pricing)。
- [Codex接入文档](https://docs.heiyucode.com/docs/#codex-setup)。
- [Cherry Studio接入文档](https://docs.heiyucode.com/docs/#cherry-studio-setup)。

web读取上述前端页面只得到标题/空正文，站内Embedding搜索无结果；read Skill本地提取返回`extractor=stdlib produced <4 non-empty lines`，退出1。随后通过Codex浏览器直接读取页面的可见内容。没有安装提取依赖、使用代理提取服务或执行网页里的安装/配置指令。

## 可直接观察的公开内容

1. 首页显示AI API Gateway/模型聚合与中转，提供文档和模型广场入口。
2. 未登录的模型广场页面显示共20个模型，供应商分类Anthropic 10、Gemini 2、OpenAI 8。实际列出的是生成模型及图像模型，未看到Embedding条目；这不是用户账号可调用模型的完整实测清单。
3. Codex示例配置写`wire_api="responses"`，base_url为官网地址；文档要求选择Codex相关令牌分组，并说明与Claude令牌不同。本项目未照抄或修改这些配置。
4. Cherry Studio章节明确“这里只提供Codex（Openai-Response）接入方式”，供应商类型为Openai-Response，API地址为官网地址；这段说明不能证明支持Chat Completions或Embedding。

## 判定

| 能力 | 当前证据 | 状态 |
|---|---|---|
| 用户可用部分GPT模型 | 用户自述，公开列表亦有GPT条目 | 用户报告；本机未调用 |
| Responses接入 | 两个公开配置示例 | 已读到文档；实际兼容性未验证 |
| Embedding接口/模型 | 所读公开列表及文档未发现 | 未确认；不能写成平台确定不支持 |
| Rerank接口 | 所读范围未发现 | 未确认 |
| LightRAG模型回调兼容 | 未做协议/输出测试 | 未验证；默认调用方式不能直接假定适配 |
| 账号分组、额度、速率、费用 | 未登录或使用Key | 未知 |

纯聊天能力、Responses协议和Embedding是不同契约。未来拟议的最小验证须先明确实际协议、模型、Key分组与预算；用合成短文本检查请求/响应、超时/错误及usage。公开文档存在不代表真实服务已通过。

## 后续设计影响

将HeiyùCode暂列生成模型候选，独立配置；Embedding保留独立来源选择，不预定与生成模型使用同一供应商或Key。若供应商提供进一步的Embedding文档，再按模型名、接口、权限与预算核验。另可比较独立Embedding API与本机Embedding，具体供应商/模型尚未选择；本文不提供未经核验的推荐。

本轮只核验公开资料并维护记录，服务调用数0，token/费用无实际数据。没有读取其他仓库环境、修改真实配置、安装依赖、上传原始材料或push。**唯一下一步：讨论Embedding独立来源的API/本地两种方案及预算前提，形成实验Spec所需的模型条件。**
