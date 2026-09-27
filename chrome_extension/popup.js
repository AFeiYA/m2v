document.addEventListener("DOMContentLoaded", async () => {
  const songNameEl = document.getElementById("songName");
  const btnExport = document.getElementById("btnExport");
  const serverInput = document.getElementById("serverInput");

  // 加载保存的服务器地址
  chrome.storage.local.get(["serverUrl"], (res) => {
    if (res && res.serverUrl) {
      serverInput.value = res.serverUrl;
    }
  });

  serverInput.addEventListener("change", () => {
    const val = serverInput.value.trim().replace(/\/+$/, "");
    chrome.storage.local.set({ serverUrl: val });
  });

  // 获取当前标签页
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

  if (!tab || !tab.url || !tab.url.includes("suno.com")) {
    songNameEl.textContent = "请先切换到 Suno 网页 (suno.com)";
    btnExport.disabled = true;
    return;
  }

  // 向当前 Suno 标签页请求歌曲信息
  chrome.tabs.sendMessage(tab.id, { action: "GET_TRACK_INFO" }, (response) => {
    if (chrome.runtime.lastError || !response) {
      songNameEl.textContent = "未检测到歌曲 (请刷新 Suno 页面)";
      return;
    }
    songNameEl.textContent = response.title || "未知曲目";
  });

  // 触发导出
  btnExport.addEventListener("click", () => {
    btnExport.disabled = true;
    btnExport.textContent = "⏳ 正在提取音轨与对齐...";
    chrome.tabs.sendMessage(tab.id, { action: "TRIGGER_EXPORT" }, (response) => {
      window.close();
    });
  });
});
