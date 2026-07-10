function chatApp({ userName = "User", maxImages = 10, maxUploadMb = 25 } = {}) {
  let nextId = 1;
  let pendingId = 1;
  const completedPipelines = new Set();

  return {
    userName,
    maxImages,
    maxUploadMb,
    messages: [],
    draft: "",
    sending: false,
    showSuggestions: true,
    pendingAttachments: [],

    init() {
      this.syncInputFromDom();
      this.syncSendDisabled();
      window.addEventListener(
        "ai-tribe:pipeline-complete",
        (event) => this.onPipelineComplete(event.detail || {})
      );
    },

    syncInputFromDom() {
      const input = document.getElementById("chat-input");
      if (input) this.draft = input.value;
    },

    syncSendDisabled() {
      const btn = document.getElementById("chat-send-btn");
      const input = document.getElementById("chat-input");
      if (!btn || !input) return;
      const hasText = !!input.value.trim();
      const hasFiles = this.pendingAttachments.length > 0;
      btn.disabled = this.sending || (!hasText && !hasFiles);
    },

    hideSuggestions() {
      this.showSuggestions = false;
      const el = document.getElementById("chat-suggestions");
      if (el) el.hidden = true;
    },

    formatText(text) {
      if (!text) return "";
      const escaped = String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
      return escaped
        .replace(
          /\[([^\]]+)\]\(claim:(\d+)\)/g,
          '<button type="button" class="chat-claim-link" data-claim-id="$2">$1</button>'
        )
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/\n/g, "<br>");
    },

    openClaimModal(claimId) {
      if (window.openChatClaimModal) window.openChatClaimModal(claimId);
    },

    scrollToBottom() {
      this.$nextTick(() => {
        const el = this.$refs.thread;
        if (el) el.scrollTop = el.scrollHeight;
      });
    },

    pushMessage(payload) {
      this.messages.push({
        id: nextId++,
        role: payload.role || "assistant",
        text: payload.text || "",
        widgets: payload.widgets || [],
        attachments: payload.attachments || [],
      });
      this.scrollToBottom();
    },

    stageFiles(fileList) {
      const files = Array.from(fileList || []);
      if (!files.length) return;

      let imageCount = this.pendingAttachments.filter((a) => !a.isVideo).length;
      let hasVideo = this.pendingAttachments.some((a) => a.isVideo);

      for (const file of files) {
        const isVideo = file.type.startsWith("video/");
        const isImage =
          file.type.startsWith("image/") ||
          /\.(jpe?g|png|webp|gif)$/i.test(file.name || "");
        if (!isVideo && !isImage) continue;
        if (isVideo && hasVideo) continue;
        if (!isVideo && imageCount >= this.maxImages) continue;

        const url = URL.createObjectURL(file);
        this.pendingAttachments.push({
          id: pendingId++,
          file,
          url,
          name: file.name || (isVideo ? "Video" : "Photo"),
          isVideo,
        });
        if (isVideo) hasVideo = true;
        else imageCount += 1;
      }

      this.hideSuggestions();
      this.syncSendDisabled();
      this.renderPendingDom();
    },

    removePendingAttachment(index) {
      const item = this.pendingAttachments[index];
      if (!item) return;
      if (item.url) URL.revokeObjectURL(item.url);
      this.pendingAttachments.splice(index, 1);
      this.syncSendDisabled();
      this.renderPendingDom();
    },

    clearPendingAttachments() {
      this.pendingAttachments.forEach((item) => {
        if (item.url) URL.revokeObjectURL(item.url);
      });
      this.pendingAttachments = [];
      this.renderPendingDom();
    },

    renderPendingDom() {
      // Keep a non-Alpine fallback strip in sync when Alpine is unavailable.
      const strip = document.getElementById("chat-pending-attachments");
      if (!strip || window.Alpine) return;
    },

    useSuggestion(hint) {
      const input = document.getElementById("chat-input");
      if (input) input.value = hint;
      this.draft = hint;
      this.sendMessage();
    },

    onFilesSelected(event) {
      const input = event.target;
      this.stageFiles(input.files);
      input.value = "";
    },

    async sendMessage() {
      const input = document.getElementById("chat-input");
      const text = ((input && input.value) || this.draft || "").trim();
      const staged = this.pendingAttachments.slice();
      if ((!text && !staged.length) || this.sending) return;

      this.hideSuggestions();
      const attachmentViews = staged.map((a) => ({
        url: a.url,
        name: a.name,
        isVideo: a.isVideo,
      }));
      this.pushMessage({
        role: "user",
        text,
        attachments: attachmentViews,
      });

      if (input) input.value = "";
      this.draft = "";
      this.pendingAttachments = [];
      this.sending = true;
      this.syncSendDisabled();

      try {
        if (staged.length) {
          const uploadReply = await postChatUpload(staged.map((a) => a.file));
          if (uploadReply.error) {
            this.pushMessage({
              role: "assistant",
              text: uploadReply.error,
            });
            return;
          }
          // If there is no accompanying text, show the server's draft guidance.
          if (!text) {
            this.pushMessage(uploadReply.data);
            return;
          }
        }

        if (text) {
          const response = await fetch("/api/chat/message", {
            method: "POST",
            credentials: "same-origin",
            headers: {
              Accept: "application/json",
              "Content-Type": "application/json",
            },
            body: JSON.stringify({ text }),
          });
          let data = {};
          try {
            data = await response.json();
          } catch (_parseErr) {
            data = {};
          }
          if (!response.ok) {
            this.pushMessage({
              role: "assistant",
              text: data.detail || "Something went wrong. Please try again.",
            });
            return;
          }
          this.pushMessage(data);
        }
      } catch (_err) {
        this.pushMessage({
          role: "assistant",
          text: "I couldn't reach the server. Check your connection and try again.",
        });
      } finally {
        this.sending = false;
        this.syncSendDisabled();
      }
    },

    async onPipelineComplete({ claimId }) {
      if (!claimId || completedPipelines.has(claimId)) return;
      completedPipelines.add(claimId);

      try {
        const response = await fetch(`/api/chat/claims/${claimId}/summary`, {
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
        if (!response.ok) return;
        const data = await response.json();
        this.pushMessage({
          role: "assistant",
          text: `${data.text}\n\nPlease submit another claim, or ask me about an existing one.`,
          widgets: data.widgets || [],
        });
      } catch (_err) {
        // Pipeline UI already shows halt state.
      }
    },
  };
}

