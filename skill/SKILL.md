---
name: sense
description: 多模态 AI 桥接技能。让文本 AI 调用另一个多模态 AI（支持图片/音视频理解），自动管理多轮对话会话，支持持续追问。当用户需要分析图片、音频、视频，或需要与一个专门的视觉/多模态模型对话时使用。
version: 1.0.0
agents:
  - opencode
  - claude
  - cursor
  - cline
tags:
  - multimodal
  - vision
  - audio
  - video
  - bridge
---

# Sense — 多模态 AI 桥接技能

## 概述

本技能让 **文本 AI** 能够调用另一个 **多模态 AI** 来理解图片、音频、视频，并**持续对话追问细节**。

工作流程：
```
你（文本 AI）──→ bridge.py ──→ 多模态 AI API（如 Nemotron, GPT-4o, Gemini 等）
                        │
                        ├── 视频：原生 video_url 上传（服务端抽帧）
                        │    或 ffmpeg 本地抽帧（兼容模式）
                        ├── 音频：ffmpeg 转码为标准格式
                        └──→ 自动管理对话会话（session）
                             每轮对话保存到本地文件
```

视频处理流程（原生模式，推荐）：
```
.mp4 视频
    └──→ base64 编码 → video_url 发送给 API
         → 服务端（NVIDIA NIM）自动抽帧 + EVS 视频压缩
         → 同时处理视频中的音频轨道（如果 USE_AUDIO_IN_VIDEO=true）
```

视频处理流程（抽帧模式，兼容）：
```
.mp4 视频
    └──→ ffmpeg 按间隔抽帧 ──→ frame_0001.jpg
                               ├── frame_0002.jpg
                               ├── frame_0003.jpg  ← 全部作为 image_url 发送
                               └── ...
```

音频处理流程：
```
.mp3 / .wav / .m4a 等
    └──→ ffmpeg 转码为标准格式 ──→ audio.mp3 ← 作为 input_audio 发送
```

## 两种使用方式

本 skill 提供两种调用方式，AI 可根据环境选择：

| 方式 | 命令 | 安装要求 | 适用场景 |
|------|------|----------|----------|
| **CLI（推荐）** | `sense new --file photo.jpg` | `npm i -g @feat-cat/sense` | 任意目录直接调用，最方便 |
| **Python 直调** | `python bridge.py new --file photo.jpg` | `pip install requests` | 未安装 npm 时，需 cd 到 skill 目录 |

**优先使用 CLI 方式**（`sense <command>`），AI 不需要知道文件路径，从任何目录都能运行。

---

## 前置条件

### 1. 安装 CLI（推荐）

```bash
npm i -g @feat-cat/sense
```

也可以直接用 npx（无需安装）：

```bash
npx @feat-cat/sense <command> ...
```

### 2. 安装 Python 依赖

```bash
pip install requests
```

### 3. 配置 `.env`

在本 skill 目录下创建 `.env` 文件，参考 `.env.example`：

```bash
# 在本 skill 目录下执行
cp .env.example .env
# 或 (Windows)
copy .env.example .env
```

**必填配置：**

| 配置项 | 说明 | 示例 |
|--------|------|------|
| `API_KEY` | 多模态 AI 的 API 密钥 | `sk-xxxxx` |
| `BASE_URL` | API 基础地址 | `https://api.openai.com/v1` |
| `MODEL_ID` | 模型 ID | `gpt-4o`, `gemini-2.0-flash-exp` |
| `DATA_PATH` | 对话数据存储路径 | `./conversations` |

