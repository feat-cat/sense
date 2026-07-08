#!/usr/bin/env python3
"""
Sense — 多模态 AI 桥接工具
让文本 AI 调用另一个多模态 AI 理解图片/音视频，并持续对话。

用法:
  python bridge.py new --prompt "描述这张图片" --file photo.jpg
  python bridge.py continue <session_id> --prompt "文字是什么" --file next.mp4
  python bridge.py list
  python bridge.py get <session_id>
  python bridge.py delete <session_id>
  python bridge.py status
"""

import os
import sys
import json
import re
import uuid
import base64
import argparse
import mimetypes
import subprocess
import shutil
import tempfile
import atexit
import signal
from pathlib import Path
from datetime import datetime

# Windows 控制台 GBK 编码兼容：无法编码的字符用 ? 替换
if sys.platform == 'win32' and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

try:
    import requests
except ImportError:
    print("错误: 需要 requests 库。请运行: pip install requests")
    sys.exit(1)

# ============================================================
# 信号处理 & 退出清理
# ============================================================

_TEMP_FILES_TO_CLEAN = []
_FFMPEG_PROCESSES = []


def register_temp(path):
    """注册临时路径，在结束时清理"""
    _TEMP_FILES_TO_CLEAN.append(Path(path))


def cleanup_temp():
    """清理所有临时文件"""
    for p in _TEMP_FILES_TO_CLEAN:
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.is_file():
            p.unlink(missing_ok=True)


def _kill_ffmpeg_processes():
    """终止所有正在运行的 ffmpeg 子进程（防止 Ctrl+C 时变孤儿进程）"""
    for proc in list(_FFMPEG_PROCESSES):
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        _FFMPEG_PROCESSES.remove(proc)