async function postChatUpload(files) {
  const list = Array.from(files || []);
  const images = [];
  let video = null;
  for (const file of list) {
    if (file.type.startsWith("video/") && !video) video = file;
    else if (
      file.type.startsWith("image/") ||
      /\.(jpe?g|png|webp|gif)$/i.test(file.name || "")
    ) {
      images.push(file);
    }
  }
  if (!images.length && !video) {
    return { error: "Please choose image or video files." };
  }

  const form = new FormData();
  images.forEach((file) => form.append("images", file));
  if (video) form.append("video", video);

  try {
    const response = await fetch("/api/chat/upload", {
      method: "POST",
      credentials: "same-origin",
      body: form,
    });
    let data = {};
    try {
      data = await response.json();
    } catch (_parseErr) {
      data = {};
    }
    if (!response.ok) {
      return { error: data.detail || "Upload failed." };
    }
    return { data };
  } catch (_err) {
    return { error: "Upload failed — please try again." };
  }
}

function getChatAlpine() {
  const shell = document.getElementById("chat-shell");
  if (!shell || !window.Alpine) return null;
  try {
    return window.Alpine.$data(shell);
  } catch (_err) {
    return null;
  }
}

function openChatProfile() {
  window.dispatchEvent(new CustomEvent("ai-tribe:open-profile"));
}

