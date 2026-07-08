# Sense — 多模态 AI 桥接工具

[![skills.sh](https://skills.sh/b/feat-cat/sense)](https://skills.sh/feat-cat/sense)

让 **文本 AI** 调用另一个 **多模态 AI** 来理解图片、音频、视频，并支持多轮对话追问。

## 快速开始

### 方式一：CLI（推荐）

```bash
# 安装
npm i -g sense-cli

# 使用（从任意目录）
sense new --prompt "描述这张图片" --file photo.jpg
```

### 方式二：Python 直调

```bash
# 安装依赖
pip install requests

# 配置 .env（在 skill 目录下）
cp .env.example .env
# 编辑 .env 填入 API_KEY、BASE_URL、MODEL_ID

# 使用
cd skill
python bridge.py new --prompt "描述这张图片" --file photo.jpg
```

### 给 AI Agent 安装

```bash
npx skills add feat-cat/sense
```

安装后 AI 会自动使用 `sense` 或 `bridge.py` 来处理你的多模态请求。

## 支持的文件类型

| 类型 | 格式 |
|------|------|
| 图片 | `.jpg` `.jpeg` `.png` `.gif` `.bmp` `.webp` `.svg` |
| 音频 | `.mp3` `.wav` `.m4a` `.ogg` `.flac` |
| 视频 | `.mp4` `.mov` `.avi` `.mkv` `.webm`（原生或抽帧） |
| 文档 | `.pdf` |

## 使用示例

```bash
# 分析图片
sense new --prompt "描述这张图片" --file photo.jpg

# 分析音频
sense new --prompt "这段音频在说什么" --file recording.mp3

# 分析视频
sense new --prompt "视频里发生了什么" --file demo.mp4

# 继续追问
sense continue <session_id> --prompt "画面里有什么文字？"

# 查看所有对话
sense list

# 显示详细信息（文件处理、token 用量）
sense -v new --prompt "..." --file image.jpg
```

## 支持的平台

可配合任何 **OpenAI 兼容 API** 的多模态模型使用，已验证：

| 平台 | BASE_URL | 推荐模型 |
|------|----------|----------|
| OpenCode Zen | `https://opencode.ai/zen/v1` | `mimo-v2.5-free`（免费） |
| NVIDIA NIM | `https://integrate.api.nvidia.com/v1` | `nvidia/nemotron-3-nano-omni-...` |
| OpenRouter | `https://openrouter.ai/api/v1` | `nvidia/...` 等 |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` |

## 配置说明

### `.env` 必填项

| 配置 | 说明 |
|------|------|
| `API_KEY` | 多模态 AI 的 API 密钥 |
| `BASE_URL` | API 基础地址（脚本拼接 `/chat/completions`） |
| `MODEL_ID` | 模型 ID |
| `DATA_PATH` | 对话数据存储路径 |

### 视频模式

- `native`（默认）— 整个视频以 `video_url` 上传，服务端自动抽帧
- `extract` — 本地 ffmpeg 抽帧，以多张图片发送

详见 `skill/SKILL.md`。

## 项目结构

```
feat-cat/sense/
├── skill/              ← skill 本体（npx skills add 安装的内容）
│   ├── SKILL.md          AI 使用指引
│   ├── bridge.py         核心 Python 脚本
│   └── .env.example      配置模板
├── cli/                ← npm CLI 包（npm i -g sense-cli）
│   ├── bin/sense.js       CLI 入口
│   └── package.json
├── README.md
├── LICENSE
└── .gitignore
```

## 数据隐私

- API key 存储在本地 `.env`，不会提交到 Git
- 对话数据存储在本地 `DATA_PATH` 目录
- 使用免费模型时，数据可能被用于模型改进（详见各平台隐私政策）

## 许可证

MIT