def _run_ffmpeg(cmd, timeout=300):
    """
    运行 ffmpeg 子进程并跟踪进程引用，
    使得 Ctrl+C 时信号处理器能终止 ffmpeg 进程。
    返回 (stdout, stderr)。
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    _FFMPEG_PROCESSES.append(proc)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(
                proc.returncode, cmd, output=stdout, stderr=stderr
            )
        return stdout, stderr
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise
    finally:
        if proc in _FFMPEG_PROCESSES:
            _FFMPEG_PROCESSES.remove(proc)


def _signal_handler(signum, frame):
    _kill_ffmpeg_processes()
    cleanup_temp()
    sys.exit(1)


signal.signal(signal.SIGINT, _signal_handler)
if sys.platform != 'win32':
    signal.signal(signal.SIGTERM, _signal_handler)
atexit.register(cleanup_temp)

# ============================================================
# 全局常量
# ============================================================

TEMP_DIR = Path(tempfile.gettempdir()) / 'sense'
VERBOSE = False  # 全局详细输出开关，由 --verbose 控制

# ============================================================
# 配置加载
# ============================================================

CONFIG = {}

# 占位符 API Key 列表，用于友好提示
PLACEHOLDER_KEYS = [
    'sk-your-api-key-here',
    'your-api-key-here',
    'change_me',
    'your_api_key_here',
]


def parse_env_file(env_path):
    """手动解析 .env 文件，仅依赖标准库"""
    env_vars = {}
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, _, value = line.partition('=')
                key = key.strip()
                value = value.strip()
                # 去掉行内注释（# 及其之后的内容）
                comment_pos = value.find(' #')
                if comment_pos != -1:
                    value = value[:comment_pos].strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                env_vars[key] = value
    return env_vars


def load_config():
    """加载并验证 .env 配置"""
    env_path = Path.cwd() / '.env'
    if not env_path.exists():
        env_path = Path(__file__).parent / '.env'

    if not env_path.exists():
        print("=" * 60)
        print("  错误: 找不到 .env 配置文件！")
        print("=" * 60)
        print()
        print(f"  当前工作目录: {Path.cwd()}")
        print(f"  脚本所在目录: {Path(__file__).parent}")
        print()
        print("  请创建 .env 文件，参考 .env.example：")
        print()
        print(f"    copy {Path(__file__).parent / '.env.example'} .env")
        print(f"    或: cp {Path(__file__).parent / '.env.example'} .env")
        print()
        print("  然后编辑 .env 填入你的配置。")
        print("=" * 60)
        sys.exit(1)

    env_data = parse_env_file(env_path)

    # 必填项校验
    required = {
        'API_KEY': 'API 密钥',
        'BASE_URL': 'API 基础地址',
        'MODEL_ID': '模型 ID',
        'DATA_PATH': '对话数据存储路径',
    }

    missing = []
    for key, label in required.items():
        value = env_data.get(key, '').strip()
        if not value:
            missing.append(f"  {key} ({label})")
        CONFIG[key.lower()] = value

    if missing:
        print("=" * 60)
        print("  错误: .env 缺少以下必填配置项:")
        print("=" * 60)
        for item in missing:
            print(f"    {item}")
        print()
        print("  请参考 .env.example 补全配置。")
        print("=" * 60)
        sys.exit(1)

    # 检查 API Key 是否还是占位符
    api_key = CONFIG['api_key']
    if any(placeholder in api_key.lower() for placeholder in PLACEHOLDER_KEYS):
        print("!" * 60)
        print("  警告: API_KEY 看起来还是示例值！")
        print("!" * 60)
        print()
        print(f"  当前值: {api_key}")
        print()
        print("  请修改 .env 中的 API_KEY 为真实的 API 密钥。")
        print("=" * 60)

    # 可选配置 — 通用
    CONFIG['single_file_only'] = env_data.get('SINGLE_FILE_ONLY', 'false').lower() in (
        'true', '1', 'yes')
    raw_ext = (env_data.get('ALLOWED_EXTENSIONS') or '').strip()
    CONFIG['allowed_extensions'] = (
        raw_ext if raw_ext
        else '.jpg,.jpeg,.png,.gif,.bmp,.webp,.svg,.mp4,.mov,.avi,.mkv,.webm,.mp3,.wav,.m4a,.ogg,.flac,.pdf'
    )
    CONFIG['temperature'] = float(env_data.get('TEMPERATURE', '0.7'))
    CONFIG['max_tokens'] = int(env_data.get('MAX_TOKENS', '4096'))
    CONFIG['top_p'] = float(env_data.get('TOP_P', '1.0'))

    # 可选配置 — 视频处理模式
    CONFIG['video_mode'] = env_data.get('VIDEO_MODE', 'native').lower()
    if CONFIG['video_mode'] not in ('native', 'extract'):
        CONFIG['video_mode'] = 'native'

    # 可选配置 — ffmpeg
    CONFIG['ffmpeg_enabled'] = env_data.get('FFMPEG_ENABLED', 'true').lower() in (
        'true', '1', 'yes')
    CONFIG['video_frame_interval'] = float(env_data.get('VIDEO_FRAME_INTERVAL', '2.0'))
    CONFIG['video_max_frames'] = int(env_data.get('VIDEO_MAX_FRAMES', '10'))
    CONFIG['video_max_width'] = int(env_data.get('VIDEO_MAX_WIDTH', '1024'))
    CONFIG['audio_target_format'] = env_data.get('AUDIO_TARGET_FORMAT', 'mp3')
    CONFIG['audio_sample_rate'] = int(env_data.get('AUDIO_SAMPLE_RATE', '16000'))

    # 可选配置 — NIM 参数
    CONFIG['use_audio_in_video'] = env_data.get('USE_AUDIO_IN_VIDEO', 'true').lower() in (
        'true', '1', 'yes')

    # 确保数据目录存在
    data_path = Path(CONFIG['data_path'])
    data_path.mkdir(parents=True, exist_ok=True)
    CONFIG['data_path_abs'] = str(data_path.resolve())

    # ffmpeg 可用性检测
    CONFIG['ffmpeg_available'] = check_ffmpeg()


# ============================================================
# ffmpeg 检测
# ============================================================


def check_ffmpeg():
    """检查 ffmpeg 是否可用"""
    if not CONFIG['ffmpeg_enabled']:
        return False
    try:
        result = subprocess.run(
            ['ffmpeg', '-version'],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


# ============================================================
# ffmpeg 转码/抽帧
# ============================================================


def ensure_temp_dir():
    """确保临时目录存在"""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)


def extract_video_frames(video_path):
    """
    使用 ffmpeg 从视频中提取关键帧。
    返回 (提取出的图片路径列表, 临时目录路径)。
    """
    if not CONFIG['ffmpeg_available']:
        print("错误: ffmpeg 不可用，无法处理视频。")
        print("  请安装 ffmpeg 或将 VIDEO_MODE 设为 native。")
        sys.exit(1)

    ensure_temp_dir()
    session_temp = TEMP_DIR / str(uuid.uuid4())
    session_temp.mkdir(parents=True)

    interval = CONFIG['video_frame_interval']
    max_frames = CONFIG['video_max_frames']
    max_width = CONFIG['video_max_width']

    output_pattern = str(session_temp / 'frame_%04d.jpg')

    # Windows 兼容的 filter 表达式：逗号用反斜杠转义，防止被 ffmpeg 当作 filter 分隔符
    filter_expr = (
        f"fps=1/{interval},"
        f"scale=min({max_width}\\,iw):-2"
    )

    try:
        _run_ffmpeg(
            [
                'ffmpeg', '-i', str(video_path),
                '-vf', filter_expr,
                '-frames:v', str(max_frames),
                '-q:v', '2',
                '-y', output_pattern,
            ],
            timeout=300,
        )
    except subprocess.CalledProcessError as e:
        print(f"错误: ffmpeg 视频抽帧失败")
        print(f"  stderr: {e.stderr[:500]}")
        shutil.rmtree(session_temp, ignore_errors=True)
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print("错误: ffmpeg 视频抽帧超时（超过 300 秒）")
        shutil.rmtree(session_temp, ignore_errors=True)
        sys.exit(1)

    frames = sorted(session_temp.glob('frame_*.jpg'))

    if not frames:
        print("错误: 视频未能提取出任何帧（可能视频文件有问题）")
        shutil.rmtree(session_temp, ignore_errors=True)
        sys.exit(1)

    return frames, session_temp


def transcode_audio(audio_path):
    """
    使用 ffmpeg 将音频转码为标准格式。
    返回 (转码后的文件路径, 是否发生了转码)。
    """
    if not CONFIG['ffmpeg_available']:
        return audio_path, False

    ensure_temp_dir()
    session_temp = TEMP_DIR / str(uuid.uuid4())
    session_temp.mkdir(parents=True)

    target_format = CONFIG['audio_target_format']
    sample_rate = CONFIG['audio_sample_rate']
    output_path = session_temp / f"audio.{target_format}"

    codec_map = {
        'mp3': 'libmp3lame',
        'wav': 'pcm_s16le',
        'm4a': 'aac_at' if sys.platform == 'darwin' else 'aac',
        'ogg': 'libvorbis',
        'flac': 'flac',
    }
    codec = codec_map.get(target_format)

    try:
        cmd = [
            'ffmpeg', '-i', str(audio_path),
            '-ar', str(sample_rate),
            '-ac', '1',
            '-y',
        ]
        if codec:
            cmd += ['-c:a', codec]
        cmd.append(str(output_path))

        _run_ffmpeg(cmd, timeout=300)
    except subprocess.CalledProcessError as e:
        print(f"警告: ffmpeg 音频转码失败，将使用原始文件")
        print(f"  stderr: {e.stderr[:300]}")
        shutil.rmtree(session_temp, ignore_errors=True)
        return audio_path, False
    except subprocess.TimeoutExpired:
        print("警告: ffmpeg 音频转码超时，将使用原始文件")
        shutil.rmtree(session_temp, ignore_errors=True)
        return audio_path, False

    return output_path, True


# ============================================================
# 文件处理
# ============================================================

MIME_FALLBACK = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.gif': 'image/gif',
    '.bmp': 'image/bmp',
    '.webp': 'image/webp',
    '.svg': 'image/svg+xml',
    '.mp4': 'video/mp4',
    '.mov': 'video/quicktime',
    '.avi': 'video/x-msvideo',
    '.mkv': 'video/x-matroska',
    '.webm': 'video/webm',
    '.mp3': 'audio/mpeg',
    '.wav': 'audio/wav',
    '.m4a': 'audio/mp4',
    '.ogg': 'audio/ogg',
    '.flac': 'audio/flac',
    '.pdf': 'application/pdf',
}

# 视频扩展名常量，避免重复定义
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}


def is_video_file(file_path):
    """判断文件路径是否为视频文件"""
    return Path(file_path).suffix.lower() in VIDEO_EXTENSIONS


def _encode_file_b64(path):
    """读取文件并返回 base64 编码字符串"""
    with open(path, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')


def process_file(file_path):
    """
    处理单个文件：
    - 图片 → 直接编码
    - 视频 → 原生上传（video_url）或 ffmpeg 抽帧
    - 音频 → ffmpeg 转码 → 编码
    返回 [(type_tag, mime_type, b64_data_or_path, label), ...]
    type_tag: 'image' / 'audio' / 'video_native' / 'other'
    """
    path = Path(file_path)
    if not path.exists():
        print(f"错误: 文件不存在: {file_path}")
        sys.exit(1)

    ext = path.suffix.lower()
    allowed = [e.strip().lower() for e in CONFIG['allowed_extensions'].split(',')]
    if ext not in allowed:
        print(
            f"错误: 不支持的文件扩展名 '{ext}'。\n"
            f"允许的扩展名: {CONFIG['allowed_extensions']}"
        )
        sys.exit(1)

    file_size = path.stat().st_size
    max_size = 200 * 1024 * 1024 if CONFIG['video_mode'] == 'native' else 100 * 1024 * 1024
    if file_size > max_size:
        print(f"错误: 文件过大 ({file_size / 1024 / 1024:.1f}MB)，最大支持 {max_size // (1024*1024)}MB")
        sys.exit(1)

    mime_type, _ = mimetypes.guess_type(str(path))
    if not mime_type:
        mime_type = MIME_FALLBACK.get(ext, 'application/octet-stream')

    results = []

    if mime_type.startswith('image/'):
        b64_data = _encode_file_b64(path)
        results.append(('image', mime_type, b64_data, path.name))

    elif mime_type.startswith('video/'):
        if CONFIG['video_mode'] == 'native':
            if VERBOSE:
                print(f"  检测到视频，以原生 video_url 上传（服务端抽帧）...")
            b64_data = _encode_file_b64(path)
            results.append(('video_native', mime_type, b64_data, path.name))
        else:
            if VERBOSE:
                print(f"  检测到视频，正在用 ffmpeg 抽帧...")
            frames, temp_dir = extract_video_frames(path)
            register_temp(temp_dir)

            for i, frame_path in enumerate(frames):
                b64_data = _encode_file_b64(frame_path)
                label = f"{path.name} [第{i+1}帧]"
                results.append(('image', 'image/jpeg', b64_data, label))

    elif mime_type.startswith('audio/'):
        if VERBOSE:
            print(f"  检测到音频，正在用 ffmpeg 转码...")
        trans_path, did_transcode = transcode_audio(path)
        if did_transcode:
            register_temp(trans_path.parent)
            label = f"{path.name} (已转码为 {CONFIG['audio_target_format']})"
        else:
            label = path.name

        b64_data = _encode_file_b64(trans_path)

        trans_ext = Path(trans_path).suffix.lower()
        trans_mime, _ = mimetypes.guess_type(str(trans_path))
        if not trans_mime:
            trans_mime = MIME_FALLBACK.get(trans_ext, 'audio/mpeg')

        results.append(('audio', trans_mime, b64_data, label))

    else:
        b64_data = _encode_file_b64(path)
        results.append(('other', mime_type, b64_data, path.name))

    return results


def build_content(prompt, files):
    """构建消息内容（文本 + 文件附件），返回 (content_list, has_video)"""
    content = []
    has_video = False

    if prompt:
        content.append({"type": "text", "text": prompt})

    if files:
        all_items = []
        for f in files:
            items = process_file(f)
            all_items.extend(items)

        for type_tag, mime_type, b64_data, label in all_items:
            if type_tag == 'image':
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{b64_data}",
                    }
                })
            elif type_tag == 'video_native':
                has_video = True
                content.append({
                    "type": "video_url",
                    "video_url": {
                        "url": f"data:{mime_type};base64,{b64_data}",
                    }
                })
            elif type_tag == 'audio':
                audio_format_map = {
                    'audio/mpeg': 'mp3',
                    'audio/wav': 'wav',
                    'audio/mp4': 'mp4',
                    'audio/x-m4a': 'mp4',
                    'audio/ogg': 'ogg',
                    'audio/flac': 'flac',
                    'audio/webm': 'webm',
                }
                fmt = audio_format_map.get(mime_type, 'mp3')
                content.append({
                    "type": "input_audio",
                    "input_audio": {
                        "data": b64_data,
                        "format": fmt
                    }
                })
            else:
                content.append({
                    "type": "text",
                    "text": f"[文件: {label}，类型: {mime_type}]"
                })

    return content, has_video


# ============================================================
# 工具函数
# ============================================================


def validate_session_id(session_id):
    """校验 session_id 是否为合法 UUID 格式（防止路径遍历）"""
    try:
        uuid.UUID(session_id)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def truncate_base64(obj):
    """
    递归遍历 dict/list，将所有 base64 大段数据替换为省略标记。
    覆盖两类情况：
      - data: URI 格式（image_url / video_url）
      - 纯 base64 字符串（input_audio.data）
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str):
                if v.startswith('data:') and ';base64,' in v:
                    obj[k] = '[base64 数据已省略]'
                elif len(v) > 1000 and re.fullmatch(r'[A-Za-z0-9+/=]+', v):
                    obj[k] = f'[base64 数据已省略, {len(v)} 字符]'
            else:
                truncate_base64(v)
    elif isinstance(obj, list):
        for item in obj:
            truncate_base64(item)