function mountUserChromeInSidebar() {
  const chrome = document.querySelector(".app-chrome-left");
  const slot = document.getElementById("chat-user-menu-slot");
  if (!chrome || !slot || slot.contains(chrome)) return;
  chrome.classList.add("chat-sidebar-user-chrome");
  slot.appendChild(chrome);
}

function initChatChrome() {
  mountUserChromeInSidebar();
  initChatClaimModal();

  const sidebar = document.getElementById("chat-sidebar");
  const toggle = document.getElementById("chat-sidebar-toggle");
  const expanded = document.getElementById("chat-sidebar-expanded");
  const collapsedProfile = document.getElementById("chat-sidebar-collapsed-profile");

  if (toggle && sidebar) {
    toggle.addEventListener("click", () => {
      const isCollapsed = sidebar.classList.toggle("chat-sidebar--collapsed");
      toggle.setAttribute("aria-expanded", String(!isCollapsed));
      toggle.setAttribute(
        "aria-label",
        isCollapsed ? "Expand sidebar" : "Collapse sidebar"
      );
      if (expanded) expanded.hidden = isCollapsed;
      if (collapsedProfile) collapsedProfile.hidden = !isCollapsed;
    });
  }

  document.querySelectorAll("[data-chat-open-profile]").forEach((btn) => {
    btn.addEventListener("click", openChatProfile);
  });

  const form = document.getElementById("chat-composer-form");
  const input = document.getElementById("chat-input");
  const sendBtn = document.getElementById("chat-send-btn");

  if (input && sendBtn) {
    input.addEventListener("input", () => {
      const alpine = getChatAlpine();
      if (alpine) {
        alpine.draft = input.value;
        alpine.syncSendDisabled();
      } else {
        const pending = document.querySelectorAll("#chat-pending-attachments .chat-pending-item");
        sendBtn.disabled = !input.value.trim() && !pending.length;
      }
    });

    input.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || event.shiftKey) return;
      event.preventDefault();
      submitChatMessage();
    });
  }

  if (form) {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      submitChatMessage();
    });
  }

  const attachInput = document.getElementById("chat-attach-input");
  if (attachInput) {
    attachInput.addEventListener("change", () => {
      const alpine = getChatAlpine();
      if (alpine && typeof alpine.onFilesSelected === "function") {
        alpine.onFilesSelected({ target: attachInput });
        return;
      }
      // Vanilla fallback: stage into DOM strip
      stageFilesVanilla(attachInput.files);
      attachInput.value = "";
    });
  }

  document.querySelectorAll("[data-chat-hint]").forEach((chip) => {
    chip.addEventListener("click", () => {
      const hint = chip.getAttribute("data-chat-hint") || chip.textContent || "";
      const alpine = getChatAlpine();
      if (alpine) {
        alpine.useSuggestion(hint);
        return;
      }
      if (input) input.value = hint;
      submitChatMessage();
    });
  });
}

const vanillaPending = [];

function stageFilesVanilla(fileList) {
  const strip = document.getElementById("chat-pending-attachments");
  const sendBtn = document.getElementById("chat-send-btn");
  if (!strip) return;
  Array.from(fileList || []).forEach((file) => {
    const isVideo = file.type.startsWith("video/");
    const isImage =
      file.type.startsWith("image/") ||
      /\.(jpe?g|png|webp|gif)$/i.test(file.name || "");
    if (!isVideo && !isImage) return;
    const url = URL.createObjectURL(file);
    vanillaPending.push({ file, url, name: file.name, isVideo });
    const item = document.createElement("div");
    item.className = "chat-pending-item";
    item.innerHTML = isVideo
      ? `<span class="chat-msg-video">${file.name || "Video"}</span>`
      : `<img src="${url}" alt="" />`;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "chat-pending-remove";
    remove.innerHTML = "&times;";
    remove.addEventListener("click", () => {
      const idx = vanillaPending.findIndex((p) => p.url === url);
      if (idx >= 0) {
        URL.revokeObjectURL(vanillaPending[idx].url);
        vanillaPending.splice(idx, 1);
      }
      item.remove();
      strip.hidden = !vanillaPending.length;
      if (sendBtn) {
        const input = document.getElementById("chat-input");
        sendBtn.disabled = !(input && input.value.trim()) && !vanillaPending.length;
      }
    });
    item.appendChild(remove);
    strip.appendChild(item);
  });
  strip.hidden = !vanillaPending.length;
  strip.style.display = vanillaPending.length ? "flex" : "none";
  if (sendBtn) sendBtn.disabled = false;
  const suggestions = document.getElementById("chat-suggestions");
  if (suggestions) suggestions.hidden = true;
}

