"""
批量视频生成器 (BatchVideoGenerator)
-----------------------------------
为指定的分镜范围批量调度本地 ComfyUI 生成高画质视频 Takes，
并在每镜完成后即刻落盘更新 alignment.json，方便实时在 Web 端监看。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from src.storyboard_schema import AlignmentProject
from src.video_providers import get_comfyui_client


def batch_generate_shots(
    json_path: str | Path,
    start_shot_idx: int = 2,
    end_shot_idx: int = 10,
    model_type: str = "ltx_video",
    resolution: str = "768x448",
    steps: int = 10,
    mode: str = "two_stage",
):
    json_file = Path(json_path).resolve()
    if not json_file.exists():
        raise FileNotFoundError(f"找不到工程文件: {json_file}")

    project = AlignmentProject.load_json(json_file)
    client = get_comfyui_client()

    print("🔍 正在检查本地 ComfyUI 服务状态...")
    health = client.check_health()
    if not health.get("online"):
        print("⚡ 正在启动本地 ComfyUI 服务进程...")
        if not client.ensure_server_running(timeout_sec=25):
            raise RuntimeError("无法连接或启动本地 ComfyUI！请检查环境。")
    print("🟢 ComfyUI 已在线！")

    # 选取目标镜头
    target_shots = []
    for s in project.storyboard:
        if start_shot_idx <= s.shot_id <= end_shot_idx:
            target_shots.append(s)

    total = len(target_shots)
    if total == 0:
        print(f"⚠️ 未在分镜列表中找到序号介于 {start_shot_idx} ~ {end_shot_idx} 的镜头！")
        return

    mode_label = {
        "two_stage": "两阶段 (FLUX 12B首帧 + LTX-I2V电影级视频)",
        "keyframe_only": "仅生成电影首帧 (FLUX 12B)",
        "t2v": "纯文生视频 (LTX-Video T2V)",
    }.get(mode, mode)

    print(f"\n🎬 开始批量生成 {total} 个分镜镜头 (Shot {start_shot_idx} 至 Shot {end_shot_idx})")
    print(f"   模式: {mode_label} | 分辨率: {resolution} | 采样步数: {steps}")
    print("=" * 68)

    start_batch_time = time.time()

    for idx, shot in enumerate(target_shots, start=1):
        t0 = time.time()
        print(f"\n▶ [{idx}/{total}] 正在处理 Shot {shot.shot_id:03d} ({shot.id})")
        print(f"   ⏱️ 时长: {shot.duration:.2f}s | 景别: {shot.shot_size} | 运镜: {shot.camera_motion}")
        prompt_snippet = (shot.prompt_en or shot.action or "")[:85]
        print(f"   🎬 Prompt: {prompt_snippet}...")

        try:
            bibles = getattr(project, "bibles", None) or getattr(project, "global_bibles", None)

            if mode == "keyframe_only":
                kf_path = client.generate_keyframe_for_shot(
                    shot=shot,
                    project_dir=json_file.parent,
                    bibles=bibles,
                    resolution=resolution,
                    steps=4,
                )
                shot.preview_image = kf_path
                if not shot.path:
                    shot.path = kf_path
                    shot.type = "image"
                project.save_json(json_file)
                elapsed = time.time() - t0
                print(f"   📸 Shot {shot.shot_id:03d} 电影首帧生成成功！耗时: {elapsed:.1f}s -> {kf_path}")

            elif mode == "two_stage":
                kf_path, take = client.generate_two_stage_take(
                    shot=shot,
                    project_dir=json_file.parent,
                    bibles=bibles,
                    resolution=resolution,
                    video_steps=steps,
                    keyframe_steps=4,
                )
                if shot.takes is None:
                    shot.takes = []
                for t in shot.takes:
                    t.selected = False

                shot.takes.append(take)
                shot.selected_take_id = take.id
                shot.path = take.media_path
                shot.type = take.media_type
                shot.preview_image = kf_path

                project.save_json(json_file)
                elapsed = time.time() - t0
                print(f"   🎉 Shot {shot.shot_id:03d} 两阶段生成成功！耗时: {elapsed:.1f}s")
                print(f"      首帧: {kf_path} | 视频: {take.media_path}")

            else:  # t2v
                take = client.generate_take_for_shot(
                    shot=shot,
                    project_dir=json_file.parent,
                    model_type=model_type,
                    bibles=bibles,
                    resolution=resolution,
                    steps=steps,
                )
                if shot.takes is None:
                    shot.takes = []
                for t in shot.takes:
                    t.selected = False

                shot.takes.append(take)
                shot.selected_take_id = take.id
                shot.path = take.media_path
                shot.type = take.media_type

                project.save_json(json_file)
                elapsed = time.time() - t0
                print(f"   ✅ Shot {shot.shot_id:03d} T2V 生成成功！耗时: {elapsed:.1f}s")
                print(f"      产物: {take.media_path} (Take ID: {take.id})")

        except Exception as e:
            elapsed = time.time() - t0
            print(f"   ❌ Shot {shot.shot_id:03d} 生成失败 ({elapsed:.1f}s): {e}")

    total_elapsed = time.time() - start_batch_time
    print("\n" + "=" * 68)
    print(f"🎉 批量生成全部结束！总耗时: {total_elapsed:.1f}s ({total_elapsed/60:.1f}分钟)")
    print(f"📁 工程已保存至: {json_file}")


def main():
    parser = argparse.ArgumentParser(description="批量为分镜生成本地 ComfyUI 视频/首帧")
    parser.add_argument("--json", default="output/匠心入梦/匠心入梦_alignment.json", help="工程路径")
    parser.add_argument("--start", type=int, default=1, help="起始镜头序号 (如 1)")
    parser.add_argument("--end", type=int, default=10, help="结束镜头序号 (如 10)")
    parser.add_argument("--model", default="ltx_video", help="模型类型")
    parser.add_argument("--steps", type=int, default=15, help="采样步数")
    parser.add_argument("--resolution", default="768x448", help="分辨率")
    parser.add_argument(
        "--mode",
        default="two_stage",
        choices=["two_stage", "keyframe_only", "t2v"],
        help="生成模式: two_stage (FLUX首帧+I2V), keyframe_only (仅生首帧), t2v (直接文生视频)",
    )

    args = parser.parse_args()
    batch_generate_shots(
        json_path=args.json,
        start_shot_idx=args.start,
        end_shot_idx=args.end,
        model_type=args.model,
        resolution=args.resolution,
        steps=args.steps,
        mode=args.mode,
    )


if __name__ == "__main__":
    main()
