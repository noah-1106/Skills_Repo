---
name: scribe
description: |
  本地录音转写工具：音频/视频文件 → 带时间戳的文字稿（TXT/SRT/JSON），可选说话人标记。
  每当用户提到以下场景，务必使用本技能（即使没提工具名）：
  - 用户提供音频/视频文件（m4a/wav/mp3/mp4/会议录音/采访/语音备忘录/口播），要求"转写""出文字稿""整理成文字""会议纪要""字幕"
  - 用户说"帮我转写这个录音""这段采访整理成文档""把口播变成文字"
  - 用户要求"录音转写"且愿意在浏览器录音页录音（http://localhost:8399，人录机转）
  本技能自包含：代码全在 skill 内；首次运行 setup.py 自动装依赖（funasr+torch）并下载模型（SenseVoice 897MB，modelscope 国内源）。
  服务常驻 http://localhost:8399：首次加载模型约 3-15 秒，之后转写秒级（RTF≈0.1，10 倍实时）。
compatibility: "Mac 已验证（Apple Silicon）。Windows 代码层兼容（venv 由 setup.py 重建，funasr 支持 Windows），待真机验证。纯 CPU 推理，无需 GPU。系统依赖：ffmpeg（音频解码，brew/官网安装）。"
---

# scribe — 本地录音转写

音频/视频 → 带时间戳文字稿。全本地、常驻服务、Agent 可自动调用。

## 快速使用（Skill 自包含，无需外部项目）

```bash
# 首次安装（新机器/新环境，一次）——建 venv + 装 funasr/torch + 下载模型 897MB
python3 scripts/setup.py

# 启动服务（常驻，http://localhost:8399）
python3 scripts/start.py --detach

# Agent 调用（上传转写 + 下载留存，一条命令）
python3 scripts/scribe.py 会议录音.m4a --diarize --format all --out ~/输出目录
```

## 三种入口（同一服务）

| 入口 | 谁用 | 干什么 |
|---|---|---|
| `scripts/scribe.py` | **Agent** | 上传文件转写 + 下载 TXT/SRT/JSON 留存（全自动闭环） |
| 浏览器 `http://localhost:8399` | **人** | 实时/上传录音（页面录音，人录机转） |
| `scripts/transcribe.py` | CLI | 直接转写文件（不经过服务） |

## Agent 调用闭环（核心用法）

```
用户丢录音文件
  → python3 scripts/scribe.py <文件> [--diarize] [--format txt|srt|json|all] [--out DIR]
      → ① 检测服务没起 → 自动启动并等待就绪（≤180s）
      → ② POST /api/transcribe 上传 → 转写
      → ③ GET /api/download 下载产物 → 存到 --out
  → Agent 读 TXT/JSON 做会议纪要/存档/知识库留存
```

## API（Agent 直接调用也行）

```
GET  /api/health         # 服务状态（ok/base_dir/disk_free_gb/模型信息）
POST /api/transcribe     # multipart: file=音频; query: ?diarize=true（说话人标记）
GET  /api/download/{项目}/{文件}.txt|srt|json   # 下载产物
GET  /api/projects       # 历史转写项目
WS   /ws/live            # 实时录音转写（浏览器用）
```

## 首次环境搭建（唯一前置）

```bash
cd ~/.exflower/skills/scribe
python3 scripts/setup.py
# 做什么: ① 建 .venv + 装依赖（funasr/torch/fastapi，5-15 分钟）
#         ② 下载模型 SenseVoice-Small 897MB + FSMN-VAD + CAM++（modelscope 国内源）
#         ③ 验证环境就绪
```

- `.venv` 绑定 CPU 架构：换机器/换架构重跑 setup.py（模型和代码通用）
- 模型走 modelscope（阿里，国内快）；断网可重跑续传
- 服务端无 OCR 平台分支，纯 CPU 推理 Mac/Windows 均可

## 执行要点（为什么这么做）

1. **服务常驻而非每次现转**：模型加载 3-15 秒，之后秒级响应——start.py 拉起后一直挂着（日志 data/server.log）
2. **scribe.py 自动管理服务**：没起就 spawn + 轮询 health，Agent 无需关心服务状态
3. **diarize 是 query 参数**（?diarize=true），不是 form 字段（FastAPI 坑，已踩）
4. **产物三格式**：TXT（带时间戳句子）/ SRT（字幕）/ JSON（结构化 sentences 含起止秒）
5. **转写质量**：SenseVoice 中文强；英文词偶发不准（"AI"→"爱"）——重要英文术语建议画面/人工校对

## 已知坑（详见 references/已知坑.md）

- Python 3.9 注解要 `from __future__ import annotations`
- CAM++ "Loading remote code failed" 是无害警告（回退内置类，实测加载成功）
- TTS 合成音频声纹区分度低，说话人聚类可能归并；真人音频区分可靠
- 上传临时文件/缓存钉在 skill 内 data/（不写系统盘）

## 系统依赖

| 依赖 | 谁负责 | 说明 |
|---|---|---|
| Python 3.9+ | 接收方 | 唯一硬前置 |
| ffmpeg | 接收方系统安装 | 音频解码（brew/官网） |
| 模型 897MB | setup.py 下载 | modelscope 国内源 |