async function submitChatMessage() {
  const alpine = getChatAlpine();
  if (alpine && typeof alpine.sendMessage === "function") {
    alpine.syncInputFromDom();
    await alpine.sendMessage();
    return;
  }

  const input = document.getElementById("chat-input");
  const text = ((input && input.value) || "").trim();
  const staged = vanillaPending.splice(0, vanillaPending.length);
  if (!text && !staged.length) return;

  const suggestions = document.getElementById("chat-suggestions");
  if (suggestions) suggestions.hidden = true;
  if (input) input.value = "";

  const strip = document.getElementById("chat-pending-attachments");
  if (strip) {
    strip.innerHTML = "";
    strip.hidden = true;
    strip.style.display = "none";
  }

  const thread = document.getElementById("chat-thread");
  if (thread) {
    const userBubble = document.createElement("div");
    userBubble.className = "chat-message chat-message--user";
    let html = text
      ? `<div class="chat-bubble">${text.replace(/</g, "&lt;")}</div>`
      : "";
    if (staged.length) {
      html += `<div class="chat-msg-attachments">${staged
        .map((a) =>
          a.isVideo
            ? `<span class="chat-msg-thumb chat-msg-video">${a.name || "Video"}</span>`
            : `<button type="button" class="chat-msg-thumb"><img src="${a.url}" alt="" /></button>`
        )
        .join("")}</div>`;
    }
    userBubble.innerHTML = html;
    thread.appendChild(userBubble);
  }

  try {
    if (staged.length) {
      const uploadReply = await postChatUpload(staged.map((a) => a.file));
      if (uploadReply.error) {
        appendAssistantMessage(thread, { text: uploadReply.error });
        return;
      }
      if (!text) {
        appendAssistantMessage(thread, uploadReply.data);
        return;
      }
    }
    if (text) {
      const response = await fetch("/api/chat/message", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ text }),
      });
      const data = await response.json();
      appendAssistantMessage(thread, data);
    }
  } catch (_err) {
    appendAssistantMessage(thread, {
      text: "I couldn't reach the server. Check your connection and try again.",
    });
  }
}

