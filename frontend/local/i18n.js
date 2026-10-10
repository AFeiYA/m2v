// ===========================================================================
// M2V Local Editor — Internationalization (i18n) Module
// Supports Chinese (zh) and English (en) with persistent locale preference
// ===========================================================================

const I18N = {
  zh: {
    // App & Header
    app_title: "M2V 歌词与字幕对齐编辑器",
    header_title: "🎤 M2V 歌词",
    header_title_title: "三击标题可显示/隐藏开发者调试选项（含URL测试历史）",
    url_placeholder: "粘贴 Suno / 网易云歌曲链接或 iframe...",
    url_history_title: "最近 10 条测试 URL 历史记录",
    url_history_default: "🕒 最近历史",
    chk_sep_title: "勾选：提取纯人声干音，适合流行/摇滚/电音等复杂伴奏，100%防止漏词跳句；取消勾选：极速模式直接对齐原曲",
    chk_sep_label: "分离伴奏",
    chk_gpu_title: "勾选：优先调用 GPU 硬件加速 (云端 ZeroGPU A100 / 本地 MPS)；取消勾选：使用 CPU 运行",
    chk_gpu_label: "GPU加速",
    lang_select_title: "语言模式：默认自动识别；英文歌若遇复杂伴奏或嘶吼，强制指定英文可大幅提升对齐精度",
    lang_auto: "🌐 语言: 自动识别",
    lang_en: "🇬🇧 强制英文 (EN)",
    lang_zh: "🇨🇳 强制中文 (ZH)",
    lang_ja: "🇯🇵 日语 (JA)",
    lang_ko: "🇰🇷 韩语 (KO)",
    btn_quick_mp3: "⬇ 仅下 MP3",
    btn_quick_mp3_title: "从粘贴的链接仅提取下载原曲 MP3 (执行步骤 1，跳过分离对齐)",
    btn_import: "⚡ 导入对齐",
    btn_import_title: "一键抓取并字级对齐",
    song_select_loading: "加载中…",

    // Toolbar
    btn_save: "💾 保存",
    btn_save_title: "保存修改 (Ctrl+S)",
    btn_analyze_audio: "🎵 分析音频",
    btn_analyze_audio_title: "提取原曲节拍、能量和频段变化；已有结果会复用缓存",
    btn_undo: "↩ 撤销",
    btn_undo_title: "Ctrl+Z",
    btn_redo: "↪ 重做",
    btn_redo_title: "Ctrl+Y",
    btn_orig_mp3: "⬇ 原曲 MP3",
    btn_orig_mp3_title: "一键下载当前歌曲的原曲 MP3",
    btn_regen_ass: "📝 生成 ASS",
    btn_regen_ass_title: "从当前字级时间戳重新生成 ASS 字幕",
    btn_export_video: "📱 导出动效短视频",
    btn_export_video_title: "一键导出商业级 9:16 / 16:9 动效短视频",
    nav_storyboard: "🎬 分镜制作 ↗",
    nav_storyboard_title: "前往下游制作图片素材与视频合成",
    nav_motion_studio: "⚡ 动效工作室 ↗",
    nav_motion_studio_title: "前往纯净音乐动效与节奏工坊",
    nav_gallery: "🎬 作品展厅 ↗",
    nav_gallery_title: "前往视频作品展厅与手机扫码播放器",
    lang_toggle_btn: "🌐 English",
    lang_toggle_title: "切换至英文界面 (Switch to English)",

    // Waveform Section
    audio_feat_not_analyzed: "音频特征尚未分析",
    audio_feat_not_analyzed_hint: "音频特征尚未分析 · 点击“分析音频”即可补做，无需重新对齐歌词",
    track_vocals: "🎤 人声",
    track_vocals_mute_title: "静音/取消静音人声轨",
    skeleton_vocals_loading: "人声音轨缓冲加载中...",
    track_inst: "🎸 伴奏",
    track_inst_mute_title: "静音/取消静音乐器轨",
    skeleton_inst_loading: "伴奏音轨缓冲加载中...",
    track_orig: "🎵 原声",
    btn_play: "▶ 播放",
    btn_pause: "⏸ 暂停",
    btn_play_line: "▶ 播放选中行",
    zoom_label: "缩放:",

    // Lyrics & Word Panels
    word_panel_placeholder: "点击左侧歌词行展开字级时间轴",
    line_ctrl_label: "整行:",
    btn_line_nudge_l200: "⬅ -200ms",
    btn_line_nudge_l200_title: "整行前移 200ms",
    btn_line_nudge_l50: "◁ -50ms",
    btn_line_nudge_l50_title: "整行前移 50ms",
    btn_line_nudge_r50: "▷ +50ms",
    btn_line_nudge_r50_title: "整行后移 50ms",
    btn_line_nudge_r200: "➡ +200ms",
    btn_line_nudge_r200_title: "整行后移 200ms",
    btn_line_expand: "↔ 展开",
    btn_line_expand_title: "行时长+100ms",
    btn_line_shrink: "⇿ 收缩",
    btn_line_shrink_title: "行时长-100ms",
    btn_snap_start_playhead: "✂ 首字对齐播放头",
    btn_snap_start_playhead_title: "将首字起唱时间对齐至当前音频播放位置 (空格暂停后点击)",
    btn_snap_end_playhead: "✂ 尾字对齐播放头",
    btn_snap_end_playhead_title: "将尾字收唱时间对齐至当前音频播放位置",
    word_ctrl_label: "选中字微调:",
    btn_word_shift_l50: "⬅ -50ms",
    btn_word_shift_l50_title: "快捷键 A",
    btn_word_nudge_l10: "◁ -10ms",
    btn_word_nudge_l10_title: "快捷键 ←",
    btn_word_nudge_r10: "▷ +10ms",
    btn_word_nudge_r10_title: "快捷键 →",
    btn_word_shift_r50: "➡ +50ms",
    btn_word_shift_r50_title: "快捷键 D",
    btn_even_split: "⚖ 均分整行时值",
    btn_play_word: "▶ 试听选中字",

    // Dynamic Timeline Labels & Titles
    interlude: "间奏",
    gap: "空隙",
    prev_line_connected: "紧接上句",
    next_line_connected: "紧接下句",
    pre_gap_title: "前置间奏/静音",
    pre_gap_hint: "双击或拖拽尾部手柄调节首字起唱时间",
    handle_start_title: "拖拽调节首字起唱 | 双击获取当前播放头时间",
    handle_split_title: "拖拽分割点 | 双击=对齐至当前播放头",
    handle_end_title: "拖拽尾字收唱 | 双击=对齐至当前播放头",
    post_gap_title: "后置间歇",
    post_gap_end_sing: "尾字收唱",
    post_gap_hint: "双击或拖拽手柄调节收唱点",
    handle_end_edge_title: "拖拽调节尾字收唱",
    handle_end_edge_hint: "双击对齐至播放头",
    word_needs_review: " [声学边界较弱/连音，建议人工复核]",
    line_row_start_title: "行起始时间",
    line_row_end_title: "行结束时间",
    line_nudge_left_title: "整行前移100ms",
    line_nudge_right_title: "整行后移100ms",
    sec_intro_dblclick: "双击从前奏开始播放",
    sec_dblclick: "双击从本乐段开始播放",
    line_title_prefix: "第",
    line_title_suffix: "行",

    // Modal (Short Video Export)
    suno_progress_extracting: "正在从 Suno 提取歌曲信息与歌词...",
    modal_title: "一键生成动效短视频 (短视频/商业化出片)",
    modal_step1_label: "1. 视频画幅规格",
    ratio_9_16_title: "📱 9:16 竖屏短视频 (1080x1920)",
    ratio_9_16_desc: "抖音、TikTok、小红书、Reels 爆款推荐",
    ratio_16_9_title: "💻 16:9 横屏高清 (1920x1080)",
    ratio_16_9_desc: "Bilibili、YouTube、PC 宽屏",
    modal_step2_label: "2. 动态背景风格",
    bg_full_bleed_title: "🖼️ 全图沉浸式铺满 (9:16推荐)",
    bg_full_bleed_desc: "原画全屏无黑边铺满，沉浸感极强",
    bg_ken_burns_title: "📷 慢速呼吸变焦 (Ken Burns)",
    bg_ken_burns_desc: "封面原画全屏缓推呼吸微动效",
    bg_blurred_title: "✨ 磨砂毛玻璃 + 封面立体悬浮",
    bg_blurred_desc: "经典毛玻璃光晕，适合 16:9 横屏",
    bg_vinyl_title: "💿 经典黑胶唱盘旋转",
    bg_vinyl_desc: "复古唱机氛围，旋转黑胶贴纸",
    modal_step3_label: "3. 歌词排版动效",
    tpl_apple: "🍎 Apple Music 滚动聚焦 (焦点放大/景深虚化)",
    tpl_center_bounce: "⚡ 极简居中弹性跳动 (爆款单行/弱显下一句)",
    tpl_tv: "🎤 经典 KTV 双行交替 (传统卡拉OK)",
    modal_step4_label: "4. 荧光调色板",
    theme_apple_white: "⚪ 极简珍珠白 (高冷白光/半透灰白)",
    theme_cyber_neon: "🔷 赛博电光霓虹 (电光青/霓虹粉)",
    theme_amber_gold: "🟡 复古黑胶金 (琥珀金/焦糖棕)",
    theme_midnight_purple: "🟣 极光冷艳紫 (薰衣草亮紫/幽邃紫)",
    theme_emerald_mint: "🟢 清爽翡翠绿 (薄荷绿/森林青)",
    modal_step5_label: "5. 导出片段范围",
    preset_full_badge: "全曲完整导出",
    preset_full: "全曲",
    preset_chorus: "🔥 副歌高潮",
    preset_verse1: "🎧 主歌 1",
    preset_custom: "⏱️ 自定义",
    start_time_label: "起始时间 (分:秒 或 秒数)",
    btn_start_curr: "当前",
    btn_start_curr_title: "从当前播放器指针设为起点",
    end_time_label: "结束时间 (留空为全曲)",
    end_time_placeholder: "全曲结束",
    btn_end_curr: "当前",
    btn_end_curr_title: "从当前播放器指针设为终点",
    btn_reset_range: "重置全曲",
    render_preparing: "正在准备渲染...",
    render_success: "🎉 动效短视频合成完成！",
    btn_download_mp4: "⬇️ 立即下载 MP4 视频",
    btn_re_render: "🔄 换个参数重新合成",
    btn_modal_close: "关闭",
    btn_modal_start: "🚀 立即开始合成短视频",
    btn_modal_rendering: "⏳ 合成中，请稍候...",
    segment_clip: "片段截取: {dur}秒 ({st} - {et})",
    segment_from_start: "从 {st} 起直至全曲结束",

    // Status & Notifications
    msg_vocals_loaded: "人声轨已加载",
    msg_inst_loaded: "伴奏轨已加载",
    msg_muted: "{track} 已静音",
    msg_unmuted: "{track} 已取消静音",
    msg_load_file_failed: "文件列表加载失败: ",
    msg_loading_song: "加载 {name}…",
    msg_align_load_failed: "对齐数据加载失败: ",
    msg_lyrics_ready: "📝 歌词已就绪 ({count} 行)，正在加载音轨波形...",
    msg_vocals_load_failed: "人声轨加载失败: ",
    msg_inst_load_failed: "伴奏轨加载失败: ",
    msg_all_ready: "✅ 全部就绪: {name} ({count} 行, 音轨: {tracks})",
    msg_track_vocals: "人声",
    msg_track_inst: "伴奏",
    msg_track_orig: "原声",
    msg_track_none: "无",
    msg_saving: "保存中…",
    msg_saved: "✅ 已保存",
    msg_save_failed: "保存失败: ",
    msg_undone: "已撤销",
    msg_no_undo: "无可撤销操作",
    msg_redone: "已重做",
    msg_no_redo: "无可重做操作",
    msg_dev_enabled: "🛠 已开启开发者调试模式（包含URL测试历史）",
    msg_dev_disabled: "🛠 已隐藏开发者调试选项",
    msg_select_song_first: "请先选择歌曲",
    msg_analyzing_audio: "正在分析原曲节拍、能量和频段变化…",
    msg_audio_analysis_done: "音频分析完成：{bpm}，{beats} 个拍点，100Hz 特征{cache}；重拍和鼓点类别为估计值",
    msg_audio_analysis_failed: "音频分析失败：",
    msg_enter_valid_url: "请输入有效的 Suno / 网易云歌曲链接、iframe 代码或歌曲 ID",
    msg_suno_extracting: "正在从 Suno 提取歌曲信息与歌词...",
    msg_netease_extracting: "正在从网易云音乐提取歌曲、LRC 歌词与音频...",
    msg_aligning_vocals: "正在进行人声与伴奏分离及时间轴对齐...",
    msg_aligning_direct: "正在进行原曲词级时间轴对齐 (CTC / WhisperX)...",
    msg_import_success: "🎉 导入成功: {title}",
    msg_downloading_mp3: "正在下载《{song}》原曲 MP3...",
    msg_download_triggered: "已触发下载: {song}.mp3",
    msg_generating_ass: "正在重新生成 ASS 字幕...",
    msg_ass_generated: "🎉 ASS 字幕已生成: {path}",
    msg_ass_failed: "生成 ASS 失败: ",
    msg_video_success: "🎉 动效短视频已生成完成！",
    msg_video_failed: "短视频合成失败",
    msg_export_video_failed: "导出短视频失败: ",
    snap_start_msg: "🎯 首字起唱点已吸附至播放头: {time}（前置间奏: {gap}s）",
    snap_end_msg: "🎯 尾字收唱点已吸附至播放头: {time}（后置间歇: {gap}s）",
    split_snapped_msg: "✂ 分割点 {idx1}|{idx2} → {time}",
    time_format_error: "时间格式错误，请输入 m:ss.xxx 或 秒数",
    bound_early_prev: "⚠️ 播放头位置 ({time}) 早于上一句结束 ({bound})，已自动约束在上一句后",
    bound_late_second: "⚠️ 播放头位置 ({time}) 晚于第 2 个字起唱 ({bound})，已自动约束在第 2 字前",
    bound_early_last: "⚠️ 播放头位置 ({time}) 早于尾字起唱 ({bound})",
    bound_late_next: "⚠️ 播放头位置 ({time}) 晚于下一句起唱 ({bound})，已约束在下一句前",
  },

  en: {
    // App & Header
    app_title: "M2V Lyrics & Subtitle Alignment Editor",
    header_title: "🎤 M2V Lyrics",
    header_title_title: "Triple-click title to toggle developer options (including URL history)",
    url_placeholder: "Paste Suno / NetEase song link or iframe...",
    url_history_title: "Recent 10 test URL history items",
    url_history_default: "🕒 Recent History",
    chk_sep_title: "Checked: Isolate vocal stem (avoids missing words in complex music); Unchecked: Fast mode direct alignment",
    chk_sep_label: "Separate Stems",
    chk_gpu_title: "Checked: GPU hardware acceleration (ZeroGPU A100 / Local MPS); Unchecked: CPU mode",
    chk_gpu_label: "GPU Accel",
    lang_select_title: "Language mode: Default Auto-detect; For English songs with loud BGM, forcing English improves accuracy",
    lang_auto: "🌐 Lang: Auto Detect",
    lang_en: "🇬🇧 Force English (EN)",
    lang_zh: "🇨🇳 Force Chinese (ZH)",
    lang_ja: "🇯🇵 Japanese (JA)",
    lang_ko: "🇰🇷 Korean (KO)",
    btn_quick_mp3: "⬇ MP3 Only",
    btn_quick_mp3_title: "Download original MP3 only (skip vocal separation & alignment)",
    btn_import: "⚡ Import & Align",
    btn_import_title: "One-click fetch and word-level alignment",
    song_select_loading: "Loading…",

    // Toolbar
    btn_save: "💾 Save",
    btn_save_title: "Save changes (Ctrl+S)",
    btn_analyze_audio: "🎵 Analyze Audio",
    btn_analyze_audio_title: "Analyze BPM, beats, energy & envelopes; cached results are reused",
    btn_undo: "↩ Undo",
    btn_undo_title: "Ctrl+Z",
    btn_redo: "↪ Redo",
    btn_redo_title: "Ctrl+Y",
    btn_orig_mp3: "⬇ Original MP3",
    btn_orig_mp3_title: "Download original MP3 of current song",
    btn_regen_ass: "📝 Gen ASS",
    btn_regen_ass_title: "Regenerate ASS subtitles from current word timestamps",
    btn_export_video: "📱 Export Video",
    btn_export_video_title: "One-click export 9:16 / 16:9 motion lyric video",
    nav_storyboard: "🎬 Storyboard ↗",
    nav_storyboard_title: "Go to storyboard creation & video composition",
    nav_motion_studio: "⚡ Motion Studio ↗",
    nav_motion_studio_title: "Go to pure motion studio & rhythm lab",
    nav_gallery: "🎬 Gallery ↗",
    nav_gallery_title: "Go to video showcase gallery & mobile player",
    lang_toggle_btn: "🌐 中文",
    lang_toggle_title: "Switch to Chinese interface (切换至中文界面)",

    // Waveform Section
    audio_feat_not_analyzed: "Audio features not analyzed yet",
    audio_feat_not_analyzed_hint: "Audio features not analyzed · Click 'Analyze Audio' to run without re-aligning",
    track_vocals: "🎤 Vocals",
    track_vocals_mute_title: "Mute / Unmute vocals track",
    skeleton_vocals_loading: "Buffering vocals track...",
    track_inst: "🎸 Instrumental",
    track_inst_mute_title: "Mute / Unmute instrumental track",
    skeleton_inst_loading: "Buffering instrumental track...",
    track_orig: "🎵 Original",
    btn_play: "▶ Play",
    btn_pause: "⏸ Pause",
    btn_play_line: "▶ Play Selected Line",
    zoom_label: "Zoom:",

    // Lyrics & Word Panels
    word_panel_placeholder: "Click a lyric line on the left to expand word timeline",
    line_ctrl_label: "Line:",
    btn_line_nudge_l200: "⬅ -200ms",
    btn_line_nudge_l200_title: "Shift line back 200ms",
    btn_line_nudge_l50: "◁ -50ms",
    btn_line_nudge_l50_title: "Shift line back 50ms",
    btn_line_nudge_r50: "▷ +50ms",
    btn_line_nudge_r50_title: "Shift line forward 50ms",
    btn_line_nudge_r200: "➡ +200ms",
    btn_line_nudge_r200_title: "Shift line forward 200ms",
    btn_line_expand: "↔ Expand",
    btn_line_expand_title: "Line duration +100ms",
    btn_line_shrink: "⇿ Shrink",
    btn_line_shrink_title: "Line duration -100ms",
    btn_snap_start_playhead: "✂ Snap Start",
    btn_snap_start_playhead_title: "Snap first word start time to current playhead (pause with Space first)",
    btn_snap_end_playhead: "✂ Snap End",
    btn_snap_end_playhead_title: "Snap last word end time to current playhead",
    word_ctrl_label: "Word:",
    btn_word_shift_l50: "⬅ -50ms",
    btn_word_shift_l50_title: "Shortcut: A",
    btn_word_nudge_l10: "◁ -10ms",
    btn_word_nudge_l10_title: "Shortcut: ←",
    btn_word_nudge_r10: "▷ +10ms",
    btn_word_nudge_r10_title: "Shortcut: →",
    btn_word_shift_r50: "➡ +50ms",
    btn_word_shift_r50_title: "Shortcut: D",
    btn_even_split: "⚖ Even Split Line",
    btn_play_word: "▶ Audition Word",

    // Dynamic Timeline Labels & Titles
    interlude: "Interlude",
    gap: "Gap",
    prev_line_connected: "Follows Prev",
    next_line_connected: "Follows Next",
    pre_gap_title: "Pre-line interlude / silence",
    pre_gap_hint: "Double-click or drag handle to adjust first word start",
    handle_start_title: "Drag to adjust start time | Double-click to snap to playhead",
    handle_split_title: "Drag boundary | Double-click to snap to playhead",
    handle_end_title: "Drag end time | Double-click to snap to playhead",
    post_gap_title: "Post-line gap",
    post_gap_end_sing: "End sing",
    post_gap_hint: "Double-click or drag handle to adjust end point",
    handle_end_edge_title: "Drag to adjust end time",
    handle_end_edge_hint: "Double-click to snap to playhead",
    word_needs_review: " [Weak acoustic boundary/liaison, review suggested]",
    line_row_start_title: "Line start time",
    line_row_end_title: "Line end time",
    line_nudge_left_title: "Shift line back 100ms",
    line_nudge_right_title: "Shift line forward 100ms",
    sec_intro_dblclick: "Double-click to play from Intro",
    sec_dblclick: "Double-click to play from this section",
    line_title_prefix: "Line",
    line_title_suffix: "",

    // Modal (Short Video Export)
    suno_progress_extracting: "Extracting song info and lyrics from Suno...",
    modal_title: "Generate Motion Lyric Video (Commercial / Shorts)",
    modal_step1_label: "1. Video Aspect Ratio",
    ratio_9_16_title: "📱 9:16 Vertical Video (1080x1920)",
    ratio_9_16_desc: "Optimized for TikTok, Reels, Shorts & RED",
    ratio_16_9_title: "💻 16:9 Widescreen HD (1920x1080)",
    ratio_16_9_desc: "Ideal for YouTube, Bilibili & PC displays",
    modal_step2_label: "2. Dynamic Background Style",
    bg_full_bleed_title: "🖼️ Full-Bleed Immersive Cover (Recommended)",
    bg_full_bleed_desc: "Full-screen borderless cover art, highly immersive",
    bg_ken_burns_title: "📷 Gentle Breathing Zoom (Ken Burns)",
    bg_ken_burns_desc: "Subtle slow zoom & pan across cover art",
    bg_blurred_title: "✨ Frosted Glass Ambient + Floating Cover",
    bg_blurred_desc: "Classic frosted glass glow, best for 16:9 landscape",
    bg_vinyl_title: "💿 Rotating Vinyl Record",
    bg_vinyl_desc: "Retro turntable aesthetic with spinning vinyl disc",
    modal_step3_label: "3. Lyric Animation Template",
    tpl_apple: "🍎 Apple Music Scrolling Focus (Enlarge & Blur)",
    tpl_center_bounce: "⚡ Center Elastic Bounce (Single line with faint next preview)",
    tpl_tv: "🎤 Classic Karaoke Dual-Line (Traditional KTV)",
    modal_step4_label: "4. Color Palette",
    theme_apple_white: "⚪ Minimal Pearl White (Cool white & translucent gray)",
    theme_cyber_neon: "🔷 Cyber Neon (Electric cyan & hot pink)",
    theme_amber_gold: "🟡 Retro Vinyl Gold (Amber gold & caramel brown)",
    theme_midnight_purple: "🟣 Aurora Purple (Lavender glow & deep purple)",
    theme_emerald_mint: "🟢 Emerald Mint (Mint green & forest teal)",
    modal_step5_label: "5. Export Clip Range",
    preset_full_badge: "Full Song Export",
    preset_full: "Full Song",
    preset_chorus: "🔥 Chorus Peak",
    preset_verse1: "🎧 Verse 1",
    preset_custom: "⏱️ Custom",
    start_time_label: "Start Time (mm:ss or seconds)",
    btn_start_curr: "Current",
    btn_start_curr_title: "Set start from current playhead position",
    end_time_label: "End Time (leave empty for song end)",
    end_time_placeholder: "Song End",
    btn_end_curr: "Current",
    btn_end_curr_title: "Set end from current playhead position",
    btn_reset_range: "Reset Full",
    render_preparing: "Preparing render...",
    render_success: "🎉 Motion video rendered successfully!",
    btn_download_mp4: "⬇️ Download MP4 Video",
    btn_re_render: "🔄 Re-render with new settings",
    btn_modal_close: "Close",
    btn_modal_start: "🚀 Start Video Synthesis",
    btn_modal_rendering: "⏳ Synthesizing, please wait...",
    segment_clip: "Clip: {dur}s ({st} - {et})",
    segment_from_start: "From {st} to end of song",

    // Status & Notifications
    msg_vocals_loaded: "Vocals track loaded",
    msg_inst_loaded: "Instrumental track loaded",
    msg_muted: "{track} muted",
    msg_unmuted: "{track} unmuted",
    msg_load_file_failed: "Failed to load song list: ",
    msg_loading_song: "Loading {name}…",
    msg_align_load_failed: "Failed to load alignment data: ",
    msg_lyrics_ready: "📝 Lyrics ready ({count} lines), loading audio waveforms...",
    msg_vocals_load_failed: "Failed to load vocals track: ",
    msg_inst_load_failed: "Failed to load instrumental track: ",
    msg_all_ready: "✅ Ready: {name} ({count} lines, tracks: {tracks})",
    msg_track_vocals: "vocals",
    msg_track_inst: "instrumental",
    msg_track_orig: "original",
    msg_track_none: "none",
    msg_saving: "Saving…",
    msg_saved: "✅ Saved",
    msg_save_failed: "Failed to save: ",
    msg_undone: "Undone",
    msg_no_undo: "Nothing to undo",
    msg_redone: "Redone",
    msg_no_redo: "Nothing to redo",
    msg_dev_enabled: "🛠 Developer debug mode enabled (with URL history)",
    msg_dev_disabled: "🛠 Developer debug options hidden",
    msg_select_song_first: "Please select a song first",
    msg_analyzing_audio: "Analyzing audio beats, BPM & frequency envelopes…",
    msg_audio_analysis_done: "Audio analysis complete: {bpm}, {beats} beats, 100Hz features{cache}; downbeats/drums are estimates",
    msg_audio_analysis_failed: "Audio analysis failed: ",
    msg_enter_valid_url: "Please enter a valid Suno / NetEase song URL, iframe code, or song ID",
    msg_suno_extracting: "Extracting song info and lyrics from Suno...",
    msg_netease_extracting: "Extracting song, LRC lyrics & audio from NetEase Music...",
    msg_aligning_vocals: "Separating vocals/instrumentals & aligning timestamps...",
    msg_aligning_direct: "Aligning word-level timestamps directly (CTC / WhisperX)...",
    msg_import_success: "🎉 Successfully imported: {title}",
    msg_downloading_mp3: "Downloading original MP3 for \"{song}\"...",
    msg_download_triggered: "Download started: {song}.mp3",
    msg_generating_ass: "Regenerating ASS subtitles...",
    msg_ass_generated: "🎉 ASS subtitles generated: {path}",
    msg_ass_failed: "Failed to generate ASS: ",
    msg_video_success: "🎉 Motion lyric video generated successfully!",
    msg_video_failed: "Motion video synthesis failed",
    msg_export_video_failed: "Failed to export video: ",
    snap_start_msg: "🎯 First word start snapped to playhead: {time} (pre-gap: {gap}s)",
    snap_end_msg: "🎯 Last word end snapped to playhead: {time} (post-gap: {gap}s)",
    split_snapped_msg: "✂ Split point {idx1}|{idx2} → {time}",
    time_format_error: "Invalid time format. Please enter m:ss.xxx or seconds",
    bound_early_prev: "⚠️ Playhead ({time}) is earlier than previous line end ({bound}), clamped after previous line",
    bound_late_second: "⚠️ Playhead ({time}) is later than 2nd word start ({bound}), clamped before 2nd word",
    bound_early_last: "⚠️ Playhead ({time}) is earlier than last word start ({bound})",
    bound_late_next: "⚠️ Playhead ({time}) is later than next line start ({bound}), clamped before next line",
  }
};

