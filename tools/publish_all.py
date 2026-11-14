#!/usr/bin/env python3
"""
M2V 全平台本地一键发布 CLI (Local Multi-Platform Publisher)
支持本地一站式分发到海外 (YouTube / TikTok / Meta IG+FB) 与国内 (小红书 / 抖音 / 微信视频号 / B站)。

示例：
  # 1. 查看所有平台当前登录状态
  python tools/publish_all.py --status

  # 2. 为指定平台弹出登录窗口（只需登录一次即可持久化）
  python tools/publish_all.py --auth tiktok
  python tools/publish_all.py --auth meta

  # 3. 演练模式（支持中英双版本路由）
  python tools/publish_all.py --en-video en.mp4 --zh-video zh.mp4 --title "弹珠演奏" --en-title "Marble Music #Shorts" --platforms all --dry-run

  # 4. 正式一键分发
  python tools/publish_all.py --en-video en.mp4 --zh-video zh.mp4 --title "弹珠演奏" --en-title "Marble Music #Shorts" --platforms all
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from src.bilibili_uploader import bilibili_uploader
from src.douyin_uploader import douyin_uploader
from src.meta_uploader import meta_uploader
from src.tiktok_uploader import tiktok_uploader
from src.wechat_uploader import wechat_uploader
from src.xiaohongshu_uploader import xiaohongshu_uploader
from src.youtube_uploader import youtube_uploader

OVERSEAS_PLATFORMS = ("youtube", "tiktok", "meta")
DOMESTIC_PLATFORMS = ("xiaohongshu", "douyin", "wechat", "bilibili")
ALL_PLATFORMS = OVERSEAS_PLATFORMS + DOMESTIC_PLATFORMS

UPLOADERS = {
    "youtube": youtube_uploader,
    "tiktok": tiktok_uploader,
    "meta": meta_uploader,
    "xiaohongshu": xiaohongshu_uploader,
    "douyin": douyin_uploader,
    "wechat": wechat_uploader,
    "bilibili": bilibili_uploader,
}


def resolve_platforms(spec: str) -> list[str]:
    """解析 --platforms 参数（支持 all / overseas / domestic / 逗号分隔列表）"""
    raw = [s.strip().lower() for s in spec.split(",") if s.strip()]
    resolved: list[str] = []
    for item in raw:
        if item == "all":
            resolved.extend(ALL_PLATFORMS)
        elif item == "overseas":
            resolved.extend(OVERSEAS_PLATFORMS)
        elif item == "domestic":
            resolved.extend(DOMESTIC_PLATFORMS)
        elif item in ("ig", "fb", "instagram", "facebook"):
            if "meta" not in resolved:
                resolved.append("meta")
        elif item in ("xhs",):
            if "xiaohongshu" not in resolved:
                resolved.append("xiaohongshu")
        elif item in UPLOADERS:
            resolved.append(item)
        else:
            raise ValueError(f"不支持的平台标识: {item}")

    seen = set()
    return [p for p in resolved if not (p in seen or seen.add(p))]


def print_status() -> dict[str, dict]:
    """打印并汇总全部平台登录状态"""
    print("=" * 70)
    print("🌐 全平台本地会话状态检查")
    print("=" * 70)
    statuses: dict[str, dict] = {}
    for name in ALL_PLATFORMS:
        up = UPLOADERS[name]
        try:
            st = up.get_account_status()
        except Exception as e:
            st = {"is_logged_in": False, "message": str(e)}
        statuses[name] = st
        logged = st.get("is_logged_in") or st.get("is_login")
        icon = "✅" if logged else "○"
        uname = st.get("uname") or "-"
        msg = st.get("message") or ""
        print(f"  {icon} {name:<12} | {uname:<22} | {msg}")
    print("=" * 70)
    return statuses


def run_auth(platform: str):
    """启动指定平台的前台登录窗口并等待完成"""
    key = resolve_platforms(platform)[0]
    if key == "youtube":
        from tools.upload_youtube import run_interactive_oauth
        run_interactive_oauth()
        return

    up = UPLOADERS[key]
    if not hasattr(up, "launch_browser_login"):
        raise RuntimeError(f"平台 {key} 暂不支持浏览器登录向导")

    print(f"🔑 正在打开 {key} 登录窗口，请在弹出的 Chrome 中完成登录...")
    res = up.launch_browser_login()
    print(res.get("message", ""))
    for _ in range(185):
        active = [t for t in threading.enumerate() if t is not threading.main_thread() and t.is_alive()]
        if not active:
            break
        time.sleep(1)
    print(f"✅ {key} 登录流程结束，当前状态:", up.get_account_status())


def publish_to_platforms(
    platforms: list[str],
    en_video: Optional[Path],
    zh_video: Optional[Path],
    title: str,
    en_title: str,
    desc: str,
    en_desc: str,
    tags: list[str],
    en_tags: list[str],
    youtube_privacy: str = "unlisted",
    headless: bool = True,
    dry_run: bool = False,
) -> list[dict]:
    """按海外/国内路线依次发布视频并返回结果列表"""
    results: list[dict] = []
    for p in platforms:
        is_overseas = p in OVERSEAS_PLATFORMS
        vpath = en_video if is_overseas else zh_video
        if vpath is None:
            results.append({"platform": p, "success": False, "skipped": True, "message": "未提供对应视频路径"})
            continue

        p_title = (en_title or title) if is_overseas else (title or en_title)
        p_desc = (en_desc or desc) if is_overseas else (desc or en_desc)
        p_tags = (en_tags or tags) if is_overseas else (tags or en_tags)

        up = UPLOADERS[p]
        print(f"\n🚀 [{p}] 开始{'演练' if dry_run else '发布'}: {vpath.name} | 标题: {p_title}")
        cb = lambda pct, msg, _p=p, **kw: print(f"  [{_p}] {int(pct * 100):3d}% | {msg}")

        try:
            if p == "youtube":
                res = up.publish_video(
                    video_source=str(vpath),
                    title=p_title,
                    desc=p_desc,
                    tags=p_tags,
                    privacy_status=youtube_privacy,
                    dry_run=dry_run,
                    progress_callback=cb,
                )
            elif p in ("tiktok", "meta"):
                res = up.publish_video(
                    video_source=str(vpath),
                    title=p_title,
                    desc=p_desc,
                    tags=p_tags,
                    headless=headless,
                    dry_run=dry_run,
                    progress_callback=cb,
                )
            elif dry_run:
                if not vpath.exists():
                    raise FileNotFoundError(f"视频文件不存在: {vpath}")
                res = {
                    "success": True,
                    "dry_run": True,
                    "platform": p,
                    "title": p_title,
                    "message": f"【演练通过】{p} 视频就绪 ({vpath.name})",
                }
            elif p == "douyin":
                res = up.publish_video(
                    video_source=str(vpath),
                    title=p_title,
                    desc=p_desc,
                    tags=p_tags,
                    headless=headless,
                    progress_callback=cb,
                )
            else:
                res = up.publish_video(
                    video_source=str(vpath),
                    title=p_title,
                    desc=p_desc,
                    tags=p_tags,
                    progress_callback=cb,
                )
            results.append({"platform": p, **res})
            print(f"✅ [{p}] {res.get('message', '完成')}")
        except Exception as e:
            results.append({"platform": p, "success": False, "message": str(e)})
            print(f"❌ [{p}] 失败: {e}")

    return results


def main():
    parser = argparse.ArgumentParser(description="M2V 全平台本地一键发布工具")
    parser.add_argument("--status", action="store_true", help="查看全部 7 个平台本地会话状态")
    parser.add_argument("--auth", metavar="PLATFORM", help="为指定平台打开登录向导 (tiktok/meta/xhs/douyin/wechat/youtube)")
    parser.add_argument("--video", help="通用视频文件路径（未区分中英文时使用）")
    parser.add_argument("--en-video", help="海外平台 (YouTube/TikTok/Meta) 使用的英文视频路径")
    parser.add_argument("--zh-video", help="国内平台 (小红书/抖音/视频号/B站) 使用的中文/双语视频路径")
    parser.add_argument("--platforms", default="all", help="目标平台: all / overseas / domestic 或逗号分隔")
    parser.add_argument("--title", default="", help="中文标题")
    parser.add_argument("--en-title", default="", help="英文标题")
    parser.add_argument("--desc", default="", help="中文描述")
    parser.add_argument("--en-desc", default="", help="英文描述")
    parser.add_argument("--tags", default="", help="中文逗号分隔标签")
    parser.add_argument("--en-tags", default="", help="英文逗号分隔标签")
    parser.add_argument("--public", action="store_true", help="YouTube 直接公开 (默认 unlisted)")
    parser.add_argument("--visible", action="store_true", help="使用前台可见 Chrome 窗口发布")
    parser.add_argument("--dry-run", action="store_true", help="演练校验，不真实上传")
    args = parser.parse_args()

    if args.status:
        print_status()
        return

    if args.auth:
        run_auth(args.auth)
        return

    en_p = Path(os.path.expanduser(args.en_video or args.video)).resolve() if (args.en_video or args.video) else None
    zh_p = Path(os.path.expanduser(args.zh_video or args.video)).resolve() if (args.zh_video or args.video) else None
    if not en_p and not zh_p:
        parser.print_help()
        sys.exit(1)

    platforms = resolve_platforms(args.platforms)
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    en_tags = [t.strip() for t in args.en_tags.split(",") if t.strip()]

    results = publish_to_platforms(
        platforms=platforms,
        en_video=en_p,
        zh_video=zh_p,
        title=args.title,
        en_title=args.en_title,
        desc=args.desc,
        en_desc=args.en_desc,
        tags=tags,
        en_tags=en_tags,
        youtube_privacy="public" if args.public else "unlisted",
        headless=not args.visible,
        dry_run=args.dry_run,
    )

    ok = sum(1 for r in results if r.get("success"))
    print(f"\n📊 发布汇总: {ok}/{len(results)} 成功")


if __name__ == "__main__":
    main()
