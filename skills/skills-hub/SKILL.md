---
name: skills-hub
description: "Discover, search, install, and update skills from the ClawHub marketplace for the user's ExFlower environment. Use when users want to find a skill for a task (e.g. PDF conversion, video download, writing tools), browse or search available skills, install a specific skill from ClawHub, check for skill updates, or ask what skills exist. Triggers on phrases like 找技能 / 装技能 / 有什么技能 / skill marketplace."
---

# skills-hub

Find and install skills from ClawHub (clawhub.ai) into the user skills
directory. Zero dependencies, no ClawHub account needed.

## Quick Start 中文速览

```
搜索（永远最新）: python3 scripts/skills_hub.py search pdf
看详情         : python3 scripts/skills_hub.py show <slug>
安装          : python3 scripts/skills_hub.py install <slug>
更新检查       : python3 scripts/skills_hub.py update
列出已装       : python3 scripts/skills_hub.py list
```

(Windows: 把 python3 换成 py -3)

## When to use

- User asks for a capability that might exist as a ready-made skill
- User names a ClawHub slug or asks to install/update skills
- User wants to browse what is available

## How to search effectively

ClawHub search is KEYWORD, not semantic. "把照片变成视频" returns nothing;
"视频 下载" or "photo video" works. As the agent: translate the user intent
into 1-3 concrete keywords (tool name / product name / file format), then
search. Show top results with download counts and let the user pick.
Every search hits the live API - results are always current, no cache.

After install, the skill appears in list_skills and other agents can use it.

## Install & rollback

- install downloads the zip anonymously and extracts into
  ~/.exflower/skills/<slug>/ (Windows: %USERPROFILE%\.exflower\skills\<slug>\)
- a .skills-hub.json origin marker is written for update tracking
- rollback = delete that skill folder
- installed skills may carry their own LICENSE - respect it when redistributing

## Update semantics

ClawHub has no in-place update; update = delete old folder + install again.
The update command only REPORTS latest versions (safe, non-destructive).

## Failure paths

- 0 results: keyword too conversational -> try concrete keywords
- download too small / 404 / 409: slug wrong or duplicated -> copy slug exactly from search results, prefer unique slugs
- network timeouts: retry once; every call is live (no cache)
- API details & verification log: see references/api-notes.md
