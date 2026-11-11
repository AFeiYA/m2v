#!/usr/bin/env python3
"""
M2V YouTube 自动化发布脚本 (YouTube Auto-Publisher CLI)
支持指定本地文件路径全自动上传至 YouTube。

特性：
1. 智能规格探测：自动检测 16:9 横屏 / 9:16 竖屏 及音视频精确时长
2. Shorts 防雷拦截：若上传 9:16 竖屏且时长 > 60s，自动拦截报警防全球禁播
3. 文案智能生成：自动生成高点击率 SEO 标题、艺人署名、标签与 Content ID 版权免责声明
4. 安全默认策略：默认以 unlisted (不公开列出) 上传，核验 Content ID 后可一键转公开
5. 零配额演练：支持 --dry-run 参数，测试全流程不消耗每日 10,000 点配额
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# 将项目根目录加入 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

# 加载 .env 环境变量
load_dotenv(PROJECT_ROOT / ".env")

from src.youtube_uploader import generate_youtube_metadata, youtube_uploader


def probe_video(video_path: Path) -> dict:
    """使用 ffprobe 获取视频分辨率、时长与横竖屏属性"""
    if not video_path.exists():
        raise FileNotFoundError(f"文件不存在: {video_path}")

    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration:format=duration",
        "-of", "json",
        str(video_path),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
        stream = data.get("streams", [{}])[0]
        fmt = data.get("format", {})

        width = int(stream.get("width", 1920))
        height = int(stream.get("height", 1080))
        duration = float(fmt.get("duration") or stream.get("duration") or 0.0)

        aspect = "9:16" if height > width else "16:9"
        is_shorts = aspect == "9:16"

        return {
            "width": width,
            "height": height,
            "duration": duration,
            "aspect": aspect,
            "is_shorts": is_shorts,
            "size_mb": round(os.path.getsize(video_path) / (1024 * 1024), 2),
        }
    except Exception as e:
        # 回退：无法探测时默认 16:9
        size_mb = round(os.path.getsize(video_path) / (1024 * 1024), 2)
        return {
            "width": 1920,
            "height": 1080,
            "duration": 0.0,
            "aspect": "16:9",
            "is_shorts": False,
            "size_mb": size_mb,
            "error": str(e),
        }


def parse_song_from_filename(filename: str) -> dict:
    """从文件名或路径智能提取歌曲名、艺人、风格等元数据"""
    stem = Path(filename).stem
    # 典型模式：Everglow-Full song-16_9-apple.mp4, Coldplay - Everglow.mp4
    song_title = stem
    artist = "Made with fovea.si"
    style = "4K超清卡拉OK伴奏"

    if " - " in stem:
        parts = stem.split(" - ", 1)
        artist = parts[0].strip()
        song_title = parts[1].strip()

    # 剥离后缀
    for tag in ["-Full song", "-Custom clip", "-16_9", "-9_16", "-ktv", "-apple", "-poster", "-karaoke"]:
        song_title = re.sub(rf"{re.escape(tag)}", "", song_title, flags=re.IGNORECASE)

    song_title = song_title.strip(" -_")

    if "karaoke" in stem.lower() or "ktv" in stem.lower():
        style = "卡拉OK伴奏字幕"
    elif "clip" in stem.lower():
        style = "精选高潮片段"

    return {
        "title": song_title or stem,
        "artist": artist,
        "style": style,
    }


def find_companion_files(video_path: Path) -> dict:
    """查找同名配置文件 (.json) 或封面图 (.jpg, .png)"""
    meta_json = video_path.with_suffix(".json")
    custom_meta = {}
    if meta_json.exists():
        try:
            custom_meta = json.loads(meta_json.read_text(encoding="utf-8"))
        except Exception:
            pass

    cover_file = None
    for ext in [".jpg", ".png", ".jpeg", ".webp"]:
        cand = video_path.with_suffix(ext)
        if cand.exists():
            cover_file = str(cand.resolve())
            break

    return {
        "meta": custom_meta,
        "cover": cover_file,
    }


def main():
    parser = argparse.ArgumentParser(
        description="M2V YouTube 自动化发布脚本 (支持指定文件路径全自动发布)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
常用命令示例:
  # 1. 演练模式 (检查规格、解析元数据、校验 Shorts 规则，零配额消耗):
  python tools/upload_youtube.py "~/Downloads/Everglow-Full song-16_9-apple.mp4" --dry-run

  # 2. 自动上传长视频 (默认以 unlisted 不公开列出，安全合规):
  python tools/upload_youtube.py "~/Downloads/Everglow-Full song-16_9-apple.mp4"

  # 3. 自动上传短视频 (脚本会自动校验时长 <= 60s，防违规禁播):
  python tools/upload_youtube.py "~/Downloads/Everglow-Custom clip-9_16-apple.mp4"

  # 4. 上传并直接设为公开:
  python tools/upload_youtube.py "~/Downloads/Everglow-Full song-16_9-apple.mp4" --public

  # 5. 查看当前 YouTube 账号连接状态:
  python tools/upload_youtube.py --status

  # 6. 配置/更新 YouTube 凭据 (Access Token 或 Refresh Token):
  python tools/upload_youtube.py --token <access_token> [--refresh-token <refresh_token>]

  # 7. 独立核验已有视频的 Content ID 版权状态:
  python tools/upload_youtube.py --check <video_id>

  # 8. 将已有视频一键切换为公开 (Public):
  python tools/upload_youtube.py --make-public <video_id>
        """,
    )

    parser.add_argument("video_path", nargs="?", help="要上传的本地视频文件路径 (.mp4)")
    parser.add_argument("--dry-run", action="store_true", help="演练模式：校验参数与文件，不消耗实际 API 配额")
    parser.add_argument("--public", action="store_true", help="直接公开 (默认以 unlisted 不公开列出，等待版权核验)")
    parser.add_argument("--private", action="store_true", help="设为私享 (Private)")
    parser.add_argument("--title", help="自定义视频标题 (若未提供则根据歌曲与模板自动生成)")
    parser.add_argument("--artist", help="自定义歌手/艺人名称")
    parser.add_argument("--desc", help="自定义视频描述")
    parser.add_argument("--tags", help="自定义逗号分隔标签 (如: Coldplay,Everglow,Karaoke)")
    parser.add_argument("--cover", help="指定自定义封面缩略图路径 (.jpg / .png)")
    parser.add_argument("--force", action="store_true", help="强制上传（即使检测到 9:16 竖屏 > 60s 仍继续上传）")
    parser.add_argument("--wait-check", action="store_true", help="上传完成后等待并获取 Content ID 自动检测报告")

    # 管理类指令
    parser.add_argument("--status", action="store_true", help="查询当前 YouTube 频道登录与连接状态")
    parser.add_argument("--token", help="设置新的 YouTube OAuth2 Access Token")
    parser.add_argument("--refresh-token", help="设置 YouTube OAuth2 Refresh Token (用于自动续期)")
    parser.add_argument("--check", metavar="VIDEO_ID", help="检查指定 YouTube 视频的 Content ID 状态")
    parser.add_argument("--make-public", metavar="VIDEO_ID", help="将指定 YouTube 视频一键切换为公开 (Public)")

    args = parser.parse_args()

    # 处理管理指令：查询状态
    if args.status:
        print("🔍 正在检查 YouTube 频道连接状态...")
        st = youtube_uploader.get_account_status()
        if st.get("is_logged_in"):
            print(f"✅ 已成功连接频道: {st.get('uname')} (ID: {st.get('channel_id')})")
        else:
            print(f"○ 未连接 YouTube 账号 ({st.get('message')})")
            print("💡 提示：可通过 --token <your_token> 设置访问令牌。")
        return

    # 处理管理指令：设置 Token
    if args.token:
        print("💾 正在保存 YouTube 凭据...")
        res = youtube_uploader.set_tokens(args.token, args.refresh_token or "")
        if res.get("is_logged_in"):
            print(f"🎉 授权成功！已绑定频道: {res.get('uname')}")
        else:
            print(f"⚠️ Token 验证未通过: {res.get('message')}")
        return

    # 处理管理指令：检查已有视频版权
    if args.check:
        vid = args.check.strip()
        print(f"🔍 正在查询视频 [{vid}] 的 Content ID 版权状态...")
        rep = youtube_uploader.check_video_compliance(vid)
        print("=" * 60)
        print(f"视频 ID: {vid}")
        print(f"合规状态: {rep.get('status')}")
        print(f"评估结论: {rep.get('summary')}")
        print(f"安全建议: {rep.get('recommendation')}")
        print("=" * 60)
        return

    # 处理管理指令：一键转公开
    if args.make_public:
        vid = args.make_public.strip()
        print(f"🌍 正在将视频 [{vid}] 切换为公开 (Public)...")
        res = youtube_uploader.update_video_privacy(vid, "public")
        if res.get("success"):
            print(f"🎉 成功更新！视频现已公开: {res.get('url')}")
        else:
            print(f"❌ 更新失败: {res.get('message')}")
        return

    # 必须指定视频路径
    if not args.video_path:
        parser.print_help()
        sys.exit(1)

    target_path = Path(os.path.expanduser(args.video_path)).resolve()
    if not target_path.exists():
        print(f"❌ 找不到视频文件: {target_path}")
        sys.exit(1)

    print("=" * 70)
    print("🎬 M2V YouTube 自动化发布助手")
    print("=" * 70)
    print(f"📁 目标文件: {target_path}")

    # 1. 规格探测
    info = probe_video(target_path)
    dur_str = f"{int(info['duration']//60):02d}:{int(info['duration']%60):02d}"
    print(f"📐 视频规格: {info['width']}x{info['height']} ({info['aspect']}) | 时长: {info['duration']:.1f}s ({dur_str}) | 大小: {info['size_mb']} MB")

    # 2. Shorts 短视频长度安全拦截
    if info["is_shorts"]:
        if info["duration"] > 60.5:
            print("\n" + "!" * 70)
            print("❌ [安全拦截] 发现潜在违规风险:")
            print(f"   此视频为 9:16 竖屏短视频，但时长达到了 {info['duration']:.1f} 秒 (> 60 秒上限)！")
            print("   YouTube Shorts 对商业音乐有严格的 60 秒硬性红线。")
            print("   上传超过 60 秒的商业音乐短视频将被唱片公司系统自动判定为超长，并在全球范围内直接禁播！")
            print("💡 解决方案:")
            print("   1. 推荐方案：截取 30~50 秒的副歌高潮片段作为 Shorts 发布（合规引流）；")
            print("   2. 完整全曲：若需发布整首歌曲，请在导出时选择 16:9 横屏长视频格式发布。")
            if not args.force and not args.dry_run:
                print("   (如需忽略此保护强制上传，请添加 --force 参数)")
                print("!" * 70 + "\n")
                sys.exit(1)
            else:
                print("⚠️ 您已指定 --force 或 --dry-run，正在跳过拦截继续执行...")
                print("!" * 70 + "\n")
        else:
            print(f"🛡️ Shorts 检测通过: 时长 {info['duration']:.1f}s <= 60s，符合短视频商业音乐配额规范。")

    # 3. 伴随文件与元数据解析
    comp = find_companion_files(target_path)
    parsed = parse_song_from_filename(target_path.name)

    # 自定义覆盖优先级：命令行 > 伴随json > 智能推断
    meta_conf = comp["meta"]
    song_title = args.title or meta_conf.get("title") or parsed["title"]
    artist = args.artist or meta_conf.get("artist") or parsed["artist"]
    style = meta_conf.get("style") or parsed["style"]

    # 自动生成 SEO 标题、版权声明与免责描述
    extra_tags = [t.strip() for t in args.tags.split(",")] if args.tags else meta_conf.get("tags")
    gen = generate_youtube_metadata(
        title=song_title,
        artist=artist,
        style=style,
        extra_tags=extra_tags or [],
    )

    final_title = args.title or gen["title"]
    final_desc = args.desc or meta_conf.get("description") or gen["description"]
    final_tags = gen["tags"]
    final_cover = args.cover or comp["cover"] or ""

    privacy_status = "unlisted"
    if args.public:
        privacy_status = "public"
    elif args.private:
        privacy_status = "private"

    print("\n📝 智能生成发布文案:")
    print(f"   • 标题: {final_title}")
    print(f"   • 歌手/制作: {artist}")
    print(f"   • 隐私范围: {privacy_status} {'(建议先不公开，等待版权核验)' if privacy_status == 'unlisted' else ''}")
    print(f"   • 标签数量: {len(final_tags)} 个 ({', '.join(final_tags[:5])}...)")
    if final_cover:
        print(f"   • 缩略图封面: {final_cover}")
    print(f"   • 模式: {'🧪 演练模式 (不消耗 API 配额)' if args.dry_run else '🚀 真实网络上传'}")
    print("=" * 70)

    # 进度回调显示
    def _progress_cb(pct: float, msg: str):
        bar_len = 25
        filled = int(bar_len * pct)
        bar = "█" * filled + "░" * (bar_len - filled)
        sys.stdout.write(f"\r[{bar}] {int(pct*100):3d}% | {msg}")
        sys.stdout.flush()

    # 4. 执行上传
    try:
        res = youtube_uploader.publish_video(
            video_source=str(target_path),
            title=final_title,
            desc=final_desc,
            tags=final_tags,
            cover_source=final_cover,
            privacy_status=privacy_status,
            dry_run=args.dry_run,
            progress_callback=_progress_cb,
        )
        print("\n" + "=" * 70)

        if res.get("dry_run"):
            print("🎉 【演练成功】视频文件与各项参数校验全部通过！")
            print("   • 未向 YouTube 发送真实网络数据，消耗配额: 0 点。")
            print("   • 移除 --dry-run 参数即可立即一键真传！")
            print("=" * 70)
            return

        video_id = res.get("video_id")
        video_url = res.get("url")
        print(f"🎉 发布成功！视频地址: {video_url}")
        print(f"   • 视频 ID: {video_id}")
        print(f"   • 当前状态: {privacy_status}")

        # 5. Content ID 校验
        comp_rep = res.get("compliance") or {}
        print(f"   • Content ID 评估: {comp_rep.get('summary', '已提交 YouTube 后台比对')}")

        if privacy_status == "unlisted":
            print("\n💡 贴心提示:")
            print(f"   视频已安全上传为「不公开」列出。可在网页端预览音画质，确认无误后通过以下命令一键公开:")
            print(f"   👉 python tools/upload_youtube.py --make-public {video_id}")

        if args.wait_check and video_id:
            print("\n⏳ 正在等待 YouTube 后台完成 Checks 版权指纹比对 (预计需要 30~60 秒)...")
            for _ in range(12):
                time.sleep(5)
                check_res = youtube_uploader.check_video_compliance(video_id)
                status = check_res.get("status")
                if status not in ["pending", "unknown"]:
                    print(f"✅ 版权核验完成: {check_res.get('summary')}")
                    print(f"   安全建议: {check_res.get('recommendation')}")
                    break
                sys.stdout.write(".")
                sys.stdout.flush()

        print("=" * 70)

    except Exception as e:
        print(f"\n❌ 上传失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