def session_has_file_attachments(messages):
    """检查消息列表中是否已有文件附件"""
    for msg in messages:
        if isinstance(msg.get('content'), list):
            for item in msg['content']:
                if any(key in item for key in ('image_url', 'input_audio', 'video_url')):
                    return True
    return False


# ============================================================
# API 调用
# ============================================================


def call_api_stream(messages, has_video=False):
    """
    流式调用多模态 API，逐 token 输出到终端。
    返回 (完整响应文本, 原始响应对象) 供后续保存。
    """
    headers = {
        "Authorization": f"Bearer {CONFIG['api_key']}",
        "Content-Type": "application/json",
    }

    url = CONFIG['base_url'].rstrip('/') + '/chat/completions'

    payload = {
        "model": CONFIG['model_id'],
        "messages": messages,
        "temperature": CONFIG['temperature'],
        "max_tokens": CONFIG['max_tokens'],
        "top_p": CONFIG['top_p'],
        "stream": True,
    }

    if has_video and CONFIG['video_mode'] == 'native':
        if CONFIG['use_audio_in_video']:
            payload['mm_processor_kwargs'] = {"use_audio_in_video": True}
        payload['media_io_kwargs'] = {
            "fps": 1.0 / CONFIG['video_frame_interval'],
            "num_frames": CONFIG['video_max_frames'],
        }

    full_content = ""
    response_id = ""
    response_model = ""
    usage_data = {}

    try:
        if VERBOSE:
            print("── 模型回复 ──")
        sys.stdout.flush()

        resp = requests.post(url, headers=headers, json=payload, timeout=600, stream=True)
        resp.raise_for_status()

        # 流式读取超时保护：120 秒内无新数据则超时
        import time as _time
        _last_data_time = _time.time()
        _stream_timeout = 120

        for line in resp.iter_lines():
            # 心跳检测：长时间无数据视为连接断开
            if _time.time() - _last_data_time > _stream_timeout:
                raise requests.exceptions.Timeout(
                    f"流式响应超过 {_stream_timeout} 秒无新数据"
                )

            if not line:
                continue
            _last_data_time = _time.time()

            line = line.decode('utf-8')
            if not line.startswith('data: '):
                continue
            data_str = line[6:]  # 去掉 "data: " 前缀
            if data_str.strip() == '[DONE]':
                break

            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            if not response_id:
                response_id = chunk.get('id', '')
            if not response_model:
                response_model = chunk.get('model', '')

            choices = chunk.get('choices', [])
            if not choices:
                continue

            delta = choices[0].get('delta', {})
            finish = choices[0].get('finish_reason')

            # reasoning_content = 推理/思考过程（Nemotron thinking 模式）
            reasoning = delta.get('reasoning_content', '')
            if reasoning:
                print(f"\033[90m{reasoning}\033[0m", end='', flush=True)

            content = delta.get('content', '')
            if content:
                print(content, end='', flush=True)
                full_content += content

            # 使用量信息可能在最后一个 chunk 中
            usage = chunk.get('usage')
            if usage:
                usage_data = usage

            if finish and VERBOSE:
                print()

        # 确保回复结束后换行（非 verbose 模式下没有 ── 标记，但也要换行）
        print()
        if VERBOSE:
            print("── 回复结束 ──")
        sys.stdout.flush()

    except requests.exceptions.Timeout:
        print("\n错误: API 请求超时（超过 600 秒）")
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code
        print(f"\n错误: API 返回 HTTP {status}")
        try:
            detail = e.response.json()
            msg = detail.get('error', {}).get('message', json.dumps(detail, ensure_ascii=False))
            print(f"详情: {msg}")
        except Exception:
            print(f"详情: {e.response.text[:500]}")
        sys.exit(1)
    except requests.exceptions.ConnectionError as e:
        print(f"\n错误: 无法连接到 {CONFIG['base_url']}")
        print(f"详情: {e}")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"\n错误: API 请求失败 - {e}")
        sys.exit(1)

    # 构造一个兼容的响应对象用于保存
    response_obj = {
        "id": response_id,
        "model": response_model,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": full_content,
            },
            "finish_reason": "stop",
        }],
        "usage": usage_data,
    }

    return full_content, response_obj


