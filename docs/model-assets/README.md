# Qwen3 Embedding 模型附件

`Qwen3-Embedding-0.6B-Q8_0.gguf` 是独立的模型发行附件，不进入 Git 仓库、Python wheel 或 sdist。本仓库只保存[来源与 SHA-256 清单](qwen3-embedding-0.6b-q8_0.json)及[模型许可证文本](Qwen3-Embedding-0.6B-Q8_0.LICENSE.txt)。上游为 Qwen 官方的 `Qwen/Qwen3-Embedding-0.6B-GGUF`，修订 `370f27d7550e0def9b39c1f16d3fbaa13aa67728`，许可标为 Apache-2.0；本项目代码采用独立的 [MIT 许可证](../../LICENSE)。[上游模型页](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF)

本机准备的附件为 639150592 字节，SHA-256 `06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439`；Qwen 官方上述固定修订的下载响应也报告相同长度和 `x-linked-etag` 摘要。Mac 上用该文件通过 Ollama `Modelfile FROM` 导入，得到的 Ollama manifest digest 为 `8b752ab34efb5f17a84567801ec213e5d2c2da504b5501775cec3588258cc13d`；它与 `ollama pull` 的 manifest digest 不同。两条短输入的兼容接口向量逐值相同，均为 1024 维；两边对超窗原生无截断请求均返回 400。这是 Mac 验证，不保证 Linux 使用的 Ollama 版本产生相同 manifest digest；目标机必须核对文件 SHA、运行时模型身份与无截断探针。[Ollama GGUF 导入说明](https://docs.ollama.com/import)

实际公开发布须将 GGUF、此许可证文本和清单放在同一个 GitHub Release，并绑定经过审核的项目版本标签。当前只是本地附件候选，未创建或上传 Release。
