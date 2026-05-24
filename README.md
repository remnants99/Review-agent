# Review Agent

一个基于 Codex CLI 的论文批量审阅小工具。它会逐篇调用 Codex，让 Codex 阅读指定论文并按照 `review.md` 里的提示词生成中文 Markdown 审稿笔记。

这个项目的设计是 prompt-driven：批处理、日志、重试由 `agent.py` 负责；审稿标准、输出结构和语气主要由 `review.md` 决定。通常你只需要修改 `review.md`，不需要改 Python 代码。

## 环境要求

请先在系统中安装：

- Python 3.10 或更高版本
- Codex CLI
- 一个可以正常登录并使用 Codex CLI 的 OpenAI/Codex 账号环境

检查 Python：

```bash
python --version
```

检查 Codex CLI：

```bash
codex --version
```

在 Windows PowerShell 中，如果 `codex` 因执行策略无法运行，可以试：

```powershell
codex.cmd --version
```

本工具会自动寻找 `codex`、`codex.cmd` 或 `codex.exe`，所以通常不需要手动配置。

## 目录结构

```text
Review-agent/
  agent.py              # 批处理 runner
  review.md             # 审稿提示词模板，主要修改这里
  config.example.json   # 可选配置示例
  待审稿/                # 默认论文输入目录
    .gitkeep
  review_outputs/       # 生成的 Markdown 审稿结果，本地目录，不上传
  runs/                 # 每篇论文的运行日志和隔离工作区，本地目录，不上传
```

默认把待审论文放进：

```text
待审稿/
```

例如：

```text
待审稿/paper.pdf
```

`待审稿/` 目录会保留在 GitHub 仓库中，但里面的 PDF 和其他论文材料默认不会被上传。

## 快速开始

1. 克隆仓库后进入项目目录：

```bash
cd Review-agent
```

2. 把论文 PDF 放入 `待审稿/`。

3. 查看当前待审论文：

```bash
python agent.py list
```

4. 审阅全部论文：

```bash
python agent.py run
```

5. 只审阅某一篇论文：

```bash
python agent.py run --file "待审稿/paper.pdf"
```

6. 查看任务状态：

```bash
python agent.py status
```

7. 重试失败任务：

```bash
python agent.py retry-failed
```

8. 只生成运行目录和渲染后的 prompt，不真正调用 Codex：

```bash
python agent.py run --dry-run --limit 1
```

## 输出位置

最终审稿 Markdown 会复制到：

```text
review_outputs/
```

每篇论文的完整运行记录会保存在：

```text
runs/<paper-id>/
```

其中常见文件包括：

- `prompt.rendered.md`：本次真正发送给 Codex 的提示词
- `events.jsonl`：Codex CLI JSONL 事件日志
- `last_message.md`：Codex 最后一条回复
- `status.json`：任务状态、输出路径和校验结果
- `review_outputs/*.md`：该论文在隔离目录中的原始输出

## 修改审稿要求

审稿要求写在 `review.md` 中。你可以改：

- 审稿语言
- 输出结构
- 评分维度
- 会议或期刊审稿风格
- 关注理论、实验、创新性或写作质量的侧重点

建议保留 `review.md` 里的这些占位符：

- `{{input_file}}`：本次要审阅的论文文件
- `{{input_dir}}`：本次运行目录中的输入目录
- `{{output_dir}}`：本次运行目录中的输出目录
- `{{output_file}}`：必须写入的 Markdown 输出文件

也建议保留这些硬性约束：

- 只审阅 `{{input_file}}`
- 必须把最终结果写入 `{{output_file}}`
- 不要把多篇论文混在同一份审稿中

这些规则让 `agent.py` 能稳定判断任务是否完成。

## 可选配置

可以复制一份本地配置：

```bash
cp config.example.json config.json
```

Windows PowerShell：

```powershell
Copy-Item config.example.json config.json
```

然后按需修改 `config.json`。命令行参数优先级高于 `config.json`。

示例配置项：

```json
{
  "input_dir": "待审稿",
  "output_dir": "review_outputs",
  "runs_dir": "runs",
  "prompt": "review.md",
  "model": null,
  "approval_policy": "never",
  "timeout_minutes": 90,
  "max_retries": 1,
  "limit": null,
  "codex_bin": null
}
```

## 跨平台说明

`agent.py` 使用 Python 标准库实现，没有额外 Python 依赖。

Codex CLI 自动探测顺序：

- Windows：优先使用 `codex.cmd`，然后是 `codex.exe` / `codex`
- macOS / Linux：优先使用 `codex`

也可以手动指定：

```bash
python agent.py run --codex-bin /path/to/codex
```

或设置环境变量：

```bash
CODEX_BIN=/path/to/codex python agent.py run
```

Windows PowerShell：

```powershell
$env:CODEX_BIN = "codex.cmd"
python agent.py run
```

## Git 忽略规则

仓库默认不会上传：

- `待审稿/` 中的论文文件
- `Paper/`
- `*.pdf`
- `*.zip`
- `runs/`
- `review_outputs/`
- `config.json`
- Python 缓存文件

GitHub 上只保留 `待审稿/.gitkeep`，用于创建默认输入目录。

提交前可以检查实际会上传哪些文件：

```bash
git ls-files
```

正常情况下不应该看到任何 PDF。

## 常见问题

### Codex 找不到或无法运行

先确认命令可用：

```bash
codex --version
```

Windows 可以试：

```powershell
codex.cmd --version
```

如果 Codex 安装在特殊位置，用 `--codex-bin` 指定。

### PowerShell 中 `codex` 被执行策略阻止

Windows 上可能出现 `.ps1` 执行策略问题。这个工具会优先尝试 `codex.cmd`，通常可以绕过该问题。

### Markdown 公式没有渲染

`review.md` 已要求 Codex 使用 `$...$` 和 `$$...$$` 输出公式。如果预览器仍显示 TeX 源码，请确认你的 Markdown 预览器支持 MathJax 或 KaTeX。

### 不想一次跑完全部论文

使用 `--file` 指定单篇：

```bash
python agent.py run --file "待审稿/paper.pdf"
```

或者限制数量：

```bash
python agent.py run --limit 3
```