**可选配置：**

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `SINGLE_FILE_ONLY` | 是否只允许每个对话全程上传 1 个文件 | `false` |
| `ALLOWED_EXTENSIONS` | 允许的文件扩展名 | `图片/视频/音频常见格式` |
| `TEMPERATURE` | 模型温度 | `0.7` |
| `MAX_TOKENS` | 最大输出 token | `4096` |
| `TOP_P` | Top-p 采样 | `1.0` |
| `VIDEO_MODE` | 视频处理模式：`native` 或 `extract` | `native` |
| `USE_AUDIO_IN_VIDEO` | 是否同时处理视频中的音频 | `true` |
| `FFMPEG_ENABLED` | 是否启用 ffmpeg | `true` |
| `VIDEO_FRAME_INTERVAL` | 视频抽帧间隔（秒） | `2.0` |
| `VIDEO_MAX_FRAMES` | 视频最大帧数 | `10` |
| `VIDEO_MAX_WIDTH` | 视频帧最大宽度（px） | `1024` |
| `AUDIO_TARGET_FORMAT` | 音频转码格式 | `mp3` |
| `AUDIO_SAMPLE_RATE` | 音频采样率 | `16000` |
| `OPENCLAW_MEDIA_DIR` | `media://` 伪路径的根目录，支持 `~` | 自动搜索 `~/.openclaw/media/` |

### 3. 视频模式说明

两种视频模式：

| 模式 | 配置值 | 工作原理 | 适用场景 |
|------|:------:|----------|----------|
| **原生**（推荐） | `native` | 上传原始 MP4，服务端（NIM）自动抽帧 + 音频处理 | NVIDIA NIM / 支持 video_url 的端点 |
| **抽帧** | `extract` | 本地 ffmpeg 抽帧，以多张图片发送 | 普通 OpenAI 兼容端点 |

`VIDEO_MODE=native` 时，还会自动传递 NIM 扩展参数：
- `mm_processor_kwargs.use_audio_in_video` — 同时处理视频中的音频
- `media_io_kwargs.fps / num_frames` — 控制服务端抽帧密度

### 4. BASE_URL 说明

`BASE_URL` 需要**用户提供完整路径**，脚本直接拼接 `/chat/completions`。例如：

| BASE_URL | 最终请求地址 |
|----------|-------------|
| `https://api.openai.com/v1` | `https://api.openai.com/v1/chat/completions` |
| `https://api.deepinfra.com/v1/openai` | `https://api.deepinfra.com/v1/openai/chat/completions` |
| `http://localhost:8000/v1` | `http://localhost:8000/v1/chat/completions` |

### 5. FFmpeg 说明

如果 `FFMPEG_ENABLED=true` 且系统安装了 ffmpeg：
- **视频（extract 模式）**：自动抽帧为图片发送
- **音频**：自动转码为标准格式（默认 mp3），作为 `input_audio` 发送

如果 ffmpeg 不可用或 `FFMPEG_ENABLED=false`：
- 视频（extract 模式）**报错退出**
- 音频**直接发送原文件**

### 6. `.env` 未配置时的行为

如果 `.env` **不存在** 或 **缺少必填项**，脚本会直接报错退出并提示缺少了哪些配置项。**请务必告知用户检查 `.env` 配置。**

### 7. `media://` 伪路径支持

某些 AI 平台（如 OpenClaw）发送媒体文件时，AI 看到的是 `media://<相对路径>` 这样的伪 URL。

bridge.py 会自动解析 `media://` 路径：
1. 如果 `.env` 设置了 `OPENCLAW_MEDIA_DIR`，则以该目录为根查找（支持 `~`）
2. 否则自动搜索默认位置：
   - `~/.openclaw/media/`
   - `~/.openclaw/workspace/media/`（Docker sandbox 模式）

**使用场景（以 OpenClaw 为例）：**
- AI 从对话上下文获取 `media://inbound/xxx.jpg` 路径
- 直接传给 `sense new --file "media://inbound/xxx.jpg" "描述这张图片"`
- bridge.py 自动映射到真实文件，无需手动处理

**不配置也能工作**（只要文件在默认位置）。如果平台使用了自定义媒体目录，才需要设置 `OPENCLAW_MEDIA_DIR`。

---

## 使用方法

