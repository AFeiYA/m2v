"""
ComfyUI 本地视频/图像生成服务客户端 (ComfyUIClient)
------------------------------------------------
调度本机部署的 ComfyUI (默认 http://127.0.0.1:8188) 执行 LTX-Video, Wan 2.1 或 FLUX 工作流。
负责：
1. 探活与后台自启动服务
2. 动态参数填充与工作流组装
3. 任务排队与异步执行状态轮询
4. 产物提取、重命名归档为多 Take 视频切片
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from src.compilers import compile_shot_for_model, get_compiler
from src.storyboard_schema import GlobalBibles, SequencePlan, ShotPlan, Take

logger = logging.getLogger(__name__)

DEFAULT_COMFYUI_URL = "http://127.0.0.1:8188"
DEFAULT_COMFYUI_DIR = "/Users/luca/AIGC/ComfyUI"
DEFAULT_COMFYUI_PYTHON = "/Users/luca/AIGC/.venv/bin/python"


class ComfyUIClient:
    """与本地 ComfyUI API 进行通讯的调度客户端"""

    def __init__(
        self,
        base_url: str = DEFAULT_COMFYUI_URL,
        comfy_dir: str = DEFAULT_COMFYUI_DIR,
        python_bin: str = DEFAULT_COMFYUI_PYTHON,
    ):
        self.base_url = base_url.rstrip("/")
        self.comfy_dir = Path(comfy_dir)
        self.python_bin = Path(python_bin)
        self.client_id = str(uuid.uuid4())
        self._server_process: Optional[subprocess.Popen] = None
        self.workflows_dir = Path(__file__).parent / "workflows"

    # =========================================================================
    # 1. 探活与服务生命周期管理
    # =========================================================================

    def check_health(self) -> Dict[str, Any]:
        """检查 ComfyUI 是否在线并获取硬件运行状态"""
        url = f"{self.base_url}/system_stats"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Suno2MV-Client"})
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    devices = data.get("devices", [])
                    return {
                        "online": True,
                        "status": "connected",
                        "devices": devices,
                        "base_url": self.base_url,
                    }
        except Exception as e:
            return {
                "online": False,
                "status": "offline",
                "error": str(e),
                "base_url": self.base_url,
            }
        return {"online": False, "status": "offline", "base_url": self.base_url}

    def ensure_server_running(self, timeout_sec: int = 25) -> bool:
        """若服务未启动，尝试拉起本地 ComfyUI 进程并等待上线"""
        health = self.check_health()
        if health.get("online"):
            return True

        if not self.comfy_dir.exists() or not self.python_bin.exists():
            logger.warning(
                "ComfyUI 目录或虚拟环境未找到: %s / %s",
                self.comfy_dir,
                self.python_bin,
            )
            return False

        logger.info("正在启动本地 ComfyUI 服务进程...")
        main_py = self.comfy_dir / "main.py"
        try:
            # 使用 nohup 类似方式在后台启动
            self._server_process = subprocess.Popen(
                [
                    str(self.python_bin),
                    str(main_py),
                    "--listen",
                    "127.0.0.1",
                    "--port",
                    "8188",
                ],
                cwd=str(self.comfy_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as err:
            logger.error("启动 ComfyUI 失败: %s", err)
            return False

        # 等待服务就绪
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            time.sleep(1.5)
            if self.check_health().get("online"):
                logger.info("本地 ComfyUI 已成功上线！")
                return True

        logger.error("启动 ComfyUI 超时 (等待 %d 秒未响应)", timeout_sec)
        return False

    # =========================================================================
    # 2. 工作流载荷组装
    # =========================================================================

    def load_workflow_template(self, model_type: str) -> Dict[str, Any]:
        """加载对应模型的工作流 JSON 模板"""
        clean_type = model_type.lower().strip()
        if "i2v" in clean_type or "img2vid" in clean_type or "image" in clean_type:
            tmpl_file = self.workflows_dir / "ltx_i2v.json"
        elif "ltx" in clean_type:
            tmpl_file = self.workflows_dir / "ltx_video.json"
        elif "wan" in clean_type:
            tmpl_file = self.workflows_dir / "wan21_t2v.json"
        elif "flux" in clean_type:
            tmpl_file = self.workflows_dir / "flux_schnell.json"
        else:
            tmpl_file = self.workflows_dir / "ltx_video.json"

        if not tmpl_file.exists():
            raise FileNotFoundError(f"找不到工作流模板: {tmpl_file}")

        with open(tmpl_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def build_workflow_payload(
        self,
        model_type: str,
        positive_prompt: str,
        negative_prompt: str = "",
        width: int = 768,
        height: int = 512,
        length: int = 25,
        steps: int = 20,
        cfg: float = 3.0,
        seed: Optional[int] = None,
        frame_rate: int = 16,
        input_image: Optional[str] = None,
    ) -> Dict[str, Any]:
        """根据分镜要求，组装向 ComfyUI /prompt 提交的完整计算图字典"""
        workflow = self.load_workflow_template(model_type)
        actual_seed = seed if seed is not None else int(time.time() * 1000) % (2**31)

        for _, node in workflow.items():
            class_type = node.get("class_type", "")
            inputs = node.setdefault("inputs", {})

            # 1. 提示词节点
            if class_type == "CLIPTextEncode":
                text_val = inputs.get("text", "")
                if "{POSITIVE_PROMPT}" in str(text_val) or text_val == "{POSITIVE_PROMPT}":
                    inputs["text"] = positive_prompt
                elif "{NEGATIVE_PROMPT}" in str(text_val) or text_val == "{NEGATIVE_PROMPT}":
                    inputs["text"] = negative_prompt or "text, watermark, subtitles, low quality"

            # 2. Latent 尺寸与帧数节点 (LTX-Video T2V & I2V)
            elif class_type in ("EmptyLTXVLatentVideo", "EmptyHunyuanLatentVideo"):
                if "width" in inputs:
                    inputs["width"] = width
                if "height" in inputs:
                    inputs["height"] = height
                if "length" in inputs:
                    inputs["length"] = length

            # 3. 图像 Latent 节点 (FLUX)
            elif class_type == "EmptyLatentImage":
                if "width" in inputs:
                    inputs["width"] = width
                if "height" in inputs:
                    inputs["height"] = height

            # 4. 图生视频图像加载与缩放 (I2V)
            elif class_type == "LoadImage":
                if input_image:
                    inputs["image"] = input_image
                elif "{INPUT_IMAGE}" in str(inputs.get("image", "")):
                    inputs["image"] = input_image or "example.png"

            elif class_type == "ImageScale":
                if "width" in inputs:
                    inputs["width"] = width
                if "height" in inputs:
                    inputs["height"] = height

            elif class_type == "LTXVImgToVideo":
                if "width" in inputs:
                    inputs["width"] = width
                if "height" in inputs:
                    inputs["height"] = height
                if "length" in inputs:
                    inputs["length"] = length

            # 5. KSampler 采样器参数
            elif class_type in ("KSampler", "KSamplerAdvanced"):
                if "steps" in inputs:
                    inputs["steps"] = steps
                if "cfg" in inputs:
                    inputs["cfg"] = cfg
                if "seed" in inputs:
                    inputs["seed"] = actual_seed

            # 6. 视频合成节点
            elif class_type == "VHS_VideoCombine":
                if "frame_rate" in inputs:
                    inputs["frame_rate"] = frame_rate

        return workflow

    # =========================================================================
    # 3. API 交互与任务排队轮询
    # =========================================================================

    def queue_prompt(self, workflow_payload: Dict[str, Any]) -> str:
        """向 ComfyUI 发送 /prompt 请求并获取 prompt_id"""
        url = f"{self.base_url}/prompt"
        post_data = {
            "prompt": workflow_payload,
            "client_id": self.client_id,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(post_data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                prompt_id = data.get("prompt_id")
                if not prompt_id:
                    raise RuntimeError(f"ComfyUI 未返回 prompt_id: {data}")
                return prompt_id
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"ComfyUI /prompt 报错 ({err.code}): {err_body}")

    def get_prompt_history(self, prompt_id: str) -> Optional[Dict[str, Any]]:
        """获取指定 prompt_id 的执行历史与产物记录"""
        url = f"{self.base_url}/history/{prompt_id}"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get(prompt_id)
        except Exception:
            return None

    def poll_completion(
        self,
        prompt_id: str,
        timeout_sec: float = 600.0,
        interval_sec: float = 1.0,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> Dict[str, Any]:
        """轮询直至任务完成，返回 outputs 字典"""
        start_time = time.time()
        while time.time() - start_time < timeout_sec:
            history = self.get_prompt_history(prompt_id)
            if history:
                # 任务已执行结束
                outputs = history.get("outputs", {})
                status_info = history.get("status", {})
                if status_info.get("status_str") == "error":
                    messages = status_info.get("messages", [])
                    raise RuntimeError(f"ComfyUI 执行失败: {messages}")
                if progress_callback:
                    progress_callback(100.0, "生成完成！")
                return outputs

            elapsed = time.time() - start_time
            # 简单估算进度反馈
            if progress_callback:
                pseudo_p = min(95.0, 10.0 + (elapsed / 25.0) * 85.0)
                progress_callback(pseudo_p, f"模型推理中... ({int(elapsed)}s)")

            time.sleep(interval_sec)

        raise TimeoutError(f"等待 ComfyUI 任务 ({prompt_id}) 超时 ({timeout_sec}s)")

    # =========================================================================
    # 4. 产物提取与多 Take 归档
    # =========================================================================

    def extract_output_media(
        self, outputs: Dict[str, Any], target_dir: Path, file_stem: str
    ) -> Tuple[str, str]:
        """
        从 ComfyUI 输出字典中提取视频 (mp4) 或图像 (png)，复制到项目 clips 目录。
        返回 (media_type, relative_media_path)
        """
        target_dir.mkdir(parents=True, exist_ok=True)
        comfy_output_dir = self.comfy_dir / "output"

        # 优先提取视频 (VHS_VideoCombine 输出)
        for _, node_data in outputs.items():
            # VHS_VideoCombine outputs
            gifs = node_data.get("gifs", [])
            for item in gifs:
                filename = item.get("filename")
                fullpath = item.get("fullpath")
                subfolder = item.get("subfolder", "")
                src_file = Path(fullpath) if fullpath and Path(fullpath).exists() else (comfy_output_dir / subfolder / filename if filename else None)
                if src_file and src_file.exists():
                    dest_file = target_dir / f"{file_stem}.mp4"
                    shutil.copy2(src_file, dest_file)
                    return "video", str(dest_file)

        # 其次提取图像 (SaveImage 输出)
        for _, node_data in outputs.items():
            images = node_data.get("images", [])
            for item in images:
                filename = item.get("filename")
                subfolder = item.get("subfolder", "")
                if filename:
                    src_file = comfy_output_dir / subfolder / filename
                    dest_file = target_dir / f"{file_stem}.png"
                    if src_file.exists():
                        shutil.copy2(src_file, dest_file)
                        return "image", str(dest_file)

        raise FileNotFoundError("未在 ComfyUI 任务产物中找到有效的视频或图像文件")

    def generate_take_for_shot(
        self,
        shot: ShotPlan,
        project_dir: Path,
        model_type: str = "ltx_video",
        bibles: Optional[GlobalBibles] = None,
        sequence: Optional[SequencePlan] = None,
        resolution: str = "768x512",
        steps: int = 20,
        seed: Optional[int] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> Take:
        """
        为指定 ShotPlan 生成一个完整的 Take 产物：
        1. 编译专有提示词
        2. 组装 ComfyUI API 请求
        3. 提交并等待执行完毕
        4. 归档 MP4 视频切片至 output/{project}/clips/
        5. 生成并返回 Take 数据实体
        """
        # 1. 确保服务在线
        if not self.ensure_server_running():
            raise RuntimeError("无法连接或启动本地 ComfyUI (端口 8188)！请确认环境配置。")

        # 2. 编译提示词
        model_alias = "ltx" if "ltx" in model_type.lower() else ("flux" if "flux" in model_type.lower() else "wan")
        compiler = get_compiler(model_alias)
        compiled_payload = compiler.compile(shot, bibles=bibles, sequence=sequence)

        # 3. 维度与帧数计算
        try:
            w_str, h_str = resolution.split("x")
            width, height = int(w_str), int(h_str)
        except Exception:
            width, height = (768, 512) if model_alias == "ltx" else (832, 480)

        # 计算帧数：根据镜头时长 (秒) * 帧率 (默认 16 fps)，LTX-Video 需满足 (length - 1) % 8 == 0
        fps = 16
        duration = max(1.5, shot.duration or 3.0)
        raw_frames = int(duration * fps)
        # 对齐到 8 的倍数 + 1 (如 17, 25, 33, 41, 49)
        k = max(2, round((raw_frames - 1) / 8))
        length = k * 8 + 1
        length = min(65, max(17, length))

        cfg = 3.0 if model_alias == "ltx" else (1.0 if model_alias == "flux" else 6.0)

        # 4. 组装工作流并提交
        if progress_callback:
            progress_callback(5.0, "正在组装本地工作流载荷...")

        payload = self.build_workflow_payload(
            model_type=model_type,
            positive_prompt=compiled_payload.prompt,
            negative_prompt=compiled_payload.negative_prompt,
            width=width,
            height=height,
            length=length,
            steps=steps,
            cfg=cfg,
            seed=seed,
            frame_rate=fps,
        )

        prompt_id = self.queue_prompt(payload)
        logger.info("已提交 ComfyUI 任务 ID: %s (Shot: %s)", prompt_id, shot.id)

        # 5. 轮询等待
        outputs = self.poll_completion(
            prompt_id=prompt_id,
            timeout_sec=600.0,
            progress_callback=progress_callback,
        )

        # 6. 文件落盘归档
        clips_dir = project_dir / "clips"
        # 统计已有 Take 确定序号
        current_takes = shot.takes or []
        take_counter = len(current_takes) + 1
        take_id = f"take_{take_counter:03d}"
        file_stem = f"{shot.id}_{take_id}"

        media_type, full_dest_path = self.extract_output_media(
            outputs=outputs, target_dir=clips_dir, file_stem=file_stem
        )

        # 相对路径方便前端与项目持久化
        try:
            rel_media_path = str(Path(full_dest_path).relative_to(project_dir.parent.parent))
        except Exception:
            rel_media_path = full_dest_path

        take = Take(
            id=take_id,
            shot_id=shot.id,
            provider=f"comfyui_{model_alias}",
            media_type=media_type,  # type: ignore
            media_path=rel_media_path,
            video_path=rel_media_path if media_type == "video" else "",
            prompt=compiled_payload.prompt,
            seed=seed,
            selected=True,  # 新生成的 Take 默认置为选中正片
            score=5.0,
        )
        return take

    def generate_keyframe_for_shot(
        self,
        shot: ShotPlan,
        project_dir: Path,
        bibles: Optional[GlobalBibles] = None,
        sequence: Optional[SequencePlan] = None,
        resolution: str = "768x448",
        steps: int = 4,
        seed: Optional[int] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> str:
        """
        为指定 ShotPlan 生成超写真电影级首帧图 (Keyframe):
        1. 编译 FLUX 视觉提示词 (富含材质、光影、微观细节)
        2. 组装 FLUX Schnell 工作流并执行
        3. 保存至 output/{project}/keyframes/shot_{idx}_keyframe_{take}.png
        4. 更新 shot.preview_image 字段并返回相对路径
        """
        if not self.ensure_server_running():
            raise RuntimeError("无法连接或启动本地 ComfyUI 服务！")

        compiler = get_compiler("flux")
        compiled = compiler.compile_keyframe(shot, bibles=bibles, sequence=sequence)

        try:
            w_str, h_str = resolution.split("x")
            width, height = int(w_str), int(h_str)
        except Exception:
            width, height = 768, 448

        if progress_callback:
            progress_callback(10.0, "正在组装 FLUX 电影首帧计算图...")

        payload = self.build_workflow_payload(
            model_type="flux_schnell",
            positive_prompt=compiled.prompt,
            negative_prompt=compiled.negative_prompt or "blurry, low quality, cartoon, 3d render, watermark, text",
            width=width,
            height=height,
            steps=steps,
            cfg=1.0,
            seed=seed,
        )

        prompt_id = self.queue_prompt(payload)
        logger.info("已提交 FLUX 首帧生成任务: %s (Shot: %s)", prompt_id, shot.id)

        outputs = self.poll_completion(
            prompt_id=prompt_id,
            timeout_sec=180.0,
            progress_callback=progress_callback,
        )

        keyframes_dir = project_dir / "keyframes"
        file_stem = f"{shot.id}_keyframe_{int(time.time()) % 10000:04d}"
        media_type, full_dest_path = self.extract_output_media(
            outputs=outputs, target_dir=keyframes_dir, file_stem=file_stem
        )

        try:
            rel_path = str(Path(full_dest_path).relative_to(project_dir.parent.parent))
        except Exception:
            rel_path = full_dest_path

        shot.preview_image = rel_path
        if not shot.path:
            shot.path = rel_path
            shot.type = "image"

        return rel_path

    def generate_endframe_for_shot(
        self,
        shot: ShotPlan,
        project_dir: Path,
        bibles: Optional[GlobalBibles] = None,
        sequence: Optional[SequencePlan] = None,
        resolution: str = "768x448",
        steps: int = 4,
        seed: Optional[int] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> str:
        """
        为指定 ShotPlan 生成可选尾帧图 (Endframe):
        用于一镜到底无缝衔接、首尾帧插值或下一镜头首帧继承。
        """
        if not self.ensure_server_running():
            raise RuntimeError("无法连接或启动本地 ComfyUI 服务！")

        compiler = get_compiler("flux")
        compiled = compiler.compile_endframe(shot, bibles=bibles, sequence=sequence)
        if not compiled:
            # 若未显式定义 endframe_prompt，使用 shot.effective_keyframe_prompt 稍加演进
            compiled = compiler.compile_keyframe(shot, bibles=bibles, sequence=sequence)

        try:
            w_str, h_str = resolution.split("x")
            width, height = int(w_str), int(h_str)
        except Exception:
            width, height = 768, 448

        if progress_callback:
            progress_callback(10.0, "正在生成电影尾帧图 (一镜到底/无缝切换)...")

        payload = self.build_workflow_payload(
            model_type="flux_schnell",
            positive_prompt=compiled.prompt,
            negative_prompt=compiled.negative_prompt or "blurry, low quality, cartoon, 3d render, watermark, text",
            width=width,
            height=height,
            steps=steps,
            cfg=1.0,
            seed=seed,
        )

        prompt_id = self.queue_prompt(payload)
        logger.info("已提交 FLUX 尾帧生成任务: %s (Shot: %s)", prompt_id, shot.id)

        outputs = self.poll_completion(
            prompt_id=prompt_id,
            timeout_sec=180.0,
            progress_callback=progress_callback,
        )

        keyframes_dir = project_dir / "keyframes"
        file_stem = f"{shot.id}_endframe_{int(time.time()) % 10000:04d}"
        media_type, full_dest_path = self.extract_output_media(
            outputs=outputs, target_dir=keyframes_dir, file_stem=file_stem
        )

        try:
            rel_path = str(Path(full_dest_path).relative_to(project_dir.parent.parent))
        except Exception:
            rel_path = full_dest_path

        shot.endframe_image = rel_path
        return rel_path

    def generate_i2v_take_for_shot(
        self,
        shot: ShotPlan,
        project_dir: Path,
        keyframe_path: Optional[str | Path] = None,
        bibles: Optional[GlobalBibles] = None,
        sequence: Optional[SequencePlan] = None,
        resolution: str = "768x448",
        steps: int = 20,
        seed: Optional[int] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> Take:
        """
        以指定首帧图为物理输入，运行 LTX-Video 图生视频 (I2V) 产生动态 Take:
        1. 确保首帧图像复制到 ComfyUI input 目录
        2. 编译镜头运动提示词 (纯运镜与时空动势，杜绝静态重复)
        3. 组装 ltx_i2v 工作流提交执行
        4. 归档 MP4 视频切片至 output/{project}/clips/
        """
        if not self.ensure_server_running():
            raise RuntimeError("无法连接或启动本地 ComfyUI 服务！")

        # 查找首帧图像
        kf_file = None
        if keyframe_path:
            p = Path(keyframe_path)
            if not p.is_absolute():
                p = (project_dir.parent.parent / keyframe_path).resolve()
            if p.exists():
                kf_file = p

        if not kf_file and shot.preview_image:
            p = Path(shot.preview_image)
            if not p.is_absolute():
                p = (project_dir.parent.parent / shot.preview_image).resolve()
            if p.exists():
                kf_file = p

        if not kf_file or not kf_file.exists():
            raise FileNotFoundError(f"未找到有效的首帧图片，无法执行 I2V: {keyframe_path or shot.preview_image}")

        # 拷贝到 ComfyUI input 目录
        comfy_input_dir = self.comfy_dir / "input"
        comfy_input_dir.mkdir(parents=True, exist_ok=True)
        target_input_name = f"suno2mv_{shot.id}_kf.png"
        shutil.copy2(kf_file, comfy_input_dir / target_input_name)

        # 编译运动提示词 (动静解耦)
        compiler = get_compiler("ltx")
        compiled = compiler.compile_motion(shot, bibles=bibles, sequence=sequence)

        try:
            w_str, h_str = resolution.split("x")
            width, height = int(w_str), int(h_str)
        except Exception:
            width, height = 768, 448

        fps = 16
        duration = max(1.5, shot.duration or 3.0)
        raw_frames = int(duration * fps)
        k = max(2, round((raw_frames - 1) / 8))
        length = min(65, max(17, k * 8 + 1))

        if progress_callback:
            progress_callback(10.0, "正在组装 LTX-I2V 图生视频计算图...")

        payload = self.build_workflow_payload(
            model_type="ltx_i2v",
            positive_prompt=compiled.prompt,
            negative_prompt=compiled.negative_prompt,
            width=width,
            height=height,
            length=length,
            steps=steps,
            cfg=3.0,
            seed=seed,
            frame_rate=fps,
            input_image=target_input_name,
        )

        prompt_id = self.queue_prompt(payload)
        logger.info("已提交 LTX-I2V 任务 ID: %s (Shot: %s)", prompt_id, shot.id)

        outputs = self.poll_completion(
            prompt_id=prompt_id,
            timeout_sec=600.0,
            progress_callback=progress_callback,
        )

        clips_dir = project_dir / "clips"
        current_takes = shot.takes or []
        take_counter = len(current_takes) + 1
        take_id = f"take_{take_counter:03d}"
        file_stem = f"{shot.id}_{take_id}"

        media_type, full_dest_path = self.extract_output_media(
            outputs=outputs, target_dir=clips_dir, file_stem=file_stem
        )

        try:
            rel_media_path = str(Path(full_dest_path).relative_to(project_dir.parent.parent))
        except Exception:
            rel_media_path = full_dest_path

        take = Take(
            id=take_id,
            shot_id=shot.id,
            provider="comfyui_ltx_i2v",
            media_type="video",
            media_path=rel_media_path,
            video_path=rel_media_path,
            prompt=compiled.prompt,
            seed=seed,
            selected=True,
            score=5.0,
        )
        return take

    def generate_two_stage_take(
        self,
        shot: ShotPlan,
        project_dir: Path,
        bibles: Optional[GlobalBibles] = None,
        sequence: Optional[SequencePlan] = None,
        resolution: str = "768x448",
        video_steps: int = 20,
        keyframe_steps: int = 4,
        seed: Optional[int] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> Tuple[str, Take]:
        """一键串联两阶段：FLUX 生成首帧 + LTX-I2V 驱动动态视频"""
        if progress_callback:
            progress_callback(5.0, "【阶段 1/2】正在生成电影级写真首帧 (FLUX 12B)...")

        kf_path = self.generate_keyframe_for_shot(
            shot=shot,
            project_dir=project_dir,
            bibles=bibles,
            sequence=sequence,
            resolution=resolution,
            steps=keyframe_steps,
            seed=seed,
            progress_callback=progress_callback,
        )

        if progress_callback:
            progress_callback(50.0, "【阶段 2/2】首帧已锁定！正在驱动镜头动态视频 (LTX-I2V)...")

        take = self.generate_i2v_take_for_shot(
            shot=shot,
            project_dir=project_dir,
            keyframe_path=kf_path,
            bibles=bibles,
            sequence=sequence,
            resolution=resolution,
            steps=video_steps,
            seed=seed,
            progress_callback=progress_callback,
        )
        return kf_path, take


_client_instance: Optional[ComfyUIClient] = None


def get_comfyui_client() -> ComfyUIClient:
    """获取单例 ComfyUIClient 实例"""
    global _client_instance
    if _client_instance is None:
        _client_instance = ComfyUIClient()
    return _client_instance
