/* Shared, local-only interface helpers. No telemetry or remote code. */
globalThis.FoveaUI = {
  confirmRights(track) {
    if (track?.is_public === false) throw new Error("Song is not published. Publish it in Suno first.");
    return confirm(`Rights & publication confirmation\n\nSong: ${track?.title || "Selected song"}\n\nI confirm that:\n• This song is published in Suno (Publish).\n• I own the rights or have permission to download and process the song, lyrics and cover.\n• I am allowed to obtain this audio through Suno’s approved download channels and within my plan’s limits.\n• My intended use, including commercial use if applicable, is permitted.\n\nPublic playback is not download permission. This confirmation does not verify ownership, override Suno’s terms or authorize bypassing download limits. Fovea MV is independent of Suno.\n\nChoose OK only if all statements are true. Cancel to stop.`);
  },
  serverUrl(value) {
    const url = new URL(value);
    const local = ["localhost", "127.0.0.1"].includes(url.hostname);
    if ((!local && url.protocol !== "https:") || !["http:", "https:"].includes(url.protocol) || url.username || url.password) {
      throw new Error("Use HTTPS for a cloud server, or HTTP for localhost.");
    }
    if (url.pathname !== "/" || url.search || url.hash) throw new Error("Enter a server address without a path.");
    return url.origin;
  },
  async allowServer(value) {
    const origin = this.serverUrl(value);
    const permissions = { origins: [origin + "/*"] };
    if (!await chrome.permissions.contains(permissions) && !await chrome.permissions.request(permissions)) {
      throw new Error("Server access was not granted. Your previous server is unchanged.");
    }
    return origin;
  },
  async consent(server, kind) {
    const origin = this.serverUrl(server);
    const { dataConsent = [] } = await chrome.storage.local.get("dataConsent");
    const key = `${origin}/${kind}/v1`;
    if (dataConsent.includes(key)) return true;
    const message = kind === "video" ?
      "Create MP4 sends the selected song ID, lyrics/prompt, title, artist and cover to your selected server. The server downloads and processes the audio and stores the result. Continue?" :
      "Your selected server may receive the song link to check publication or download/extract audio when the original MP3 is unavailable. Continue?";
    if (!confirm(`${message}\n\nServer: ${origin}\nPrivacy details are available in the extension popup.`)) return false;
    await chrome.storage.local.set({ dataConsent: [...dataConsent, key] });
    return true;
  },
  async allowAudio(track) {
    if (!track?.audioUrl) return;
    // Chrome does not expose permissions to content scripts. The popup may
    // request optional access; the worker checks existing grants for page clicks.
    if (!chrome.permissions?.contains || !chrome.permissions?.request) return;
    const url = new URL(track.audioUrl);
    if (url.protocol !== "https:" || !["suno.ai", "suno.com", "cloudfront.net", "amazonaws.com"].some(host => url.hostname === host || url.hostname.endsWith(`.${host}`))) return;
    const permission = { origins: [url.origin + "/*"] };
    if (!await chrome.permissions.contains(permission) && !await chrome.permissions.request(permission)) {
      if (track.songId) { track.audioUrl = ""; return; }
      throw new Error("Audio-host access was not granted. Try downloading with the server instead.");
    }
  },
  error(detail) {
    const text = String(detail?.message || detail || "Unknown error");
    if (/context invalidated/i.test(text)) return "The extension was updated. Refresh Suno and try again.";
    if (/interrupted|Server restarted/i.test(text)) return "The server restarted during rendering. Start a new MP4 job to retry.";
    if (/not published|尚未公开|未公开|未发布/i.test(text)) return "Publish the song in Suno’s (…) menu first, then retry MP3 or MP4.";
    if (/HTTP (429|502|503|504)|fetch|connect|network/i.test(text)) return "The server is temporarily unavailable. Retry the download or resume your video job.";
    if (/not found|404/i.test(text)) return "This task or file is no longer available. Create a new video.";
    if (/permission/i.test(text)) return "Allow access to your selected server in the extension settings.";
    if (/20 minutes/i.test(text)) return "Still waiting. Use Resume to check the existing job without generating again.";
    return /[\u3400-\u9fff]|<html|Traceback|CUDA|ffmpeg|Exception|\.venv|\/app\/|\/Users\//i.test(text) ? "Processing failed. Check the task details and retry." : text;
  },
};
