# 歌曲版式

Motion Studio 的“歌曲署名与版式”可编辑歌名和作者。默认读取导入时保存的 Suno JSON（title、artist / display_name / handle），未找到缓存时使用现有工程标题；未知作者留空，不自动编造。修改后点击“保存歌曲版式”。切换歌曲或导出时也会保存未保存的修改。

- 海报版：细线、小署名和已知段落名称，沿用歌词导演配色。
- 简洁版：小署名；不显示段落细线。
- 仅歌词：关闭歌曲装饰，包括歌名封面。
- 开场：有至少 1 秒前奏时显示，最长 5 秒。
- 尾页：原曲有至少 1.5 秒尾奏时显示，歌词结束后至少留出 0.3 秒，最长 5 秒。
- 封面只显示真实歌名和已填写的作者。作者留空时隐藏。
- 横竖屏按实际字体测量；长歌名平衡分成最多两行，并适配字号。

署名保持静止，只在封面与尾页淡入淡出，不加入呼吸、震动或拍点缩放。没有明确段落标签时不生成章节。现有歌词海报节点与对齐不变。

设置独立保存于输出目录的 `<song>_motion_identity.json`，不重写 alignment 和导演方案；预览、海报 PNG 与 Remotion MP4 使用相同歌曲版式计算。

API：`PUT /api/motion/identity`，body 为 `project_id` 与 `identity`；可编辑字段为 version、title、artist、style、show_intro、show_signature、show_section、show_outro。源歌名与作者为服务端只读字段。
