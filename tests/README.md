# 测试运行范围

## CI 保留的检查

纯逻辑、Schema、对齐算法的模拟回归、接口、发布状态及会话隔离测试继续运行。账号状态使用模拟 Uploader；文件操作使用临时目录，不要求真实登录、不发布真实内容、不修改真实 Token。

HF 入口启动和合成音频的音频分析测试继续留在 CI。Motion 渲染测试需要 Node、Chrome 和 FFmpeg，现有工作流已准备这些依赖，并设置 `RUN_MOTION_RENDER=1`，因此也继续保留。

## 仅本地运行

以下测试标记 `local_only`：

- 已保存的真实歌曲基线 JSON 校验。
- 使用真实人声、歌词和模型进行完整对齐回归。
- 使用本地歌曲素材导出歌词视频和进行 API 导出验证。

它们依赖未提交的私人媒体资产或模型，并不适合作为每次部署的前置条件。工作流继续使用 `-m "not local_only"`；`tests/conftest.py` 还会在 `CI=true/1` 或 `GITHUB_ACTIONS=true/1` 时自动跳过这类测试，避免新任务忘记添加筛选条件。

```sh
# 常规检查
python -m pytest tests/ -m "not local_only"

# 本地素材/模型集成检查（缺少素材会跳过）
python -m pytest tests/ -m local_only
```

新增测试应按真实依赖分类。调用第三方接口但已经被模拟的测试仍属于 CI；不要为了让 CI 通过而跳过能稳定验证的逻辑。
