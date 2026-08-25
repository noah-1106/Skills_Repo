# scribe Skill — API 文档

服务常驻 `http://localhost:8399`（SCRIBE_PORT 可改）。启动：`python3 scripts/start.py --detach`。

## 端点

### GET /api/health
服务状态。`ok: true` 表示模型就绪可转写。
```json
{"ok": true, "base_dir": "...", "tmpdir": "...", "disk_free_gb": 857.5,
 "model_load_seconds": 2.9, "decoder": "ffmpeg", "decoder_path": "...",
 "asr_model": "SenseVoice-Small (pt, 897MB)", "vad_model": "FSMN-VAD",
 "sv_model": "CAM++ (28MB, 未加载)"}
```

### POST /api/transcribe
上传音频/视频转写。
- 请求：`multipart/form-data`，字段 `file`（音频/视频文件）
- Query：`?diarize=true`（可选，说话人标记；CAM++ 懒加载）
- 响应：
```json
{"job_id": "1787634087177", "project": "会议录音", "source": "会议录音.m4a",
 "duration_s": 15.1, "infer_s": 1.8, "rtf": 0.118, "diarize": false,
 "n_speakers": 0,
 "sentences": [{"start": 0.09, "end": 10.41, "text": "大家好，..."}],
 "downloads": {
   "txt": "/api/download/会议录音/1787634087177.txt",
   "srt": "/api/download/会议录音/1787634087177.srt",
   "json": "/api/download/会议录音/1787634087177.json"}}
```

### GET /api/download/{name:path}
下载产物。name 是 downloads 里给的相对路径（需拼 host）。

### GET /api/projects
历史转写项目列表。

### WS /ws/live
实时录音转写（浏览器 MediaRecorder 推流 → 流式 VAD → 段闭合识别）。浏览器录音页用。

## 产物格式

| 格式 | 内容 |
|---|---|
| TXT | `[00:00:00] 句子`（带时间戳，可选 `说话人 N: ` 前缀） |
| SRT | 标准字幕（序号 + 时间轴 + 文本） |
| JSON | 结构化（project/source/duration_s/diarize/sentences[{start,end,text,speaker}]） |

## 客户端（scripts/scribe.py）

```
python3 scribe.py <文件> [--diarize] [--format txt|srt|json|all] [--out DIR]
python3 scribe.py --status      # 查看服务状态
python3 scribe.py --start       # 启动服务并等待就绪
```

自动流程：ensure_server（没起就 spawn + 轮询 health ≤180s）→ 上传转写 → 下载产物 → 打印摘要。
