#!/usr/bin/env python3
"""
一键配置 Hugging Face Space 环境变量与 Secrets

支持从 .env 文件自动解析并批量写入目标 Space，无需在网页上手动一条条输入。
用法:
    python scripts/setup_hf_space.py --token <HF_WRITE_TOKEN> --space LucaZhou/suno2mv-api-staging --env-file work/paddle-sandbox.env
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from huggingface_hub import HfApi

# 敏感字段归入 Secrets（页面隐藏明文），其余字段归入 Variables（公开可见）
SECRET_KEYS = {
    "PADDLE_API_KEY",
    "PADDLE_SANDBOX_API_KEY",
    "PADDLE_CLIENT_TOKEN",
    "PADDLE_WEBHOOK_SECRET",
    "SECRET_KEY",
    "DATABASE_URL",
    "R2_SECRET_ACCESS_KEY",
    "R2_ACCESS_KEY_ID",
    "S3_SECRET_KEY",
    "S3_ACCESS_KEY",
    "STRIPE_API_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "LEMONSQUEEZY_API_KEY",
    "LEMONSQUEEZY_WEBHOOK_SECRET",
}


def parse_env_file(file_path: Path) -> dict[str, str]:
    if not file_path.is_file():
        raise FileNotFoundError(f"未找到环境配置文件: {file_path}")

    env_vars: dict[str, str] = {}
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            # 去除可能的首尾引号
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            if val:
                env_vars[key] = val
    return env_vars


def main() -> None:
    parser = argparse.ArgumentParser(description="一键批量配置 Hugging Face Space 环境变量与密钥")
    parser.add_argument("--token", default=os.getenv("HF_TOKEN"), help="Hugging Face 用户 Write 权限 Token (也可通过环境变量 HF_TOKEN 传入)")
    parser.add_argument("--space", default="LucaZhou/suno2mv-api-staging", help="目标 Space 仓库 ID (例如 LucaZhou/suno2mv-api-staging)")
    parser.add_argument("--env-file", default="work/paddle-sandbox.env", help="源配置文件路径 (默认 work/paddle-sandbox.env)")
    parser.add_argument("--create", action="store_true", help="若 Space 尚不存在，则自动以 Gradio SDK 创建")
    parser.add_argument("--push", action="store_true", help="配置完成后自动将当前代码推送到目标 Space")

    args = parser.parse_args()

    token = args.token
    if not token:
        print("❌ 错误: 未提供 Hugging Face Token！\n请通过 --token <TOKEN> 或环境变量 HF_TOKEN 提供具有 Write 权限的 Token。\n可在 https://huggingface.co/settings/tokens 获取。")
        sys.exit(1)

    space_id = args.space.strip()
    env_file = Path(args.env_file)

    try:
        env_vars = parse_env_file(env_file)
    except Exception as e:
        print(f"❌ 读取配置文件失败: {e}")
        sys.exit(1)

    api = HfApi(token=token)

    # 1. 验证用户凭据
    try:
        user_info = api.whoami()
        print(f"🔑 认证成功: 用户名 {user_info.get('name')} (HF 账号已就绪)")
    except Exception as e:
        print(f"❌ HF Token 认证失败: {e}")
        sys.exit(1)

    # 2. 如果指定了 --create 或自动检测创建
    if args.create:
        try:
            print(f"📦 正在检查/创建 Space: {space_id} (SDK: gradio)...")
            api.create_repo(
                repo_id=space_id,
                repo_type="space",
                space_sdk="gradio",
                exist_ok=True,
            )
            print(f"✅ Space {space_id} 已确认就绪！")
        except Exception as e:
            print(f"⚠️ 检查/创建 Space 提示: {e}")

    # 3. 批量同步变量和 Secrets
    print(f"\n🚀 开始向 Space [{space_id}] 同步配置 (共 {len(env_vars)} 项)...")

    success_secrets = 0
    success_vars = 0

    for key, val in env_vars.items():
        is_secret = key in SECRET_KEYS
        target_type = "Secret" if is_secret else "Variable"

        try:
            if is_secret:
                api.add_space_secret(repo_id=space_id, key=key, value=val)
                success_secrets += 1
            else:
                api.add_space_variable(repo_id=space_id, key=key, value=val)
                success_vars += 1
            print(f"  ✅ [{target_type}] {key} 设置成功")
        except Exception as e:
            print(f"  ❌ [{target_type}] {key} 设置失败: {e}")

    print(f"\n🎉 配置完成！共写入 {success_secrets} 个 Secrets 和 {success_vars} 个 Variables。")
    print(f"🔗 查看 Space 设置: https://huggingface.co/spaces/{space_id}/settings")

    # 4. 如果指定了 --push，自动同步当前代码至目标 Space
    if args.push:
        import subprocess
        user_name = user_info.get("name", "git")
        push_url = f"https://{user_name}:{token}@huggingface.co/spaces/{space_id}"
        print(f"\n📦 正在将当前代码推送到目标 Space [{space_id}]...")
        cmd = ["git", "push", "--force", push_url, "HEAD:refs/heads/main"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            print(f"🚀 代码推送成功！已触发 Space 自动构建。\n🔗 查看实时构建日志: https://huggingface.co/spaces/{space_id}")
        else:
            print(f"❌ 代码推送失败:\n{res.stderr or res.stdout}")


if __name__ == "__main__":
    main()
