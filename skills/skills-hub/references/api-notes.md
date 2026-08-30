# ClawHub API Notes (verified 2026-08-30)

All endpoints verified with anonymous requests. No auth token needed for
read/search/download. Token only needed for publish (out of scope here).

## Endpoints

| Purpose | Endpoint | Notes |
|---|---|---|
| Full list (paged) | GET /api/v1/skills?limit=100&cursor=<nextCursor> | not used by v1.2 (kept for reference / future bulk ops) |
| Single detail | GET /api/v1/skills/<slug> | includes SKILL.md raw text in description field |
| Keyword search | GET /api/v1/search?q=<kw>&limit=N | exact keyword match, NOT semantic ("把照片变成视频" returns 0) |
| Download zip | GET /api/v1/download?slug=<slug>[&version=x] | anonymous, ~1.4MB typical, standard SKILL.md structure |

Base URL: https://clawhub.ai

## Key facts

- Search is keyword-only. Natural-language queries fail. Guide users to
  concrete keywords (tool names, product names: "pptx", "论文查重", "小红书").
- The zip contains the skill folder (SKILL.md + optional references/assets/
  agents). Some zips nest a top-level folder named after the slug, some do
  not - the installer handles both.
- Download endpoint returns 404-body if slug does not exist; small response
  bodies (<200B) indicate failure.
- Skills are multi-runtime: ClawHub zips may include agents/openai.yaml
  alongside SKILL.md (OpenAI-compatible). ExFlower uses SKILL.md.
- v1.2 architecture decision: NO local index cache. Search always hits the live API - freshness beats caching for a low-frequency operation. A 7.7MB cached index of 4961 skills was built in v1.0/v1.1 and removed.

## Second source (roadmap v2)

anthropics/skills on GitHub (19 official skills, Apache-2.0 source repo,
cloneable) can be a second adapter. v1 ships ClawHub only.

## Verification log (2026-08-30)

- list pagination: 3 pages, 299 skills pulled
- search "论文查重" -> 2 hits; "pptx" -> 5 hits; "把照片变成视频" -> 0 (keyword, not semantic)
- anonymous download paper-character-strategy: HTTP 200, 1487554 bytes, 19 files
