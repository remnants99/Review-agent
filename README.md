# Codex 论文审阅批处理 Agent

这是一个 prompt-driven 的轻量批处理工具：`agent.py` 负责发现论文、创建隔离运行目录、调用 Codex CLI、记录状态和收集输出；具体审稿标准由 `review.md` 控制。

通常别人只需要修改 `review.md`，不要改 `agent.py`。

## 目录约定

```text
review-agent/
  agent.py
  review.md
  待审稿/
    paper.pdf
  review_outputs/
  runs/
```

## Prompt 接口

`review.md` 中建议保留这些占位符：

- `{{input_file}}`：本次要审阅的论文文件
- `{{input_dir}}`：本次运行目录中的输入目录
- `{{output_dir}}`：本次运行目录中的输出目录
- `{{output_file}}`：必须写入的 Markdown 输出文件

可以自由修改审稿格式、评分标准、语言和详细程度，但不要删除“只审阅 `{{input_file}}`”和“必须写入 `{{output_file}}`”这类硬性规则。

## 使用方式

列出待审论文：

```bash
python agent.py list
```

审阅全部论文：

```bash
python agent.py run
```

只审阅一篇：

```bash
python agent.py run --file "待审稿/paper.pdf"
```

查看状态：

```bash
python agent.py status
```

重试失败任务：

```bash
python agent.py retry-failed
```

先演练目录和 prompt 渲染，不调用 Codex：

```bash
python agent.py run --dry-run --limit 1
```

## 跨平台说明

脚本会自动寻找 Codex CLI：

- Windows 优先使用 `codex.cmd`
- macOS / Linux 优先使用 `codex`
- 也可以通过环境变量 `CODEX_BIN` 或参数 `--codex-bin` 指定

运行时使用 `subprocess.run(..., shell=False)`，不会依赖 PowerShell、bash 或 zsh 的重定向语法。

默认会以 `codex -a never exec ...` 的形式运行，避免非交互批处理卡在审批提示上。如需修改，可以使用 `--approval-policy` 或在 `config.json` 中设置 `approval_policy`。

## 可选配置

可以创建 `config.json` 覆盖默认值。示例见 `config.example.json`。

命令行参数优先级高于 `config.json`。
