#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scribe Skill 跨平台安装脚本（Mac / Windows 通用，一套代码）

做什么:
  1. 创建 .venv（Python 内置 venv 模块）
  2. 安装依赖（funasr + torch + fastapi 等，requirements.txt）
  3. 下载 ASR 模型（SenseVoice-Small 897MB + FSMN-VAD + CAM++，modelscope 国内源）
  4. 验证环境就绪

用法:
  python3 scripts/setup.py        # Mac / Linux
  python scripts/setup.py         # Windows

注意:
  - .venv 绑定 CPU 架构, 换机器/换架构重跑本脚本即可（模型和代码通用）
  - 模型下载走 modelscope（阿里, 国内快）；首次约 10-20 分钟（视网速）
  - 服务端无 OCR 平台分支（纯 CPU 推理, Mac/Windows 均可）
"""
import os
import platform
import subprocess
import sys
import venv
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
if SKILL_DIR.name == "scripts":
    SKILL_DIR = SKILL_DIR.parent

VENV_DIR = SKILL_DIR / ".venv"
MODELS_DIR = SKILL_DIR / "models"
REQ = SKILL_DIR / "requirements.txt"

# modelscope 模型 ID → 本地目录（与 server.py/transcribe.py 的 models/ 路径一致）
MODELS = [
    ("iic/SenseVoiceSmall", "SenseVoiceSmall"),
    ("iic/speech_fsmn_vad", "speech_fsmn_vad"),
    ("iic/speech_campplus_sv_zh-cn_16k-common", "campplus_sv"),
]


def venv_python() -> Path:
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def run(cmd, **kw):
    print("  >", " ".join(str(c) for c in cmd))
    return subprocess.run([str(c) for c in cmd], **kw)


def main():
    print("=== scribe Skill 首次安装（跨平台）===")
    print(f"Skill 根 : {SKILL_DIR}")
    print(f"平台    : {platform.system()} {platform.machine()}")
    print(f"Python  : {sys.version.split()[0]}")

    # 1. venv
    if not (VENV_DIR / ("Scripts" if sys.platform == "win32" else "bin")).exists():
        print("创建 .venv ...")
        venv.create(str(VENV_DIR), with_pip=True)
    else:
        print(".venv 已存在, 跳过创建")

    py = venv_python()

    # 2. 依赖
    print("安装依赖 (funasr/torch/fastapi 等, 视网速 5-15 分钟)...")
    run([py, "-m", "pip", "install", "--upgrade", "pip"])
    run([py, "-m", "pip", "install", "-r", str(REQ)])
    # modelscope 用于模型下载
    run([py, "-m", "pip", "install", "modelscope"])

    # 3. 模型下载（已存在则跳过）
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    for model_id, local_name in MODELS:
        local_dir = MODELS_DIR / local_name
        if (local_dir / "configuration.json").exists():
            print(f"模型 {local_name} 已存在, 跳过")
            continue
        print(f"下载模型 {model_id} → {local_dir} ...")
        r = run([py, "-m", "modelscope", "download", "--model", model_id,
                 "--local_dir", str(local_dir)])
        if r.returncode != 0:
            print(f"⚠️ 模型 {local_name} 下载失败, 可重跑本脚本续传")

    # 4. 验证
    print("验证环境...")
    r = run([py, "-c", "import funasr, fastapi, uvicorn; print('  ✅ funasr + fastapi + uvicorn OK')"],
            capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-500:])
        print("❌ 依赖验证失败, 检查上方报错")
        sys.exit(1)
    print(r.stdout.strip())

    print()
    print("✅ 安装完成。启动服务:")
    print("  python3 scripts/start.py        # Mac / Linux")
    print("  python  scripts/start.py        # Windows")
    print("  然后浏览器打开 http://localhost:8399  (录音页)")
    print("  Agent 调用: python3 scripts/scribe.py <音频文件> [--diarize]")


if __name__ == "__main__":
    main()