function appendAssistantMessage(thread, data) {
  if (!thread) return;
  const botBubble = document.createElement("div");
  botBubble.className = "chat-message chat-message--assistant";
  const text = String(data.detail || data.text || "No response.")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(
      /\[([^\]]+)\]\(claim:(\d+)\)/g,
      '<button type="button" class="chat-claim-link" data-claim-id="$2">$1</button>'
    )
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
  let html = `<div class="chat-bubble">${text}</div>`;
  const widgets = data.widgets || [];
  for (const widget of widgets) {
    if (!widget || !widget.type) continue;
    if (widget.type === "file_upload") {
      html += `
      <div class="chat-widget">
        <label class="chat-upload-btn">
          <input type="file" class="sr-only" accept="image/jpeg,image/png,image/webp,image/gif,video/mp4,video/webm,video/quicktime" multiple data-chat-upload />
          <span>Upload photos or video</span>
        </label>
        <p class="chat-upload-hint">Attach damage photos or a short video</p>
      </div>`;
    } else if (widget.type === "claim_images" && Array.isArray(widget.images)) {
      const thumbs = widget.images
        .map(
          (image) => `
        <button type="button" class="chat-gallery-thumb" data-preview-src="${String(
          image.url || ""
        ).replace(/"/g, "&quot;")}" data-preview-alt="${String(
            image.alt || "Claim photo"
          ).replace(/"/g, "&quot;")}">
          <img src="${String(image.url || "").replace(/"/g, "&quot;")}" alt="${String(
            image.alt || "Claim photo"
          ).replace(/"/g, "&quot;")}" loading="lazy" />
        </button>`
        )
        .join("");
      html += `
      <div class="chat-widget chat-gallery-widget">
        <p class="chat-widget-title">Claim photos · ${String(
          widget.claim_reference || ""
        ).replace(/</g, "&lt;")}</p>
        <div class="chat-gallery-grid">${thumbs}</div>
      </div>`;
    } else if (widget.type === "claim_estimate") {
      const rows = (widget.line_items || [])
        .slice(0, 8)
        .map((row) => {
          const total = row.line_total
            ? `₹${Number(row.line_total).toLocaleString("en-IN")}`
            : "—";
          return `<tr>
            <td>${String(row.part_name || "—").replace(/</g, "&lt;")}</td>
            <td>${String(row.damage_type || "—").replace(/</g, "&lt;")}</td>
            <td>${String(row.repair_or_replace || "—").replace(/</g, "&lt;")}</td>
            <td class="text-right">${total}</td>
          </tr>`;
        })
        .join("");
      html += `
      <div class="chat-widget chat-estimate-widget">
        <p class="chat-widget-title">Estimate · ${String(
          widget.claim_reference || ""
        ).replace(/</g, "&lt;")}</p>
        <div class="chat-estimate-table-wrap">
          <table class="chat-estimate-table">
            <thead><tr><th>Part</th><th>Damage</th><th>Action</th><th class="text-right">Total</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>`;
    }
  }
  botBubble.innerHTML = html;
  thread.appendChild(botBubble);
  botBubble.querySelectorAll("[data-chat-upload]").forEach((fileInput) => {
    fileInput.addEventListener("change", () => {
      const alpine = getChatAlpine();
      if (alpine) {
        alpine.onFilesSelected({ target: fileInput });
        return;
      }
      stageFilesVanilla(fileInput.files);
      fileInput.value = "";
    });
  });
  botBubble.querySelectorAll("[data-preview-src]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (window.openMediaPreview) {
        window.openMediaPreview({
          src: btn.getAttribute("data-preview-src"),
          alt: btn.getAttribute("data-preview-alt") || "Claim photo",
        });
      }
    });
  });
  thread.scrollTop = thread.scrollHeight;
}

function initChatClaimModal() {
  const modal = document.getElementById("chat-claim-modal");
  const frame = document.getElementById("chat-claim-modal-frame");
  if (!modal || !frame) return;
  const titleEl = document.getElementById("chat-claim-modal-title");
  const closeEls = modal.querySelectorAll("[data-chat-claim-close]");

  function closeModal() {
    modal.hidden = true;
    frame.removeAttribute("src");
    document.body.classList.remove("chat-claim-modal-open");
  }

  function openModal(claimId) {
    const id = Number(claimId);
    if (!id) return;
    if (titleEl) titleEl.textContent = `Claim #${id}`;
    frame.src = `/claims/${id}/estimate?embed=1`;
    modal.hidden = false;
    document.body.classList.add("chat-claim-modal-open");
    const panel = modal.querySelector(".chat-claim-modal-panel");
    if (panel) panel.focus();
  }

  window.openChatClaimModal = openModal;

  closeEls.forEach((el) => el.addEventListener("click", closeModal));
  document.addEventListener("keydown", (event) => {
    if (modal.hidden) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeModal();
    }
  });

  document.addEventListener("click", (event) => {
    const link = event.target.closest(".chat-claim-link");
    if (!link) return;
    event.preventDefault();
    openModal(link.getAttribute("data-claim-id"));
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initChatChrome);
} else {
  initChatChrome();
}

mountUserChromeInSidebar();