// ---------------------------------------------------------------------------
// Locale State & Helper Functions
// ---------------------------------------------------------------------------

let currentLocale = "zh";
try {
  const saved = localStorage.getItem("m2v_locale");
  if (saved === "en" || saved === "zh") {
    currentLocale = saved;
  } else if (navigator.language && navigator.language.toLowerCase().startsWith("en")) {
    currentLocale = "en";
  }
} catch (e) {}

window.currentLocale = currentLocale;

/**
 * Translate a key into the active locale.
 * Supports parameter interpolation: t("msg_all_ready", null, { name: "test", count: 10 })
 */
function t(key, fallback = "", params = null) {
  const loc = window.currentLocale || "zh";
  let str = I18N[loc]?.[key] ?? I18N["zh"]?.[key] ?? fallback ?? key;
  if (params && typeof params === "object") {
    for (const [k, v] of Object.entries(params)) {
      str = str.replace(new RegExp(`\\{${k}\\}`, "g"), v);
    }
  }
  return str;
}
window.t = t;

/**
 * Apply translations to all DOM elements marked with data-i18n attributes.
 */
function applyTranslations() {
  const loc = window.currentLocale || "zh";
  document.documentElement.lang = loc === "en" ? "en" : "zh-CN";

  // 1. Text Content
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.getAttribute("data-i18n");
    if (key && I18N[loc]?.[key] !== undefined) {
      el.textContent = I18N[loc][key];
    }
  });

  // 2. Titles / Tooltips
  document.querySelectorAll("[data-i18n-title]").forEach((el) => {
    const key = el.getAttribute("data-i18n-title");
    if (key && I18N[loc]?.[key] !== undefined) {
      el.title = I18N[loc][key];
    }
  });

  // 3. Placeholders
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    const key = el.getAttribute("data-i18n-placeholder");
    if (key && I18N[loc]?.[key] !== undefined) {
      el.placeholder = I18N[loc][key];
    }
  });

  // 4. Update Language Switcher Button Text & Title
  const langBtn = document.getElementById("btn-lang-toggle");
  if (langBtn) {
    langBtn.textContent = I18N[loc]?.lang_toggle_btn || (loc === "zh" ? "🌐 English" : "🌐 中文");
    langBtn.title = I18N[loc]?.lang_toggle_title || "Switch Language / 切换语言";
  }

  // 5. Update Document Title
  if (I18N[loc]?.app_title) {
    const songName = window.state?.currentFile?.name;
    document.title = songName ? `${songName} — ${I18N[loc].app_title}` : I18N[loc].app_title;
  }
}
window.applyTranslations = applyTranslations;

/**
 * Set active locale, save to localStorage, apply to DOM, and dispatch event.
 */
function setLocale(loc) {
  if (loc !== "zh" && loc !== "en") return;
  window.currentLocale = loc;
  try {
    localStorage.setItem("m2v_locale", loc);
  } catch (e) {}

  applyTranslations();

  // Notify other components (lyric_editor.js / common.js)
  window.dispatchEvent(new CustomEvent("languagechange", { detail: { locale: loc } }));
}
window.setLocale = setLocale;

/**
 * Toggle between "zh" and "en".
 */
function toggleLocale() {
  const next = window.currentLocale === "zh" ? "en" : "zh";
  setLocale(next);
}
window.toggleLocale = toggleLocale;

// Initialize on DOMContentLoaded
if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => applyTranslations());
  } else {
    applyTranslations();
  }
}