优先使用 `sense` CLI 命令（需安装 `npm i -g @feat-cat/sense`），从任意目录直接调用。如未安装 CLI，可 `cd` 到本 skill 目录后用 `python bridge.py <command>`。

### 1. 创建新对话（分析文件）

当用户上传图片/音频/视频并要求分析时：

```bash
# 推荐：用 sense 命令（从任意目录执行）
sense new --prompt "描述这张图片的内容" --file photo.jpg

# 也可用 npx（无需安装）
npx @feat-cat/sense new --prompt "描述这张图片的内容" --file photo.jpg

# 或用 Python 直接调用
# cd <skill目录> && python bridge.py new --prompt "..." --file photo.jpg

# 分析多个文件（需 SINGLE_FILE_ONLY=false）
sense new --prompt "对比这两张图片" --file img1.jpg img2.jpg

# 仅文本对话（不上传文件）
sense new --prompt "你好，请介绍一下你自己"
```

返回结果示例：
```json
{
  "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "response": "这是一张夕阳下的海滩照片...",
  "usage": { "prompt_tokens": 120, "completion_tokens": 80, "total_tokens": 200 },
  "model": "gpt-4o",
  "single_file_only": false
}
```

**重要：** 将 `session_id` 记录下来，后续追问需要使用。

### 2. 继续对话（追问细节）

当用户对之前的结果进行追问时：

```bash
# 继续对话（不传新文件）
sense continue <session_id> --prompt "画面里的人物在做什么？"

# 继续对话（上传新文件）
sense continue <session_id> --prompt "这张图里有什么不同？" --file new_angle.jpg
```

> **注意**: 如果 `SINGLE_FILE_ONLY=true`，已包含文件的对话无法再上传新文件。

### 3. 查看所有对话

```bash
sense list
```

### 4. 查看某个对话的完整历史

```bash
sense get <session_id>
```

### 5. 删除对话

```bash
# 删除指定对话
sense delete <session_id>

# 清空所有对话
sense delete --all
```

### 6. 查看当前配置状态

```bash
sense status
```

---

## 关键约束说明

### 单文件限制 (`SINGLE_FILE_ONLY`)

- 如果 `.env` 中 `SINGLE_FILE_ONLY=true`，则**每个对话全程只能上传 1 个文件**
- 这意味着：一旦在某轮上传了一个文件，后续所有追问轮次**不能再上传新文件**
- 如果违反此限制，脚本会报错
- **特别地**：`SINGLE_FILE_ONLY=true` 且 `VIDEO_MODE=extract` 时，视频文件会被拒绝（抽帧会产生多张图片，违反限制）。必须改用 `VIDEO_MODE=native`
- **使用本 skill 的 AI 应当注意：当 SINGLE_FILE_ONLY=true 时，告知用户每个对话全程只能分析一个文件，并在用户上传多个文件时提示此限制**

### 文件类型限制

只允许 `ALLOWED_EXTENSIONS` 中定义的文件类型，默认支持：
- 图片: `.jpg`, `.jpeg`, `.png`, `.gif`, `.bmp`, `.webp`, `.svg`
- 视频: `.mp4`, `.mov`, `.avi`, `.mkv`, `.webm`
- 音频: `.mp3`, `.wav`, `.m4a`, `.ogg`, `.flac`
- 文档: `.pdf`

### 文件大小限制

- 原生视频模式：最大 **200MB**
- 其他模式：最大 **100MB**

### 视频处理说明

**原生模式（`VIDEO_MODE=native`，推荐）：**
- 整个 MP4 视频以 `video_url` 类型上传
- 服务端（NVIDIA NIM）自动完成：抽帧、Efficient Video Sampling (EVS) 压缩、音频提取
- 可通过 `USE_AUDIO_IN_VIDEO=true` 开启视频中的音频理解
- 服务端默认以 2 FPS 采样，可通过 `media_io_kwargs` 控制

