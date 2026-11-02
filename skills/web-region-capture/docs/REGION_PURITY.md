# 任意区域纯净度：样图标定 + 结构处方 + 首图验收

> 状态：M1 已实现 `element_box` / `text_line_boxes`、显式排除交集与采样遮挡门禁，并有本地及 Wikipedia 单站回归。`explicit_rect`、跨 frame/Canvas/Shadow DOM、完整页面元素覆盖与所有布局均未实现或未验证。目的不是“截出一张图”，而是在声明边界内满足“只截用户要的内容”。

## 1. 核心裁定

**建议让用户提供样图，但样图只定义区域意图与首次验收基准，不作为像素定位器。**

推荐流程：

```text
用户提供样图与目标锚点
        ↓
程序列出少量候选容器，并生成带边框/编号的预览
        ↓
用户一次确认：选哪个、保留什么、排除什么、留白多少
        ↓
保存可执行区域处方（不是只保存样图）
        ↓
每次运行：唯一性检查 → 排除/遮挡检查 → 截图 → 纯度门禁
        ↓
新处方首图人工验收；后续失败进入 needs_human
```

不做：上传样图后由视觉模型每次猜坐标；也不以新旧图像素相似度判断业务正确。网页数据、缩放和响应式布局本来就可能变化。

## 2. 用户最少提供什么

首次配置一种区域时，推荐三项：

1. 一张样图，说明想要的视觉范围；
2. 一个稳定锚点，例如“粉丝性别比例”标题或业务容器；
3. 明确不要的内容；若用户没列，程序从样图差异中提出候选，由用户确认。

后续同一站点/区域复用处方，不要求每次提供样图。页面布局变化或纯度检查失败时重新标定。

样图默认仅保存在本地项目 `data/references/`，不进入公开分发包。用户也可用不含业务数据的公开样图。

## 3. 区域处方契约

```yaml
region: example
reference_image: data/references/example.png
locate:
  scope: ".verified-panel"
  anchor_text: "目标标题"
  container: ".business-card"
  require_unique: true
boundary:
  strategy: element_box       # element_box | text_line_boxes | explicit_rect
  padding_px: 8
exclude:
  selectors: [".sidebar", "[role=dialog]", ".fixed-toolbar"]
  overlap_action: block       # 默认阻断，不自动删除内容
occlusion:
  detect: true
  allowed_overlay_selectors: []
viewport:
  width: 1440
  height: 1000
  device_scale_factor: 1
acceptance:
  required_text: "目标标题"
  first_capture_requires_human: true
```

`reference_image` 是人类意图证据；`locate/boundary/exclude/occlusion` 才是机器执行依据。两者缺一不可。

## 4. 三种边界策略

### element_box

适合完整卡片、图表、表格。定位唯一业务容器，截容器而不是只截标题文本的父级。

### text_line_boxes

适合带浮动侧栏的文本区域。使用浏览器 Range/DOM 获取实际文本行矩形，计算文本行的边界后加留白；不直接使用整个段落元素盒子。

Wikipedia 首段就是该策略的用例：段落盒子横向覆盖到浮动信息框区域，单纯 `locator.screenshot()` 会把信息框拍入；应按文本行矩形并排除 `table.infobox`。M1 的机器检查与视觉复核只覆盖 Alan Turing 当前布局，不能推广为任意 Wikipedia 页面或其他网站已通过。

实现入口：`src/web_region_capture/region_purity.py`；`capture.capture_regions()` 也已接入同一门禁。每个区域生成 `<name>-purity-check.json`；失败时保留阻断报告，不生成目标 PNG。遮挡使用有限采样，不能证明不存在未命中的覆盖层，仍需视觉域验收。

### explicit_rect

只用于确实无法结构定位的 Canvas/iframe 等。必须锁定 viewport、DPI、缩放和滚动状态；布局改变后必须重新标定。

## 5. 排除与遮挡检查

截图前记录：

- 目标矩形与排除元素矩形的交集；
- 目标中心、四角及网格采样点的 `elementsFromPoint` 结果；
- 非目标后代、非白名单覆盖层、加载/遮罩状态；
- 目标是否超出视口，以及必要的滚动/拼接策略。

默认处理：

- 与排除元素相交：`REGION_NOT_PURE`，阻断；
- 非预期遮挡：`REGION_OCCLUDED`，阻断；
- 多个目标：`REGION_AMBIGUOUS`，阻断；
- 数据仍在加载：`REGION_NOT_READY`，按处方重试，超限后待人工。

不默认隐藏页面元素。只有用户明确配置且该操作不触发布局变化时，才允许隐藏装饰性固定覆盖层，并保留处理前后证据。隐藏浮动内容可能改变排版，不能作为通用修复。

## 6. 样图怎样参与验收

样图用于校准“标题是否包含、图表/图例是否保留、边界与留白、排除哪些相邻内容”。运行后采用多域证据：

- 对象域：页面/实体身份断言；
- 结构域：唯一锚点、容器、排除元素交集；
- 视觉域：PNG 可打开、目标完整、无遮挡、无无关区域；
- 写入域：目标单元格/路径读回。

OCR 或视觉模型只能提供辅助信号，不当作真值。新处方的第一张图必须由用户确认；后续自动通过也只能说明本次检查项通过，不能证明所有网页永久兼容。

## 7. 每次交付留下的证据

```text
reference.png             # 用户样图（仅本地）
candidate-overlay.png     # 标定候选，用户选择前
region-recipe.yaml        # 用户确认后的处方
capture.png               # 实际截图
purity-check.json         # 目标/排除/遮挡/尺寸检查结果
capture-debug.png         # 失败时的脱敏调试图
manifest.jsonl            # 与文件或表格交付状态连接
```

只有 `purity-check` 通过，且新处方首图经人工确认，才进入 `captured`；文件或表格读回后才进入 `delivered`。
