/* ==========================================================
   Cast Studio — Virtual Artists & Character Engine Controller
   ========================================================== */
(() => {
  function getApiBase() {
    if (window.M2V_API_BASE) return window.M2V_API_BASE.replace(/\/+$/, "");
    const isLocal = location.hostname === "localhost" || location.hostname === "127.0.0.1";
    if (isLocal) return "http://localhost:8000";
    return location.origin;
  }

  function getAuthToken() {
    return localStorage.getItem("m2v_token") || "";
  }

  async function castApi(path, options = {}) {
    const base = getApiBase();
    const headers = options.headers || {};
    const token = getAuthToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;

    if (options.json) {
      headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(options.json);
      delete options.json;
    }
    options.headers = headers;

    const res = await fetch(`${base}${path}`, options);
    if (!res.ok) {
      let errDetail = `${res.status} ${res.statusText}`;
      try {
        const body = await res.json();
        if (body.detail) errDetail = body.detail;
      } catch (_) {}
      throw new Error(errDetail);
    }
    return res.json();
  }

  // Cast Studio State
  const state = {
    characters: [],
    selectedId: null,
    searchQuery: "",
    isLoading: false,
  };

  // Helper: Get active song in workspace
  function getActiveSong() {
    if (window.m2vStore) return window.m2vStore.getState().song.activeSong;
    if (window.m2vActiveSong) return window.m2vActiveSong;
    try {
      if (typeof sessionStorage !== "undefined") {
        return JSON.parse(sessionStorage.getItem("m2v_active_song") || "null");
      }
    } catch (_) {}
    return null;
  }

  // Helper: Gather song list from store or DOM
  function getAvailableSongs() {
    const songs = [];
    const seen = new Set();

    const activeSong = getActiveSong();
    if (activeSong && activeSong.id) {
      songs.push({ id: activeSong.id, title: activeSong.title || activeSong.id });
      seen.add(activeSong.id);
    }

    if (window.m2vStore) {
      const storeSongs = window.m2vStore.getState()?.library?.songs || [];
      storeSongs.forEach(s => {
        if (s.id && !seen.has(s.id)) {
          songs.push({ id: s.id, title: s.title || s.id });
          seen.add(s.id);
        }
      });
    }

    // Fallback: check DOM task items
    document.querySelectorAll(".task-card, .song-card").forEach(el => {
      const id = el.dataset.songId || el.id;
      if (id && !seen.has(id)) {
        const titleEl = el.querySelector(".song-title, .task-title, h3");
        const title = titleEl ? titleEl.textContent.trim() : id;
        songs.push({ id, title });
        seen.add(id);
      }
    });

    return songs;
  }

  // Render character cards list
  function renderRoster() {
    const container = document.getElementById("cast-roster-list");
    if (!container) return;

    const filtered = state.characters.filter(c => {
      if (!state.searchQuery) return true;
      const q = state.searchQuery.toLowerCase();
      const name = (c.identity?.name || c.name || "").toLowerCase();
      const alias = (c.identity?.alias || c.alias || "").toLowerCase();
      return name.includes(q) || alias.includes(q);
    });

    if (filtered.length === 0) {
      container.innerHTML = `
        <div class="cast-empty-roster">
          <p>No characters found.</p>
          <button type="button" id="cast-btn-empty-create" class="btn btn-sm btn-outline" style="margin-top:8px;">+ Create Character</button>
        </div>
      `;
      document.getElementById("cast-btn-empty-create")?.addEventListener("click", () => {
        openCreateModal();
      });
      return;
    }

    container.innerHTML = filtered.map(c => {
      const isActive = c.id === state.selectedId;
      const name = c.identity?.name || c.name || "Unnamed";
      const alias = c.identity?.alias || c.alias || "";
      const age = c.identity?.age || 16;
      const ageLocked = c.identity?.age_locked !== false;
      const tagline = c.identity?.tagline || c.tagline || "";
      const isLocked = Boolean(c.versioning?.is_locked);
      const version = c.versioning?.version || 1;
      const avatarUrl = c.assets?.thumbnail_url || c.assets?.primary_image_url || "";
      const boundCount = (c.bound_songs || []).length;
      const isOfficial = Boolean(c.is_official || c.user_id === "system" || c.id === "char_zero_soe_0618");

      const avatarContent = avatarUrl
        ? `<img src="${avatarUrl}" alt="${name}" class="cast-card-avatar">`
        : `<div class="cast-card-avatar">${name.charAt(0).toUpperCase()}</div>`;

      return `
        <div class="cast-card ${isActive ? "active" : ""}" data-char-id="${c.id}" role="button" tabindex="0">
          ${avatarContent}
          <div class="cast-card-info">
            <div class="cast-card-name-row">
              <span class="cast-card-name">${escapeHtml(name)}</span>
              ${alias ? `<span class="cast-char-alias">(${escapeHtml(alias)})</span>` : ""}
            </div>
            ${tagline ? `<div class="cast-card-tagline">${escapeHtml(tagline)}</div>` : ""}
            <div class="cast-card-badges">
              <span class="cast-pill ${isOfficial ? "cast-pill-official" : "cast-pill-private"}">
                ${isOfficial ? "🌐 Official" : "🔒 Private"}
              </span>
              <span class="cast-pill cast-pill-age">${age} y/o${ageLocked ? " 🔒" : ""}</span>
              <span class="cast-pill ${isLocked ? "cast-pill-locked" : "cast-pill-draft"}">
                ${isLocked ? `v${version} Locked` : `Draft v${version}`}
              </span>
              ${boundCount > 0 ? `<span class="cast-pill cast-pill-song">🎵 ${boundCount} song${boundCount > 1 ? "s" : ""}</span>` : ""}
            </div>
          </div>
        </div>
      `;
    }).join("");

    container.querySelectorAll(".cast-card").forEach(el => {
      el.addEventListener("click", () => {
        const id = el.dataset.charId;
        selectCharacter(id);
      });
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          selectCharacter(el.dataset.charId);
        }
      });
    });
  }

  // Render character inspector & workflow steps
  function renderDetail() {
    const container = document.getElementById("cast-detail-column");
    if (!container) return;

    const char = state.characters.find(c => c.id === state.selectedId);
    if (!char) {
      container.innerHTML = `
        <div class="cast-empty-detail">
          <h3>No Character Selected</h3>
          <p>Select a character from the roster or create a new virtual artist to inspect and manage their reference portrait, baseline lock, and song bindings.</p>
          <button type="button" id="cast-btn-hero-create" class="btn btn-sm btn-primary" style="margin-top:14px;">+ Create Character</button>
        </div>
      `;
      document.getElementById("cast-btn-hero-create")?.addEventListener("click", () => {
        openCreateModal();
      });
      return;
    }

    const name = char.identity?.name || "Unnamed";
    const alias = char.identity?.alias || "";
    const age = char.identity?.age || 16;
    const gender = char.identity?.gender || "neutral";
    const tagline = char.identity?.tagline || "";
    const version = char.versioning?.version || 1;
    const isLocked = Boolean(char.versioning?.is_locked);
    const confirmedAt = char.versioning?.confirmed_at;
    const promptAnchor = char.prompt_engine?.positive_character_anchor || "";
    const primaryImg = char.assets?.primary_image_url || "";
    const boundSongs = char.bound_songs || [];
    const isOfficial = Boolean(char.is_official || char.user_id === "system" || char.id === "char_zero_soe_0618");

    const availableSongs = getAvailableSongs();
    const activeSong = getActiveSong();

    container.innerHTML = `
      <!-- Hero Identity Card -->
      <div class="cast-hero-identity-card">
        ${isOfficial ? `
          <div class="cast-official-banner">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/></svg>
            <span><strong>Official Benchmark Artist</strong> · Canonical baseline is permanently locked. Ready to bind and star in your music videos!</span>
          </div>
        ` : ""}
        <div class="cast-identity-header-row">
          <div class="cast-identity-main-info">
            <div class="cast-char-title">
              <span>${escapeHtml(name)}</span>
              ${alias ? `<span class="cast-char-alias">「${escapeHtml(alias)}」</span>` : ""}
            </div>
            ${tagline ? `<p class="cast-step-desc">${escapeHtml(tagline)}</p>` : ""}
            <div class="cast-identity-meta-row">
              <span class="cast-pill ${isOfficial ? "cast-pill-official" : "cast-pill-private"}">
                ${isOfficial ? "🌐 Official System Artist" : "🔒 Private Artist"}
              </span>
              <span class="cast-pill cast-pill-age">Age: ${age} (Locked Invariant 🔒)</span>
              <span class="cast-pill" style="background:rgba(255,255,255,0.08);color:var(--text);">${escapeHtml(gender)}</span>
              <span class="cast-pill ${isLocked ? "cast-pill-locked" : "cast-pill-draft"}">
                ${isLocked ? `✅ Baseline v${version} Locked` : `Draft v${version}`}
              </span>
            </div>
          </div>
          <div style="display:flex;gap:8px;align-items:center;">
            ${isOfficial ? `
              <span class="cast-pill cast-pill-official" style="font-size:0.75rem;padding:4px 10px;">Official Read-Only</span>
            ` : `
              <button type="button" id="cast-btn-toggle-visibility" class="btn btn-sm btn-outline" title="Change character visibility">
                ${char.visibility === "public" ? "🔒 Make Private" : "🌐 Make Public"}
              </button>
              <button type="button" id="cast-btn-delete-char" class="btn btn-sm btn-outline" style="color:#ef4444;border-color:rgba(239,68,68,0.4);" title="Delete character">
                Delete Artist
              </button>
            `}
          </div>
        </div>

        ${promptAnchor ? `
          <div>
            <div class="cast-anchor-label">Visual DNA &amp; Invariant Prompt Anchor</div>
            <div class="cast-prompt-anchor-box">${escapeHtml(promptAnchor)}</div>
          </div>
        ` : ""}
      </div>

      <!-- 3 Primary Actions Flow -->
      <div class="cast-workflow-steps">
        <!-- Step 1: Upload Reference Portrait -->
        <div class="cast-step-card">
          <div class="cast-step-header">
            <div class="cast-step-title-group">
              <span class="cast-step-num">1</span>
              <div>
                <h3 class="cast-step-title">Reference Portrait (上传参考图)</h3>
                <p class="cast-step-desc">Establish canonical visual identity, facial invariants, and hairstyle.</p>
              </div>
            </div>
            ${isOfficial ? `<span class="cast-pill cast-pill-official">Official Portrait Frozen</span>` : primaryImg ? `<span class="cast-pill cast-pill-locked">Portrait Ready</span>` : `<span class="cast-pill cast-pill-draft">Required</span>`}
          </div>

          <div class="cast-portrait-zone">
            <div class="cast-portrait-preview-wrap">
              ${primaryImg ? `
                <img src="${primaryImg}" alt="${name} Portrait" class="cast-portrait-preview-img">
              ` : `
                <div class="cast-portrait-placeholder">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                  <span>No reference portrait uploaded</span>
                </div>
              `}
            </div>

            <div class="cast-portrait-actions">
              ${isOfficial ? `
                <span class="cast-form-hint" style="color:#7dd3fc;">Official artist portrait is maintained by the platform. You can bind her directly to any song.</span>
              ` : `
                <label for="cast-file-input" class="btn btn-sm btn-primary" style="display:inline-flex;align-items:center;gap:6px;cursor:pointer;width:fit-content;">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                  <span>${primaryImg ? "Replace Reference Portrait" : "Upload Reference Portrait"}</span>
                </label>
                <input type="file" id="cast-file-input" accept="image/png,image/jpeg,image/webp" style="display:none">
                <span class="cast-form-hint">Supports PNG, JPG, WEBP up to 20MB. Used as the anchor reference for storyboard &amp; video generation.</span>
              `}
            </div>
          </div>
        </div>

        <!-- Step 2: Version Baseline Confirmation -->
        <div class="cast-step-card">
          <div class="cast-step-header">
            <div class="cast-step-title-group">
              <span class="cast-step-num">2</span>
              <div>
                <h3 class="cast-step-title">Baseline Version Lock (确认版本)</h3>
                <p class="cast-step-desc">Lock this version to freeze face invariants and prevent visual drift across shots.</p>
              </div>
            </div>
          </div>

          <div class="cast-version-status-row">
            <div class="cast-version-indicator">
              <span class="cast-version-num">Version v${version}</span>
              <span class="cast-pill ${isLocked ? "cast-pill-locked" : "cast-pill-draft"}">
                ${isLocked ? "🔒 Locked Baseline" : "Draft (Editable)"}
              </span>
              ${confirmedAt ? `<span class="cast-form-hint">Confirmed at ${new Date(confirmedAt).toLocaleDateString()}</span>` : ""}
            </div>

            <div>
              ${isOfficial ? `
                <span class="cast-pill cast-pill-official">Platform Baseline Verified</span>
              ` : `
                <button type="button" id="cast-btn-confirm-version" class="btn btn-sm ${isLocked ? "btn-outline" : "btn-primary"}">
                  ${isLocked ? "🔒 Re-confirm New Version (v" + (version + 1) + ")" : "🔒 Confirm Baseline (Lock v" + version + ")"}
                </button>
              `}
            </div>
          </div>
          <span class="cast-form-hint">Confirming locks the profile schema and tells the AI director engine that this character's facial features and keyframe are canonical.</span>
        </div>

        <!-- Step 3: Song Project Binding -->
        <div class="cast-step-card">
          <div class="cast-step-header">
            <div class="cast-step-title-group">
              <span class="cast-step-num">3</span>
              <div>
                <h3 class="cast-step-title">Song Project Binding (绑定歌曲)</h3>
                <p class="cast-step-desc">Bind this virtual singer to songs in your library to inject character DNA into Storyboard &amp; Motion Studio.</p>
              </div>
            </div>
            <span class="cast-pill cast-pill-song">${boundSongs.length} Bound</span>
          </div>

          <div class="cast-binding-row">
            ${activeSong?.id ? `
              <button type="button" id="cast-btn-bind-active" class="btn btn-sm btn-primary">
                🎵 Bind to Active Song (${escapeHtml(activeSong.title || activeSong.id)})
              </button>
            ` : ""}

            <select id="cast-song-dropdown" class="cast-song-select">
              <option value="">Select a song to bind...</option>
              ${availableSongs.map(s => `
                <option value="${escapeHtml(s.id)}">${escapeHtml(s.title || s.id)}</option>
              `).join("")}
            </select>
            <button type="button" id="cast-btn-bind-dropdown" class="btn btn-sm btn-outline">
              Bind
            </button>
          </div>

          <div class="cast-bound-songs-wrap">
            <div class="cast-anchor-label">Currently Bound Projects</div>
            ${boundSongs.length > 0 ? `
              <div class="cast-bound-songs-list">
                ${boundSongs.map(sId => `
                  <div class="cast-bound-song-chip">
                    <span>🎵 ${escapeHtml(sId)}</span>
                    <button type="button" class="cast-unbind-btn" data-song-id="${escapeHtml(sId)}" title="Unbind song">×</button>
                  </div>
                `).join("")}
              </div>
            ` : `
              <p class="cast-step-desc" style="margin-top:6px;">No songs bound yet. Bind a song above to automatically assign ${escapeHtml(name)} as lead singer.</p>
            `}
          </div>
        </div>
      </div>
    `;

    // Attach Action Listeners
    // 1. File Upload
    const fileInput = document.getElementById("cast-file-input");
    fileInput?.addEventListener("change", async (e) => {
      const file = e.target.files?.[0];
      if (!file) return;
      await uploadReferencePortrait(char.id, file);
    });

    // 2. Confirm Version
    document.getElementById("cast-btn-confirm-version")?.addEventListener("click", async () => {
      await confirmCharacterVersion(char.id);
    });

    // 3. Bind Active Song
    document.getElementById("cast-btn-bind-active")?.addEventListener("click", async () => {
      if (activeSong?.id) {
        await bindSongToCharacter(char.id, activeSong.id);
      }
    });

    // 4. Bind Dropdown Song
    document.getElementById("cast-btn-bind-dropdown")?.addEventListener("click", async () => {
      const dropdown = document.getElementById("cast-song-dropdown");
      const songId = dropdown?.value;
      if (!songId) {
        alert("Please select a song from the dropdown.");
        return;
      }
      await bindSongToCharacter(char.id, songId);
    });

    // 5. Unbind Songs
    container.querySelectorAll(".cast-unbind-btn").forEach(btn => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const sId = btn.dataset.songId;
        if (sId) {
          await unbindSongFromCharacter(char.id, sId);
        }
      });
    });

    // 6. Delete Character
    document.getElementById("cast-btn-delete-char")?.addEventListener("click", async () => {
      if (confirm(`Are you sure you want to delete character "${name}"? This cannot be undone.`)) {
        await deleteCharacter(char.id);
      }
    });

    // 7. Toggle Visibility
    document.getElementById("cast-btn-toggle-visibility")?.addEventListener("click", async () => {
      const nextVis = char.visibility === "public" ? "private" : "public";
      await toggleVisibility(char.id, nextVis);
    });
  }

  // API Action: Load all characters
  async function loadCharacters() {
    state.isLoading = true;
    try {
      const res = await castApi("/api/characters");
      state.characters = res.characters || [];

      // Auto-select first character or maintain selection
      if (!state.selectedId && state.characters.length > 0) {
        state.selectedId = state.characters[0].id;
      } else if (state.selectedId && !state.characters.some(c => c.id === state.selectedId)) {
        state.selectedId = state.characters[0]?.id || null;
      }

      renderRoster();
      renderDetail();
    } catch (err) {
      console.error("[Cast Studio] Failed to load characters:", err);
    } finally {
      state.isLoading = false;
    }
  }

  // API Action: Select character
  async function selectCharacter(charId) {
    state.selectedId = charId;
    renderRoster();
    try {
      const fullProfile = await castApi(`/api/characters/${charId}`);
      const idx = state.characters.findIndex(c => c.id === charId);
      if (idx !== -1) {
        state.characters[idx] = fullProfile;
      }
      renderDetail();
    } catch (err) {
      console.error("[Cast Studio] Failed to fetch character details:", err);
      renderDetail();
    }
  }

  // API Action: Create character
  async function createCharacter(payload) {
    try {
      const newChar = await castApi("/api/characters", {
        method: "POST",
        json: payload,
      });
      state.characters.unshift(newChar);
      state.selectedId = newChar.id;
      closeCreateModal();
      renderRoster();
      renderDetail();
    } catch (err) {
      alert("Failed to create character: " + err.message);
    }
  }

  // API Action: Upload reference portrait
  async function uploadReferencePortrait(charId, file) {
    const base = getApiBase();
    const token = getAuthToken();
    const formData = new FormData();
    formData.append("file", file);

    const headers = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;

    try {
      const res = await fetch(`${base}/api/characters/${charId}/upload-reference`, {
        method: "POST",
        headers,
        body: formData,
      });
      if (!res.ok) {
        throw new Error(await res.text());
      }
      const data = await res.json();
      if (data.character) {
        const idx = state.characters.findIndex(c => c.id === charId);
        if (idx !== -1) state.characters[idx] = data.character;
        renderRoster();
        renderDetail();
      }
    } catch (err) {
      alert("Failed to upload reference image: " + err.message);
    }
  }

  // API Action: Confirm baseline version
  async function confirmCharacterVersion(charId) {
    try {
      const res = await castApi(`/api/characters/${charId}/confirm-version`, {
        method: "POST",
      });
      if (res.character) {
        const idx = state.characters.findIndex(c => c.id === charId);
        if (idx !== -1) state.characters[idx] = res.character;
        renderRoster();
        renderDetail();
      }
    } catch (err) {
      alert("Failed to confirm version: " + err.message);
    }
  }

  // API Action: Bind song
  async function bindSongToCharacter(charId, songId) {
    try {
      const res = await castApi(`/api/characters/${charId}/bind-song`, {
        method: "POST",
        json: { song_id: songId },
      });
      if (res.character) {
        const idx = state.characters.findIndex(c => c.id === charId);
        if (idx !== -1) state.characters[idx] = res.character;
        renderRoster();
        renderDetail();
      }
    } catch (err) {
      alert("Failed to bind song: " + err.message);
    }
  }

  // API Action: Unbind song
  async function unbindSongFromCharacter(charId, songId) {
    try {
      const res = await castApi(`/api/characters/${charId}/unbind-song`, {
        method: "POST",
        json: { song_id: songId },
      });
      if (res.character) {
        const idx = state.characters.findIndex(c => c.id === charId);
        if (idx !== -1) state.characters[idx] = res.character;
        renderRoster();
        renderDetail();
      }
    } catch (err) {
      alert("Failed to unbind song: " + err.message);
    }
  }

  // API Action: Toggle Visibility
  async function toggleVisibility(charId, visibility) {
    try {
      const res = await castApi(`/api/characters/${charId}/visibility`, {
        method: "POST",
        json: { visibility },
      });
      if (res.character) {
        const idx = state.characters.findIndex(c => c.id === charId);
        if (idx !== -1) state.characters[idx] = res.character;
        renderRoster();
        renderDetail();
      }
    } catch (err) {
      alert("Failed to update visibility: " + err.message);
    }
  }

  // API Action: Delete character
  async function deleteCharacter(charId) {
    try {
      await castApi(`/api/characters/${charId}`, {
        method: "DELETE",
      });
      state.characters = state.characters.filter(c => c.id !== charId);
      state.selectedId = state.characters[0]?.id || null;
      renderRoster();
      renderDetail();
    } catch (err) {
      alert("Failed to delete character: " + err.message);
    }
  }

  // Modal helpers
  function openCreateModal() {
    const modal = document.getElementById("cast-create-modal");
    if (!modal) return;
    modal.hidden = false;

    // Reset fields to clean state
    const nameInput = document.getElementById("cast-input-name");
    const aliasInput = document.getElementById("cast-input-alias");
    const ageInput = document.getElementById("cast-input-age");
    const genderInput = document.getElementById("cast-input-gender");
    const taglineInput = document.getElementById("cast-input-tagline");
    const visInput = document.getElementById("cast-input-visibility");

    if (nameInput) nameInput.value = "";
    if (aliasInput) aliasInput.value = "";
    if (ageInput) ageInput.value = "16";
    if (genderInput) genderInput.value = "female";
    if (taglineInput) taglineInput.value = "";
    if (visInput) visInput.value = "private";

    nameInput?.focus();
  }

  function closeCreateModal() {
    const modal = document.getElementById("cast-create-modal");
    if (modal) modal.hidden = true;
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Initialize event listeners
  function init() {
    // Header "+ New Character" button
    document.getElementById("cast-btn-create-header")?.addEventListener("click", () => {
      openCreateModal();
    });

    // Search input
    document.getElementById("cast-search-input")?.addEventListener("input", (e) => {
      state.searchQuery = e.target.value.trim();
      renderRoster();
    });

    // Create Modal Cancel / Close
    document.getElementById("cast-modal-cancel")?.addEventListener("click", closeCreateModal);
    document.getElementById("cast-modal-close")?.addEventListener("click", closeCreateModal);
    document.getElementById("cast-create-modal")?.addEventListener("click", (e) => {
      if (e.target.id === "cast-create-modal") closeCreateModal();
    });

    // Create Form Submit
    document.getElementById("cast-form-create")?.addEventListener("submit", (e) => {
      e.preventDefault();
      const name = document.getElementById("cast-input-name")?.value.trim();
      const alias = document.getElementById("cast-input-alias")?.value.trim() || "";
      const age = parseInt(document.getElementById("cast-input-age")?.value || "16", 10);
      const gender = document.getElementById("cast-input-gender")?.value || "neutral";
      const tagline = document.getElementById("cast-input-tagline")?.value.trim() || "";
      const visibility = document.getElementById("cast-input-visibility")?.value || "private";

      if (!name) {
        alert("Character name is required");
        return;
      }

      createCharacter({
        name,
        alias,
        age: isNaN(age) ? 16 : age,
        gender,
        tagline,
        visibility,
      });
    });
  }

  // Export module to window
  window.m2vCastStudio = {
    init,
    load: loadCharacters,
    select: selectCharacter,
    state,
  };

  document.addEventListener("DOMContentLoaded", () => {
    init();
  });
})();