**抽帧模式（`VIDEO_MODE=extract`）：**
- 本地 ffmpeg 按 `VIDEO_FRAME_INTERVAL` 秒间隔抽取关键帧
- 例如 30 秒视频，间隔 2 秒 → 抽最多 10 帧
- 每帧缩放到 `VIDEO_MAX_WIDTH` 宽度
- 所有帧作为 `image_url` 发送

### 音频处理说明

上传音频时，ffmpeg 会转码为标准格式：
- 默认转码为 **单声道 16kHz mp3**
- 转码失败时回退到原始文件

---

## AI 使用此 Skill 的最佳实践

当用户请求涉及图片/音视频分析时，请遵循以下流程：

### 流程

0. **识别 `media://` 伪路径**
   - 如果用户传来的文件路径以 `media://` 开头（如在 OpenClaw 中），**直接使用该路径**
   - 示例: `sense new --file "media://inbound/abc123.jpg" "描述这张图片"`
   - bridge.py 会自动将 `media://` 映射到磁盘上的真实文件

1. **检查 `.env` 是否已配置**
   - 如果未配置，引导用户参考 `.env.example` 进行配置
   - 执行 `sense status` 快速验证，如果报错则引导用户创建 `.env`

2. **使用 `new` 命令开启新对话**
   - 每次用户提出新的分析需求，使用 `new`
   - 将返回的 `session_id` 记录下来

3. **使用 `continue` 命令处理追问**
   - 用户对同一文件/话题继续提问时，使用 `continue <session_id>`
   - 如果 `SINGLE_FILE_ONLY=true`，追问时不能再传新文件

4. **告知用户会话 ID**
   - 告知用户 session_id，以便后续可以继续对话
   - 示例: "本次分析的会话 ID 是 `xxxx`，你可以记住这个 ID，后续可以继续追问"

### 处理 `SINGLE_FILE_ONLY=true` 的对话示例

```
用户: 分析这张图片 （上传了 1 张图）
你:  使用 sense new --prompt "分析这张图片" --file image.jpg
     → 得到 session_id 和 AI 回复

用户: 再看看这张 （上传了第 2 张图）
你:  由于当前模型设置为 SINGLE_FILE_ONLY=true，每个对话全程只能分析一个文件。
     你需要开启一个新的对话来分析这张新图片。
     使用 sense new --prompt "分析这张图片" --file image2.jpg
```

### 处理 `SINGLE_FILE_ONLY=false` 的对话示例

```
用户: 对比这两张图片 （上传了 2 张图）
你:  使用 sense new --prompt "对比这两张图片" --file img1.jpg img2.jpg
     → 得到 session_id

用户: 再放大看看这个细节 （上传了 1 张新图）
你:  使用 sense continue <session_id> --prompt "放大看这个细节" --file detail.jpg
```

---

## 文件结构

安装后的结构（在 `.agents/skills/sense/` 或 `~/.agents/skills/sense/` 下）：

```
sense/
├── SKILL.md           ← 本文件（AI 使用指引）
├── bridge.py           ← 核心 Python 脚本
├── .env.example        ← 配置模板
├── .env                ← 实际配置（用户创建，cp .env.example .env）
└── conversations/      ← 对话数据（自动生成）
```

Repo 完整结构（含 CLI）：

```
feat-cat/sense/
├── skill/              ← skill 本体（npx skills add 安装的目录）
│   ├── SKILL.md
│   ├── bridge.py
│   └── .env.example
├── cli/                ← npm CLI（npm i -g @feat-cat/sense）
│   ├── bin/sense.js
│   └── package.json
├── README.md
├── LICENSE
├── .gitignore
└── agent-skills.json
```

## 数据存储

每次对话都以 JSON 文件保存在 `DATA_PATH` 目录下，文件名 = `{session_id}.json`，包含完整的对话历史。可以使用 `get` 命令查看（base64 数据会被省略以保持可读性）。
