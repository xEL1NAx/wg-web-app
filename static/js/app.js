(() => {
  const state = {
    csrfToken: "",
    activeContent: "",
    selectedPreset: null,
    presets: [],
    backups: [],
    restartInFlight: false,
  };

  const elements = {};

  const byId = (id) => document.getElementById(id);

  function initElements() {
    elements.loadActiveBtn = byId("load-active-btn");
    elements.presetSearch = byId("preset-search");
    elements.refreshPresetsBtn = byId("refresh-presets-btn");
    elements.presetList = byId("preset-list");
    elements.pasteInput = byId("paste-input");
    elements.uploadConfigInput = byId("upload-config-input");
    elements.useUploadBtn = byId("use-upload-btn");
    elements.usePasteBtn = byId("use-paste-btn");

    elements.sourceBadge = byId("source-badge");
    elements.parseTestBtn = byId("parse-test-btn");
    elements.previewBtn = byId("preview-btn");
    elements.saveBtn = byId("save-btn");
    elements.restartBtn = byId("restart-btn");
    elements.editorInput = byId("editor-input");
    elements.editorStats = byId("editor-stats");

    elements.resultOutput = byId("result-output");
    elements.validationBox = byId("validation-box");
    elements.copyBtn = byId("copy-btn");
    elements.downloadBtn = byId("download-btn");

    elements.diffBody = byId("diff-body");
    elements.clearDiffBtn = byId("clear-diff-btn");

    elements.activeMeta = byId("active-file-meta");
    elements.backupList = byId("backup-list");
    elements.refreshBackupsBtn = byId("refresh-backups-btn");

    elements.toastRegion = byId("toast-region");

    elements.sourceTabs = document.querySelectorAll("[data-source-tab]");
    elements.sourceViews = document.querySelectorAll("[data-source-view]");
  }

  function attachEvents() {
    elements.loadActiveBtn.addEventListener("click", () => {
      setEditorContent(state.activeContent, "active file");
      showToast("Loaded active config into editor.", "success");
    });

    elements.refreshPresetsBtn.addEventListener("click", loadPresets);
    elements.refreshBackupsBtn.addEventListener("click", loadBackups);

    elements.presetSearch.addEventListener("input", renderPresetList);
    elements.usePasteBtn.addEventListener("click", () => {
      const pasted = elements.pasteInput.value;
      if (!pasted.trim()) {
        showToast("Paste a config first.", "warn");
        return;
      }
      setEditorContent(pasted, "one-time paste");
      showToast("One-time pasted config loaded in memory.", "success");
    });
    elements.useUploadBtn.addEventListener("click", onUseUploadedConfig);

    elements.parseTestBtn.addEventListener("click", onParseTest);
    elements.previewBtn.addEventListener("click", onPreview);
    elements.saveBtn.addEventListener("click", onSave);
    elements.restartBtn.addEventListener("click", onRestart);

    elements.copyBtn.addEventListener("click", onCopy);
    elements.downloadBtn.addEventListener("click", onDownload);

    elements.clearDiffBtn.addEventListener("click", () => {
      renderDiff([]);
      elements.resultOutput.value = "";
      elements.validationBox.innerHTML = "";
      showToast("Preview output cleared.", "success");
    });

    elements.editorInput.addEventListener("input", updateEditorStats);

    document.addEventListener("keydown", (event) => {
      const isCmdOrCtrl = event.metaKey || event.ctrlKey;
      if (!isCmdOrCtrl) {
        return;
      }

      if (event.key.toLowerCase() === "s") {
        event.preventDefault();
        onSave();
      }

      if (event.key === "Enter") {
        event.preventDefault();
        onPreview();
      }
    });

    elements.sourceTabs.forEach((tab) => {
      tab.addEventListener("click", () => {
        const target = tab.dataset.sourceTab;
        switchSourceTab(target);
      });
    });
  }

  function switchSourceTab(tabName) {
    elements.sourceTabs.forEach((tab) => {
      tab.classList.toggle("active", tab.dataset.sourceTab === tabName);
    });

    elements.sourceViews.forEach((view) => {
      view.classList.toggle("active", view.dataset.sourceView === tabName);
    });
  }

  async function apiRequest(url, { method = "GET", body = null, raw = false } = {}) {
    const options = { method, headers: {} };

    if (body !== null) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }

    if (method !== "GET") {
      options.headers["X-CSRF-Token"] = state.csrfToken;
    }

    const response = await fetch(url, options);

    if (raw) {
      if (!response.ok) {
        let message = `Request failed (${response.status}).`;
        try {
          const payload = await response.json();
          message = payload.error || message;
        } catch (_err) {
          // Ignore JSON parse failure for non-JSON responses.
        }
        throw new Error(message);
      }
      return response;
    }

    let payload = null;
    try {
      payload = await response.json();
    } catch (_err) {
      throw new Error("Server returned invalid JSON.");
    }

    if (!response.ok || payload.ok === false) {
      const error = new Error(payload.error || `Request failed (${response.status}).`);
      error.payload = payload;
      error.status = response.status;
      throw error;
    }

    return payload;
  }

  function setBusy(button, busy, { disable = true } = {}) {
    if (disable) {
      button.disabled = busy;
    }
    button.dataset.busy = busy ? "1" : "0";
  }

  function formatBytes(size) {
    if (!Number.isFinite(size) || size < 1024) {
      return `${size || 0} B`;
    }
    const units = ["KB", "MB", "GB"];
    let val = size / 1024;
    let idx = 0;
    while (val >= 1024 && idx < units.length - 1) {
      val /= 1024;
      idx += 1;
    }
    return `${val.toFixed(1)} ${units[idx]}`;
  }

  function formatDate(isoValue) {
    if (!isoValue) {
      return "n/a";
    }
    const date = new Date(isoValue);
    if (Number.isNaN(date.valueOf())) {
      return "n/a";
    }
    return date.toLocaleString();
  }

  function showToast(message, tone = "success") {
    const toast = document.createElement("div");
    toast.className = `toast ${tone}`;
    toast.textContent = message;
    elements.toastRegion.appendChild(toast);
    window.setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transform = "translateY(6px)";
      window.setTimeout(() => toast.remove(), 220);
    }, 3200);
  }

  function updateEditorStats() {
    const value = elements.editorInput.value;
    const lineCount = value === "" ? 0 : value.split(/\r\n|\r|\n/).length;
    elements.editorStats.textContent = `${lineCount} lines`;
  }

  function setEditorContent(content, sourceLabel) {
    elements.editorInput.value = content;
    elements.sourceBadge.textContent = `Source: ${sourceLabel}`;
    updateEditorStats();
  }

  function currentPolicyMode() {
    return "enable";
  }

  function renderValidation(validation) {
    if (!validation) {
      elements.validationBox.innerHTML = "<p class='muted'>No validation output yet.</p>";
      return;
    }

    const errors = validation.errors || [];
    const warnings = validation.warnings || [];
    const status = validation.valid
      ? "<p class='ok'>Validation passed.</p>"
      : "<p class='error'>Validation failed. File will not be written.</p>";

    const errorList = errors.length
      ? `<ul>${errors.map((item) => `<li class='error'>${escapeHtml(item)}</li>`).join("")}</ul>`
      : "";

    const warningList = warnings.length
      ? `<ul>${warnings.map((item) => `<li class='warn'>${escapeHtml(item)}</li>`).join("")}</ul>`
      : "";

    elements.validationBox.innerHTML = `${status}${errorList}${warningList}`;
  }

  function escapeHtml(input) {
    return input
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function encodePath(path) {
    return path
      .split("/")
      .map((segment) => encodeURIComponent(segment))
      .join("/");
  }

  function renderDiff(rows) {
    if (!rows || rows.length === 0) {
      elements.diffBody.innerHTML = "<tr><td colspan='4' class='muted'>No diff to display.</td></tr>";
      return;
    }

    elements.diffBody.innerHTML = rows
      .map((row) => {
        const leftNo = row.left_no ?? "";
        const rightNo = row.right_no ?? "";
        const left = escapeHtml(row.left || "");
        const right = escapeHtml(row.right || "");
        return `<tr class='${row.type}'>
          <td class='no'>${leftNo}</td>
          <td class='code'>${left}</td>
          <td class='no'>${rightNo}</td>
          <td class='code'>${right}</td>
        </tr>`;
      })
      .join("");
  }

  function renderPresetList() {
    const filter = elements.presetSearch.value.trim().toLowerCase();
    const presets = state.presets.filter((preset) => preset.name.toLowerCase().includes(filter));

    if (presets.length === 0) {
      elements.presetList.innerHTML = "<div class='card'>No matching preset config files.</div>";
      return;
    }

    elements.presetList.innerHTML = presets
      .map(
        (preset) => {
          const parts = preset.name.split("/");
          const fileName = parts.pop() || preset.name;
          const folderPath = parts.join("/");
          const folderMeta = folderPath ? `Folder: ${escapeHtml(folderPath)} • ` : "";

          return `
        <article class="card">
          <strong>${escapeHtml(fileName)}</strong>
          <div class="meta">${folderMeta}${formatBytes(preset.size)} • ${formatDate(preset.modified)}</div>
          <div class="actions">
            <button class="btn ghost" type="button" data-action="load-preset" data-name="${encodeURIComponent(
              preset.name
            )}">Load For Preview</button>
            <button class="btn secondary" type="button" data-action="apply-preset" data-name="${encodeURIComponent(
              preset.name
            )}">Apply To Active</button>
          </div>
        </article>
      `;
        }
      )
      .join("");

    elements.presetList.querySelectorAll("[data-action='load-preset']").forEach((button) => {
      button.addEventListener("click", async () => {
        const name = decodeURIComponent(button.dataset.name || "");
        await loadPresetDetail(name);
      });
    });

    elements.presetList.querySelectorAll("[data-action='apply-preset']").forEach((button) => {
      button.addEventListener("click", async () => {
        const name = decodeURIComponent(button.dataset.name || "");
        await applyPreset(name);
      });
    });
  }

  function renderBackupList() {
    if (state.backups.length === 0) {
      elements.backupList.innerHTML = "<div class='card'>No backups yet.</div>";
      return;
    }

    elements.backupList.innerHTML = state.backups
      .map(
        (backup) => `
        <article class="card">
          <strong>${escapeHtml(backup.name)}</strong>
          <div class="meta">${formatBytes(backup.size)} • ${formatDate(backup.modified)}</div>
          <div class="actions">
            <button class="btn ghost" type="button" data-action="restore-backup" data-name="${encodeURIComponent(
              backup.name
            )}">Restore</button>
          </div>
        </article>
      `
      )
      .join("");

    elements.backupList.querySelectorAll("[data-action='restore-backup']").forEach((button) => {
      button.addEventListener("click", async () => {
        const name = decodeURIComponent(button.dataset.name || "");
        await restoreBackup(name);
      });
    });
  }

  async function loadBootstrap() {
    const payload = await apiRequest("/api/bootstrap");
    state.csrfToken = payload.csrf_token;
  }

  async function loadActiveConfig() {
    const payload = await apiRequest("/api/active");
    const active = payload.active;

    state.activeContent = active.content || "";

    if (!elements.editorInput.value.trim()) {
      setEditorContent(state.activeContent, "active file");
    }

    const existsText = active.exists ? "exists" : "missing";
    elements.activeMeta.textContent = `${existsText} • ${formatBytes(active.size)} • ${formatDate(
      active.modified
    )}`;

    renderValidation(active.validation);
  }

  async function loadPresets() {
    const payload = await apiRequest("/api/presets");
    state.presets = payload.presets || [];
    renderPresetList();
  }

  async function loadPresetDetail(name) {
    const payload = await apiRequest(`/api/presets/${encodePath(name)}`);
    const preset = payload.preset;
    state.selectedPreset = preset.name;
    setEditorContent(preset.content || "", `preset: ${preset.name}`);
    renderValidation(preset.validation);
    showToast(`Loaded preset ${preset.name} into editor.`, "success");
  }

  async function applyPreset(name) {
    if (!window.confirm(`Apply preset ${name} to active config now?`)) {
      return;
    }

    try {
      const payload = await apiRequest("/api/apply-preset", {
        method: "POST",
        body: {
          preset_name: name,
          policy_mode: currentPolicyMode(),
        },
      });

      if (payload.restart && payload.restart.attempted && !payload.restart.success) {
        showToast("Preset applied, but wg0 restart failed.", "error");
      } else {
        showToast(payload.message || "Preset applied.", "success");
      }
      await Promise.all([loadActiveConfig(), loadBackups(), loadPresets()]);
      renderValidation(payload.validation);
    } catch (error) {
      handleApiError(error, "Could not apply preset.");
    }
  }

  async function loadBackups() {
    const payload = await apiRequest("/api/backups");
    state.backups = payload.backups || [];
    renderBackupList();
  }

  async function restoreBackup(name) {
    if (!window.confirm(`Restore backup ${name} to active config?`)) {
      return;
    }

    try {
      const payload = await apiRequest("/api/restore-backup", {
        method: "POST",
        body: { backup_name: name },
      });
      if (payload.restart && payload.restart.attempted && !payload.restart.success) {
        showToast("Backup restored, but wg0 restart failed.", "error");
      } else {
        showToast(payload.message || "Backup restored.", "success");
      }
      await Promise.all([loadActiveConfig(), loadBackups()]);
    } catch (error) {
      handleApiError(error, "Could not restore backup.");
    }
  }

  async function onUseUploadedConfig() {
    const files = elements.uploadConfigInput.files;
    if (!files || files.length === 0) {
      showToast("Select a config file first.", "warn");
      return;
    }

    const file = files[0];
    try {
      const content = await file.text();
      if (!content.trim()) {
        showToast("Uploaded file is empty.", "warn");
        return;
      }

      setEditorContent(content, `upload: ${file.name}`);
      showToast("Uploaded config extracted into editor memory.", "success");
    } catch (_error) {
      showToast("Could not read uploaded file.", "error");
    }
  }

  async function onParseTest() {
    setBusy(elements.parseTestBtn, true);
    try {
      const payload = await apiRequest("/api/parse-test", {
        method: "POST",
        body: { content: elements.editorInput.value },
      });
      renderValidation(payload.validation);
      showToast(payload.validation.valid ? "Parse test passed." : "Parse test found issues.", payload.validation.valid ? "success" : "warn");
    } catch (error) {
      handleApiError(error, "Parse test failed.");
    } finally {
      setBusy(elements.parseTestBtn, false);
    }
  }

  async function onPreview() {
    setBusy(elements.previewBtn, true);
    try {
      const payload = await apiRequest("/api/preview", {
        method: "POST",
        body: {
          content: elements.editorInput.value,
          policy_mode: currentPolicyMode(),
        },
      });

      const preview = payload.preview;
      elements.resultOutput.value = preview.transformed_content;
      renderValidation(preview.validation);
      renderDiff(preview.diff_rows);

      showToast(preview.changed_from_active ? "Dry run ready." : "No changes vs active config.", "success");
    } catch (error) {
      handleApiError(error, "Preview failed.");
    } finally {
      setBusy(elements.previewBtn, false);
    }
  }

  async function onSave() {
    if (!window.confirm("Write the transformed config to the active wg0.conf file?")) {
      return;
    }

    setBusy(elements.saveBtn, true);
    try {
      const payload = await apiRequest("/api/save", {
        method: "POST",
        body: {
          content: elements.editorInput.value,
          policy_mode: currentPolicyMode(),
        },
      });

      if (typeof payload.transformed_content === "string") {
        elements.editorInput.value = payload.transformed_content;
        elements.resultOutput.value = payload.transformed_content;
        updateEditorStats();
      }

      renderValidation(payload.validation);
      if (payload.restart && payload.restart.attempted && !payload.restart.success) {
        showToast("Config saved, but wg0 restart failed.", "error");
      } else {
        showToast(payload.message || "Config saved.", "success");
      }
      await Promise.all([loadActiveConfig(), loadBackups()]);
    } catch (error) {
      handleApiError(error, "Save failed.");
      if (error.payload && error.payload.validation) {
        renderValidation(error.payload.validation);
      }
      if (error.payload && typeof error.payload.transformed_content === "string") {
        elements.resultOutput.value = error.payload.transformed_content;
      }
    } finally {
      setBusy(elements.saveBtn, false);
    }
  }

  async function onRestart() {
    if (state.restartInFlight) {
      showToast("Restart already in progress.", "warn");
      return;
    }

    if (!window.confirm("Restart wg-quick@wg0 now? This can briefly interrupt traffic.")) {
      return;
    }

    state.restartInFlight = true;
    setBusy(elements.restartBtn, true, { disable: false });
    try {
      const payload = await apiRequest("/api/restart", { method: "POST", body: {} });
      showToast(payload.message || "Service restarted.", "success");
    } catch (error) {
      handleApiError(error, "Restart failed.");
    } finally {
      state.restartInFlight = false;
      setBusy(elements.restartBtn, false, { disable: false });
    }
  }

  async function onDownload() {
    const content = elements.resultOutput.value || elements.editorInput.value;
    if (!content.trim()) {
      showToast("No config content to download.", "warn");
      return;
    }

    try {
      const response = await apiRequest("/api/download", {
        method: "POST",
        body: {
          content,
          filename: "wg0-generated.conf",
        },
        raw: true,
      });

      const blob = await response.blob();
      const href = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = href;
      anchor.download = "wg0-generated.conf";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(href);
      showToast("Downloaded generated config.", "success");
    } catch (error) {
      handleApiError(error, "Download failed.");
    }
  }

  async function onCopy() {
    const content = elements.resultOutput.value || elements.editorInput.value;
    if (!content.trim()) {
      showToast("No text available to copy.", "warn");
      return;
    }

    try {
      await navigator.clipboard.writeText(content);
      showToast("Copied config to clipboard.", "success");
    } catch (_err) {
      showToast("Clipboard copy is not available in this browser context.", "warn");
    }
  }

  function handleApiError(error, fallbackMessage) {
    const message = error.message || fallbackMessage;
    showToast(message, "error");
  }

  async function boot() {
    initElements();
    attachEvents();

    try {
      await loadBootstrap();
      await Promise.all([loadActiveConfig(), loadPresets(), loadBackups()]);
      renderDiff([]);
      switchSourceTab("active");
      showToast("Dashboard ready.", "success");
    } catch (error) {
      handleApiError(error, "Initialization failed.");
    }
  }

  window.addEventListener("DOMContentLoaded", boot);
})();
