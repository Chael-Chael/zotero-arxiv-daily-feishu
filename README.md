<p align="center">
  <a href="" rel="noopener">
 <img width=200px height=200px src="assets/logo.svg" alt="logo"></a>
</p>

<h3 align="center">Zotero-arXiv-Daily</h3>

<div align="center">

  [![Status](https://img.shields.io/badge/status-active-success.svg)]()
  ![Stars](https://img.shields.io/github/stars/TideDra/zotero-arxiv-daily?style=flat)
  [![GitHub Issues](https://img.shields.io/github/issues/TideDra/zotero-arxiv-daily)](https://github.com/TideDra/zotero-arxiv-daily/issues)
  [![GitHub Pull Requests](https://img.shields.io/github/issues-pr/TideDra/zotero-arxiv-daily)](https://github.com/TideDra/zotero-arxiv-daily/pulls)
  [![License](https://img.shields.io/github/license/TideDra/zotero-arxiv-daily)](/LICENSE)

</div>

---

<p align="center"> 根据你的 Zotero 文献库，每日推荐感兴趣的 arXiv 论文。
    <br> 
</p>

> [!IMPORTANT]
> 请关注此仓库，及时同步上游更新以获取新功能和修复。

## 🧐 关于

> 只需 Fork（和 Star）本仓库，即可追踪你感兴趣的最新科研成果！😊

*Zotero-arXiv-Daily* 根据你 Zotero 文献库的内容，找到可能吸引你的 arXiv 论文，并将结果推送到**飞书群**📮或邮箱。可作为 GitHub Action 工作流部署，**零成本**、**无需安装**、**配置简单**，每日**自动**推送。

## ✨ 特性

- 完全免费！所有计算都在 GitHub Action 运行器本地完成
- AI 生成 TLDR 摘要，快速筛选目标论文
- 解析并展示论文作者机构
- 邮件/飞书卡片中包含 PDF 和代码链接
- 论文按与你近期研究兴趣的相关度排序
- 支持**飞书机器人**和**邮件**两种推送方式
- 支持 LLM API 生成论文摘要
- 使用 gitignore 风格规则忽略不需要的 Zotero 论文

## 📷 截图
![screenshot](./assets/screenshot.png)

## 🚀 使用方法

### 快速开始

1. Fork（并 Star😘）本仓库
![fork](./assets/fork.png)

2. 设置 GitHub Action 环境变量
![secrets](./assets/secrets.png)

### 必需的 Secrets

| Key | 必填 | 类型 | 说明 | 示例 |
| :--- | :---: | :---  | :---  | :--- |
| ZOTERO_ID | ✅ | str | Zotero 用户 ID（**是一串数字，不是用户名**）。从[这里](https://www.zotero.org/settings/security)获取 | 12345678 |
| ZOTERO_KEY | ✅ | str | 具有读取权限的 Zotero API 密钥。从[这里](https://www.zotero.org/settings/security)获取 | AB5tZ877P2j7Sm2Mragq041H |
| ARXIV_QUERY | ✅ | str | 目标 arXiv 论文类别，用 `+` 连接多个类别。从[这里](https://arxiv.org/category_taxonomy)查找 | cs.AI+cs.CV+cs.LG+cs.CL |
| FEISHU_WEBHOOK_URL | ✅* | str | 飞书自定义机器人 webhook 地址 | https://open.feishu.cn/open-apis/bot/v2/hook/xxx |
| FEISHU_SECRET | | str | 飞书机器人签名密钥（如启用安全设置）| abc123secret |

> *如果使用邮件推送而非飞书，则需要配置邮件相关 Secrets（见下文）

### 邮件推送配置（可选）

如需使用邮件推送，设置 `NOTIFY_METHOD` 为 `email` 或 `both`，并配置以下 Secrets：

| Key | 类型 | 说明 | 示例 |
| :--- | :---  | :---  | :--- |
| SMTP_SERVER | str | SMTP 服务器 | smtp.qq.com |
| SMTP_PORT | int | SMTP 端口 | 465 |
| SENDER | str | 发件邮箱 | abc@qq.com |
| SENDER_PASSWORD | str | 发件邮箱 SMTP 密码 | abcdefghijklmn |
| RECEIVER | str | 收件邮箱 | abc@outlook.com |

### LLM 配置（可选）

| Key | 类型 | 说明 | 示例 |
| :--- | :---  | :---  | :--- |
| MAX_PAPER_NUM | int | 推送论文最大数量，`-1` 为全部 | 50 |
| USE_LLM_API | bool | 是否使用云端 LLM API（`1`）或本地 LLM（`0`，默认）| 0 |
| OPENAI_API_KEY | str | LLM API 密钥。可在 [SiliconFlow](https://cloud.siliconflow.cn/i/b3XhBRAm) 获取免费 API | sk-xxx |
| OPENAI_API_BASE | str | LLM API 地址，默认 OpenAI | https://api.siliconflow.cn/v1 |
| MODEL_NAME | str | 模型名称，默认 gpt-4o | Qwen/Qwen2.5-7B-Instruct |

### Repository Variables

| Key | 类型 | 说明 | 示例 |
| :--- | :---  | :---  | :--- |
| ZOTERO_IGNORE | str | gitignore 风格规则，忽略特定 Zotero 文献夹 | AI Agent/<br>**/survey |
| NOTIFY_METHOD | str | 推送方式：`feishu`（默认）/ `email` / `both` | feishu |
| LANGUAGE | str | TLDR 摘要语言 | Chinese |
| SEND_EMPTY | bool | 无新论文时是否发送空消息 | False |

---

### 配置飞书机器人

1. 在目标群组中点击设置 → 群机器人 → 添加机器人 → 自定义机器人
2. 设置机器人名称，获取 webhook 地址
3. （可选）启用签名校验并记录密钥
4. 将 webhook 地址添加到 GitHub Secrets 的 `FEISHU_WEBHOOK_URL`

> ⚠️ **请妥善保管 webhook 地址**，避免泄露后被恶意调用

---

### 测试工作流

配置完成后，手动触发测试：
![test](./assets/test.png)

> [!NOTE]
> Test-Workflow 是调试版本，始终获取 5 篇论文。主工作流每天自动运行，获取前一天发布的新论文。周末和节假日没有新论文。

默认每天 UTC 22:00 运行，可在 `.github/workflows/main.yml` 中修改。

### 本地运行

需安装 [uv](https://github.com/astral-sh/uv)：

```bash
# 设置环境变量
# export ZOTERO_ID=xxxx
# export FEISHU_WEBHOOK_URL=xxxx
# ...
cd zotero-arxiv-daily
uv run main.py
```

## 📖 工作原理

*Zotero-arXiv-Daily* 首先通过 API 获取你 Zotero 文献库中的所有论文和前一天发布的 arXiv 论文。然后使用 embedding 模型计算每篇论文摘要的向量表示。新论文的得分是它与所有 Zotero 论文的加权平均相似度（最近添加的论文权重更高）。

TLDR 由轻量级 LLM（Qwen2.5-3b-instruct-q4_k_m）根据论文的标题、摘要、引言和结论生成。

## 📌 限制

- 推荐算法较简单，可能无法准确反映你的兴趣。欢迎提出改进建议！
- 工作流在 GitHub Action 运行器的 CPU 上部署 LLM，生成一篇论文的 TLDR 约需 70 秒。

## 👯‍♂️ 贡献

欢迎 Issue 和 PR！但请记住 **PR 应合并到 `dev` 分支**。

## 📃 许可证

基于 AGPLv3 许可证分发。详见 `LICENSE`。

## ❤️ 致谢

- [pyzotero](https://github.com/urschrei/pyzotero)
- [arxiv](https://github.com/lukasschwab/arxiv.py)
- [sentence_transformers](https://github.com/UKPLab/sentence-transformers)
- [llama-cpp-python](https://github.com/abetlen/llama-cpp-python)

## 🌟 Star History

[![Star History Chart](https://api.star-history.com/svg?repos=TideDra/zotero-arxiv-daily&type=Date)](https://star-history.com/#TideDra/zotero-arxiv-daily&Date)
