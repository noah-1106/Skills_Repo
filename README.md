# Skills Repo

红运团队的技能仓库 | Red Team's Skill Repository

## 用途

这个仓库用于管理我们团队自己创建和维护的 OpenClaw Skills。

## 目录结构

```
skills-repo/
├── README.md              # 本文件
├── skills/                # 技能目录
│   └── {skill-name}/      # 单个技能文件夹
│       ├── SKILL.md       # 技能文档（必须）
│       ├── skill.json     # 技能配置（必须）
│       └── ...            # 其他文件
└── docs/                  # 文档
```

## 技能列表

| 技能名称 | 版本 | 描述 | 状态 |
|----------|------|------|------|
| _待添加_ | - | - | - |

## Clawhub 发布

技能开发完成后，可以通过 Clawhub CLI 发布：

```bash
clawhub publish skills/{skill-name}
```

## 开发规范

1. 每个技能必须有 `SKILL.md` 和 `skill.json`
2. 遵循 OpenClaw AgentSkills 规范
3. 版本号遵循 SemVer
4. 测试通过后再提交

---

*Team: 红运 | Created: 2026-03-15*
