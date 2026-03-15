---
name: ec_creator
version: 1.1.0
description: |
  Execution Card Linter & Validator with Auto-Fix | 执行卡片检查与自动修复工具
  A validation and correction tool for creating standardized Execution Cards. | 创建标准化执行卡片的验证和修正工具
---

# EC Creator Skill | EC 创建技能

> **Version: 1.1.0** | Execution Card Linter & Validator with Auto-Fix | 执行卡片检查与自动修复工具

A validation and correction tool for creating standardized Execution Cards. | 创建标准化执行卡片的验证和修正工具。

---

## What's New in v1.1.0 | v1.1.0 新特性

- **Python-based**: Data-driven validation using JSON rules (no hard-coding) | 使用JSON规则的数据驱动验证（无硬编码）
- **Auto-Fix Suggestions**: Returns copy-pasteable Markdown snippets for common issues | 返回可复制的Markdown片段用于常见问题
- **Real Skill Scanning**: Actually checks `~/.openclaw/skills/` directory for skill existence | 实际检查 `~/.openclaw/skills/` 目录中的技能存在性
- **Enhanced Error Messages**: More actionable guidance | 更具操作性的指导

---

## What This Skill Does | 此技能功能

EC Creator transforms draft workflow descriptions into production-ready Execution Cards through automated validation and iterative correction. | EC Creator 通过自动化验证和迭代修正，将工作流草稿转换为生产就绪的执行卡片。

**Core Workflow / 核心工作流:**
```
Draft (temp_draft.md) → Lint → Fix → Validate → Standard EC (EC-XXX.md)
草稿 (temp_draft.md) → 检查 → 修复 → 验证 → 标准 EC (EC-XXX.md)
```

---

## Core Functions | 核心功能

### 1. Structure Integrity Scan | 结构完整性扫描

Validates logical blocks are complete: | 验证逻辑块是否完整：

| Block / 模块 | Check / 检查 | Error if Missing / 缺失时错误 |
|-------------|--------------|------------------------------|
| **Resource Dependencies / 资源依赖** | Lists required skills/tools | "Agent may hallucinate unavailable tools" / "Agent可能幻觉不存在的工具" |
| **Execution Workflow / 执行工作流** | Numbered step list | "Non-sequential, hard to parse" / "非顺序，难以解析" |
| **Execution Conventions / 执行约定** | I/O paths defined | "Cross-agent collaboration fails" / "跨Agent协作失败" |

### 2. Path Vitality Check | 路径活力检查

Scans and validates all paths in the EC: | 扫描并验证EC中的所有路径：

```bash
# Checks / 检查:
- Resource paths: Do files exist? / 资源路径：文件是否存在？
- Output directories: Are they writable? / 输出目录：是否可写？
- Template references: Are they valid? / 模板引用：是否有效？

# Example Output / 示例输出:
[FAIL] Template POST_TEMPLATE.md not found in workspace / 模板未找到
[PASS] Output directory posts/ exists and is writable / 输出目录存在且可写
```

### 3. Semantic Polish | 语义润色

Keyword-based sanity checks: | 基于关键词的合理性检查：

| Keywords Found / 发现的关键词 | Warning if Missing / 缺失时警告 |
|------------------------------|--------------------------------|
| "upload", "post", "send" | No network/API skill in dependencies / 依赖中无网络/API技能 |
| "read", "write", "save" | No file system skill declared / 未声明文件系统技能 |
| "error", "fail", "retry" | No error handling section / 无错误处理章节 |
| "if", "check", "validate" | No input validation steps / 无输入验证步骤 |

---

## Usage | 使用方式

### Command Line | 命令行

```bash
# Validate a draft EC / 验证EC草稿
ec_linter ExCard/temp_draft.md

# Output / 输出:
# [INFO] Scanning temp_draft.md...
# [WARN] Missing Resource Dependencies section / 缺少资源依赖章节
# [ERROR] Output path posts/ does not exist / 输出路径不存在
# [FAIL] 1 error, 1 warning found / 1个错误，1个警告

# After fixing, run again / 修复后重新运行:
ec_linter ExCard/temp_draft.md
# [PASS] All checks passed. Ready to rename to EC-XXX.md / 所有检查通过
```

### In Agent Workflow | 在Agent工作流中

**Phase 1: Observation / 阶段1：观察**
Agent records successful operations in `ExCard/temp_draft.md` | Agent记录成功操作到 `ExCard/temp_draft.md`

**Phase 2: Initial Structuring / 阶段2：初始结构化**
Agent formats draft according to template | Agent按模板格式化草稿

**Phase 3: Lint & Validate / 阶段3：检查与验证**
```
Agent: Run ec_linter ExCard/temp_draft.md / 运行检查器
Linter: [FAIL] Missing Input conventions / 缺少输入约定
Agent: Edit file, add Input section / 编辑文件，添加输入章节
Agent: Run ec_linter again / 再次运行检查器
Linter: [PASS] / 通过
```

