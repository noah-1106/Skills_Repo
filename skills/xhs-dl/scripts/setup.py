#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
xhs-dl Skill 跨平台安装脚本（Mac / Windows 通用，一套代码）

做什么:
  1. 创建 .venv（Python 内置 venv 模块）
  2. 安装依赖（按平台自动选择: Mac→ocrmac / Windows→winrt-Windows.Media.Ocr）
  3. 下载 ASR 模型 paraformer-bilingual (224MB, 国内走 hf-mirror)
  4. 验证环境就绪

用法（Mac 和 Windows 都是这一条）:
  python3 scripts/setup.py        # Mac / Linux
  python scripts/setup.py         # Windows（若 python3 不在 PATH 用 python）

注意:
  - .venv 绑定 CPU 架构, 换机器/换架构重跑本脚本即可（模型和代码通用）
  - Windows 上 OCR 用 winrt-Windows.Media.Ocr（系统级, 与 Mac Vision 同级）
"""
import os
import platform
import subprocess
import sys
import urllib.request
import venv
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
if SKILL_DIR.name == "scripts":
    SKILL_DIR = SKILL_DIR.parent

VENV_DIR = SKILL_DIR / ".venv"
MODEL_DIR = SKILL_DIR / "models" / "paraformer-bilingual"
MODEL_BASE = "https://hf-mirror.com/csukuangfj/sherpa-onnx-paraformer-bilingual-zh-en/resolve/main"
MODEL_FILES = ["model.int8.onnx", "tokens.txt"]

# Windows: .venv/Scripts/python.exe ; Mac/Linux: .venv/bin/python
def venv_python() -> Path:
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def run(cmd, **kw):
    print("  >", " ".join(str(c) for c in cmd))
    return subprocess.run([str(c) for c in cmd], **kw)


def main():
    print("=== xhs-dl Skill 首次安装（跨平台）===")
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

    # 2. 依赖（平台自动选择）
    deps = ["sherpa-onnx", "numpy"]
    if sys.platform == "darwin":
        deps.append("ocrmac")
    elif sys.platform == "win32":
        deps += [
            "winrt-Windows.Media.Ocr",
            "winrt-Windows.Graphics.Imaging",
            "winrt-Windows.Storage",
            "winrt-Windows.Storage.Streams",
        ]
    print(f"安装依赖 ({', '.join(deps)}, 2-3 分钟)...")
    run([py, "-m", "pip", "install", "--upgrade", "pip"])
    run([py, "-m", "pip", "install"] + deps)

    # 3. 模型下载
    if not (MODEL_DIR / "model.int8.onnx").exists():
        print("下载 ASR 模型 (224MB, hf-mirror, 1-5 分钟)...")
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        for f in MODEL_FILES:
            dest = MODEL_DIR / f
            if dest.exists():
                print(f"  {f} 已存在, 跳过")
                continue
            print(f"  下载 {f} ...")
            urllib.request.urlretrieve(f"{MODEL_BASE}/{f}", dest)
            print(f"    ✅ {dest.name} ({dest.stat().st_size // 1024 // 1024}MB)")
    else:
        print("模型已存在, 跳过下载")

    # 4. 验证
    print("验证环境...")
    r = run([py, "-c", "import sherpa_onnx, numpy; print('  ✅ sherpa-onnx + numpy OK')"],
            capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-500:])
        print("❌ 依赖验证失败, 检查上方报错")
        sys.exit(1)
    print(r.stdout.strip())

    ocr_pkg = "ocrmac" if sys.platform == "darwin" else ("winrt" if sys.platform == "win32" else "无(跳过OCR)")
    print(f"  OCR 包: {ocr_pkg}")
    print(f"  模型: {MODEL_DIR / 'model.int8.onnx'} ({'存在' if (MODEL_DIR / 'model.int8.onnx').exists() else '缺失!'})")

    print()
    print("✅ 安装完成。使用:")
    print("  python3 scripts/xhs.py <小红书链接>     # Mac")
    print("  python  scripts/xhs.py <小红书链接>     # Windows")


if __name__ == "__main__":
    main()