# ============================================================
# 会话管理
# ============================================================


def save_session(session_id, messages, response_data):
    """保存/更新对话到文件"""
    data_path = Path(CONFIG['data_path_abs'])
    session_file = data_path / f"{session_id}.json"

    now = datetime.now().isoformat()

    if session_file.exists():
        with open(session_file, 'r', encoding='utf-8') as f:
            existing = json.load(f)
        existing['messages'] = messages
        existing['last_response'] = response_data
        existing['updated_at'] = now
        with open(session_file, 'w', encoding='utf-8') as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
    else:
        session_data = {
            "session_id": session_id,
            "model": CONFIG['model_id'],
            "created_at": now,
            "updated_at": now,
            "single_file_only": CONFIG['single_file_only'],
            "allowed_extensions": CONFIG['allowed_extensions'],
            "ffmpeg_available": CONFIG['ffmpeg_available'],
            "messages": messages,
            "last_response": response_data,
        }
        with open(session_file, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, indent=2, ensure_ascii=False)


def load_session(session_id):
    """加载已有对话（含 session_id 格式校验）"""
    if not validate_session_id(session_id):
        print(f"错误: 无效的 session_id 格式: {session_id}")
        print("  session_id 应为 UUID 格式，例如: a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        sys.exit(1)

    data_path = Path(CONFIG['data_path_abs'])
    session_file = data_path / f"{session_id}.json"

    if not session_file.exists():
        print(f"错误: 找不到对话 {session_id}")
        print(f"  查找路径: {session_file}")
        sys.exit(1)

    try:
        with open(session_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"错误: 会话文件损坏: {session_file}")
        print("  尝试用文本编辑器打开修复，或删除该文件重新开始对话。")
        sys.exit(1)


def extract_assistant_message(response):
    """从 API 响应中提取 assistant 消息，只保留 role 和 content"""
    raw = response['choices'][0]['message']
    content = raw.get('content') or ''
    # 如果 content 为空但模型给了 refusal 信息，保留 refusal
    refusal = raw.get('refusal')
    if refusal and not content:
        content = f"[模型拒绝回答] {refusal}"
    return {
        "role": "assistant",
        "content": content,
    }


# ============================================================
# 命令处理
# ============================================================


def _check_single_file_video_conflict(files):
    """
    检查 SINGLE_FILE_ONLY + VIDEO_MODE=extract + 上传视频 的冲突。
    如果启用单文件限制、又用本地抽帧模式、又传了视频 → 报错。
    """
    if not CONFIG['single_file_only'] or CONFIG['video_mode'] != 'extract':
        return
    if not files:
        return
    if any(is_video_file(f) for f in files):
        print(
            f"错误: SINGLE_FILE_ONLY=true 且 VIDEO_MODE=extract 时，"
            f"无法处理视频文件。\n"
            f"  视频抽帧会生成多张图片发给 API，违反单文件限制。\n"
            f"  建议: 将 VIDEO_MODE 设为 native，让服务端抽帧。"
        )
        sys.exit(1)


def cmd_new(prompt, files):
    """创建新对话"""
    file_count = len(files) if files else 0
    _check_single_file_video_conflict(files)
    if CONFIG['single_file_only'] and file_count > 1:
        print(
            f"错误: 当前模型 ({CONFIG['model_id']}) 仅支持每个对话上传一个文件，"
            f"但你上传了 {file_count} 个"
        )
        sys.exit(1)

    session_id = str(uuid.uuid4())
    content, has_video = build_content(prompt, files)
    messages = [{"role": "user", "content": content}]

    full_content, response_obj = call_api_stream(messages, has_video=has_video)

    assistant_message = {"role": "assistant", "content": full_content}
    messages.append(assistant_message)

    save_session(session_id, messages, response_obj)

    has_local_video = any(is_video_file(f) for f in (files or []))
    if VERBOSE:
        video_info = None
        if has_local_video:
            if CONFIG['video_mode'] == 'native':
                video_info = "视频已以原生格式上传（服务端抽帧 + 音频处理）"
            else:
                video_info = "视频已本地抽帧处理"
        if video_info:
            print(f"  {video_info}")

        usage = response_obj.get('usage', {})
        if usage:
            print(f"Token 用量: {usage}")
        print(f"模型: {CONFIG['model_id']}")

    print(f"会话 ID: {session_id}")
    return session_id


def cmd_continue(session_id, prompt, files):
    """继续已有对话"""
    file_count = len(files) if files else 0

    # 先加载会话（含 session_id 校验），以便检查历史
    session = load_session(session_id)
    messages = session['messages']

    _check_single_file_video_conflict(files)

    # SINGLE_FILE_ONLY 检查：
    #   1. 本次传了超过 1 个文件 → 直接拒绝
    #   2. 本次传了文件但会话已有文件附件 → 拒绝
    if CONFIG['single_file_only']:
        if file_count > 1:
            print(
                f"错误: 当前模型 ({CONFIG['model_id']}) 仅支持每个对话上传一个文件，"
                f"但你上传了 {file_count} 个"
            )
            sys.exit(1)
        if file_count == 1 and session_has_file_attachments(messages):
            print(
                f"错误: 当前模型 ({CONFIG['model_id']}) 每个对话全程仅支持上传一个文件，"
                f"且此对话已有文件附件，无法再上传新文件"
            )
            sys.exit(1)

    content, has_video = build_content(prompt, files)
    messages.append({"role": "user", "content": content})

    full_content, response_obj = call_api_stream(messages, has_video=has_video)

    assistant_message = {"role": "assistant", "content": full_content}
    messages.append(assistant_message)

    save_session(session_id, messages, response_obj)

    if VERBOSE:
        usage = response_obj.get('usage', {})
        if usage:
            print(f"\nToken 用量: {usage}")
    print(f"会话 ID: {session_id}")


def cmd_list():
    """列出所有对话"""
    data_path = Path(CONFIG['data_path_abs'])
    sessions = []

    for f in sorted(data_path.glob('*.json'), key=os.path.getmtime, reverse=True):
        try:
            with open(f, 'r', encoding='utf-8') as sf:
                data = json.load(sf)

            # 省略 base64 大段数据以减少内存占用
            truncate_base64(data)

            preview = ""
            for msg in data.get('messages', []):
                if msg['role'] == 'user' and isinstance(msg.get('content'), str):
                    preview = msg['content'][:100]
                    break
                elif msg['role'] == 'user' and isinstance(msg.get('content'), list):
                    for item in msg['content']:
                        if item.get('type') == 'text':
                            preview = item['text'][:100]
                            break
                    if preview:
                        break

            sessions.append({
                "session_id": data['session_id'],
                "created_at": data.get('created_at', ''),
                "updated_at": data.get('updated_at', ''),
                "model": data.get('model', ''),
                "message_count": len(data.get('messages', [])),
                "preview": preview,
            })
        except (json.JSONDecodeError, KeyError) as e:
            print(f"警告: 跳过损坏的会话文件 {f.name}: {e}", file=sys.stderr)

    print(json.dumps(sessions, indent=2, ensure_ascii=False))


def cmd_get(session_id):
    """获取对话详情（自动省略所有 base64 数据）"""
    session = load_session(session_id)
    simplified = session.copy()
    truncate_base64(simplified)
    print(json.dumps(simplified, indent=2, ensure_ascii=False))


def cmd_delete(session_id, delete_all=False):
    """删除指定对话"""
    if not session_id and not delete_all:
        print("错误: 请指定要删除的 session_id，或使用 --all 清空所有对话")
        sys.exit(1)

    if delete_all:
        if session_id:
            print(f"警告: --all 将清空所有对话，忽略指定的 session_id '{session_id}'", file=sys.stderr)
        data_path = Path(CONFIG['data_path_abs'])
        count = 0
        for f in data_path.glob('*.json'):
            f.unlink()
            count += 1
        print(f"已删除 {count} 个对话文件")
        return

    if not validate_session_id(session_id):
        print(f"错误: 无效的 session_id 格式: {session_id}")
        sys.exit(1)

    data_path = Path(CONFIG['data_path_abs'])
    session_file = data_path / f"{session_id}.json"

    if not session_file.exists():
        print(f"错误: 找不到对话 {session_id}")
        sys.exit(1)

    session_file.unlink()
    print(f"已删除对话 {session_id}")


def cmd_status():
    """显示当前配置信息"""
    info = {
        "model": CONFIG['model_id'],
        "base_url": CONFIG['base_url'],
        "data_path": CONFIG['data_path_abs'],
        "single_file_only": CONFIG['single_file_only'],
        "allowed_extensions": CONFIG['allowed_extensions'],
        "temperature": CONFIG['temperature'],
        "max_tokens": CONFIG['max_tokens'],
        "top_p": CONFIG['top_p'],
        "video_mode": CONFIG['video_mode'],
        "use_audio_in_video": CONFIG['use_audio_in_video'],
        "ffmpeg": {
            "enabled": CONFIG['ffmpeg_enabled'],
            "available": CONFIG['ffmpeg_available'],
            "video_frame_interval": CONFIG['video_frame_interval'],
            "video_max_frames": CONFIG['video_max_frames'],
            "video_max_width": CONFIG['video_max_width'],
            "audio_target_format": CONFIG['audio_target_format'],
            "audio_sample_rate": CONFIG['audio_sample_rate'],
        },
    }
    print(json.dumps(info, indent=2, ensure_ascii=False))


# ============================================================
# CLI 入口
# ============================================================


def main():
    parser = argparse.ArgumentParser(
        description="多模态 AI 桥接工具 — 从命令行调用多模态 AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s new --prompt "描述这张图片" --file cat.jpg
  %(prog)s new --prompt "分析这个视频" --file demo.mp4
  %(prog)s continue a1b2c3d4-e5f6-7890-abcd-ef1234567890 --prompt "画面里有什么文字"
  %(prog)s continue a1b2c3d4-e5f6-7890-abcd-ef1234567890 --prompt "继续分析" --file new_image.jpg
  %(prog)s list
  %(prog)s get a1b2c3d4-e5f6-7890-abcd-ef1234567890
  %(prog)s delete a1b2c3d4-e5f6-7890-abcd-ef1234567890
  %(prog)s delete --all
  %(prog)s status
        """,
    )
    parser.add_argument('--verbose', '-v', action='store_true', help='显示详细信息（文件处理、token用量等）')

    subparsers = parser.add_subparsers(dest='command', help='可用命令')

    # new
    p_new = subparsers.add_parser('new', help='创建新对话（自动生成 session_id）')
    p_new.add_argument('--prompt', '-p', required=True, help='发送给多模态 AI 的提示文本')
    p_new.add_argument('--file', '-f', nargs='*', default=[], help='要上传的文件路径（可多个，用空格分隔）')

    # continue
    p_cont = subparsers.add_parser('continue', help='继续已有对话')
    p_cont.add_argument('session_id', help='对话 ID')
    p_cont.add_argument('--prompt', '-p', required=True, help='继续对话的提示文本')
    p_cont.add_argument('--file', '-f', nargs='*', default=[], help='要上传的文件路径（可多个，用空格分隔）')

    # list
    subparsers.add_parser('list', help='列出所有对话')

    # get
    p_get = subparsers.add_parser('get', help='查看指定对话的详情')
    p_get.add_argument('session_id', help='对话 ID')

    # delete
    p_del = subparsers.add_parser('delete', help='删除指定对话（或 --all 清空所有）')
    p_del.add_argument('session_id', nargs='?', default=None, help='对话 ID')
    p_del.add_argument('--all', action='store_true', help='清空所有对话')

    # status
    subparsers.add_parser('status', help='显示当前配置')

    args = parser.parse_args()

    # 设置全局详细输出开关
    global VERBOSE
    VERBOSE = args.verbose

    if not args.command:
        parser.print_help()
        sys.exit(1)

    load_config()

    if args.command == 'new':
        cmd_new(args.prompt, args.file)
    elif args.command == 'continue':
        cmd_continue(args.session_id, args.prompt, args.file)
    elif args.command == 'list':
        cmd_list()
    elif args.command == 'get':
        cmd_get(args.session_id)
    elif args.command == 'delete':
        cmd_delete(args.session_id, delete_all=args.all)
    elif args.command == 'status':
        cmd_status()


if __name__ == '__main__':
    main()