**Phase 4: Activate / 阶段4：激活**
Rename to `EC-005-descriptive-name.md` | 重命名为 `EC-005-描述性名称.md`

---

## Validation Rules | 验证规则

### Rule 1: Required Sections | 规则1：必需章节

Must have these Markdown H2 sections: | 必须包含以下Markdown H2章节：
- `## Resource Dependencies` / `## 资源依赖`
- `## Execution Workflow` / `## 执行工作流`
- `## Execution Conventions` / `## 执行约定`

### Rule 2: Numbered Steps | 规则2：编号步骤

Execution Workflow must use numbered list (1., 2., 3.) | 执行工作流必须使用编号列表

```markdown
## Execution Workflow / ## 执行工作流
1. Read input file / 读取输入文件
2. Process data / 处理数据
3. Save output / 保存输出
```

### Rule 3: Path Verification | 规则3：路径验证

All paths must be: | 所有路径必须：
- Relative (not absolute) / 相对路径（非绝对路径）
- Within workspace / 在工作空间内
- Properly formatted / 格式正确

### Rule 4: Dependency Declaration | 规则4：依赖声明

Every external tool/skill must be listed in Resource Dependencies | 每个外部工具/技能必须在资源依赖中列出

### Rule 5: Error Handling | 规则5：错误处理

Must have at least one of: | 必须至少包含以下之一：
- Error handling steps / 错误处理步骤
- Retry logic / 重试逻辑
- Failure recovery procedure / 故障恢复程序

---

## Output Format | 输出格式

```
EC Linter Report / EC检查报告
================
File / 文件: ExCard/temp_draft.md
Status / 状态: [PASS] / [FAIL] / [WARN]

Structure Check / 结构检查:
  [✓] Resource Dependencies / 资源依赖
  [✓] Execution Workflow / 执行工作流
  [✗] Execution Conventions / 执行约定 (missing I/O paths / 缺少I/O路径)

Path Check / 路径检查:
  [✓] Input: data/input.csv
  [✗] Template: templates/missing.md (not found / 未找到)

Semantic Check / 语义检查:
  [WARN] Steps mention 'upload' but no network skill declared / 步骤提到上传但未声明网络技能
  [WARN] No error handling detected / 未检测到错误处理

Next Steps / 下一步:
  1. Add missing Execution Conventions section / 添加缺失的执行约定章节
  2. Create templates/missing.md or fix path / 创建模板或修复路径
  3. Add error handling steps or retry logic / 添加错误处理或重试逻辑
```

---

## Integration with OpenExCard | 与OpenExCard集成

```
┌─────────────────────────────────────────┐
│     Agent observes workflow / Agent观察工作流      │
│     Records in temp_draft.md / 记录到temp_draft.md  │
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│   Agent formats using template / Agent使用模板格式化  │
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│   EC Creator Skill (ec_linter) / EC创建技能        │
│  ┌──────────────┬──────────────┐       │
│  │ Structure    │ Path         │       │
│  │ Scan / 结构  │ Vitality /   │       │
│  │    扫描      │   路径活力    │       │
│  └──────────────┴──────────────┘       │
│              │                          │
│              ▼                          │
│  ┌──────────────────────┐              │
│  │   Semantic Polish /  │              │
│  │   语义润色           │              │
│  └──────────────────────┘              │
└─────────────────┬───────────────────────┘
                  │
          [FAIL]  │  [PASS]
                  ▼
┌─────────────────┴───────────────────────┐
│  Report errors / 报告错误  │  Rename to EC-XXX.md  │
│  Agent fixes / Agent修复   │  Activate / 激活      │
│  Re-run linter / 重新运行  │                      │
└─────────────────────────────────────────┘
```

---

## Installation | 安装

```bash
clawhub install ec_creator
```

Or clone to / 或克隆到 `~/.openclaw/skills/ec_creator/`

---

## Files | 文件

```
ec_creator/
├── SKILL.md              # This file / 本文档
├── ec_linter.sh          # Main validation script / 主验证脚本
├── ec_linter.py          # Python validation script / Python验证脚本
├── rules/
│   ├── structure.json    # Section requirements / 章节要求
│   ├── paths.json        # Path validation rules / 路径验证规则
│   └── semantic.json     # Keyword patterns / 关键词模式
└── templates/
    └── ec_template.md    # Starter template / 起始模板
```

---

## Changelog | 更新日志

- **v1.1.0** (2026-03-14): 
  - Added bilingual support / 添加中英文对照
  - Structure integrity scan / 结构完整性扫描
  - Path vitality check / 路径活力检查
  - Semantic polish / 语义润色
  - Iterative validation workflow / 迭代验证工作流

- **v1.0.0** (2026-03-14): Initial release / 初始版本

---

*Part of OpenExCard Framework | OpenExCard框架的一部分*
