function chatApp({ userName = "User", maxImages = 10, maxUploadMb = 25 } = {}) {
  let nextId = 1;
  const completedPipelines = new Set();

  return {
    userName,
    maxImages,
    maxUploadMb,
    messages: [],
    draft: "",
    sending: false,
    showSuggestions: true,

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
      btn.disabled = this.sending || !input.value.trim();
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
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/\n/g, "<br>");
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
      });
      this.scrollToBottom();
    },

    useSuggestion(hint) {
      const input = document.getElementById("chat-input");
      if (input) input.value = hint;
      this.draft = hint;
      this.sendMessage();
    },

    async sendMessage() {
      const input = document.getElementById("chat-input");
      const text = ((input && input.value) || this.draft || "").trim();
      if (!text || this.sending) return;

      this.hideSuggestions();
      this.pushMessage({ role: "user", text });
      if (input) input.value = "";
      this.draft = "";
      this.sending = true;
      this.syncSendDisabled();

      try {
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

    async onFilesSelected(event) {
      const input = event.target;
      await uploadChatFiles(Array.from(input.files || []), {
        onStart: () => {
          this.sending = true;
          this.syncSendDisabled();
        },
        onDone: () => {
          this.sending = false;
          this.syncSendDisabled();
          input.value = "";
        },
        onReply: (data) => {
          this.hideSuggestions();
          this.pushMessage(data);
        },
        onError: (text) => {
          this.pushMessage({ role: "assistant", text });
        },
      });
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

async function uploadChatFiles(files, { onStart, onDone, onReply, onError } = {}) {
  const list = Array.from(files || []);
  if (!list.length) return;

  const images = [];
  let video = null;
  for (const file of list) {
    if (file.type.startsWith("video/") && !video) {
      video = file;
    } else if (file.type.startsWith("image/") || /\.(jpe?g|png|webp|gif)$/i.test(file.name || "")) {
      images.push(file);
    }
  }

  if (!images.length && !video) {
    if (onError) onError("Please choose image or video files.");
    return;
  }

  const form = new FormData();
  images.forEach((file) => form.append("images", file));
  if (video) form.append("video", video);

  if (onStart) onStart();
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
      if (onError) onError(data.detail || "Upload failed.");
      return;
    }
    if (onReply) onReply(data);
  } catch (_err) {
    if (onError) onError("Upload failed — please try again.");
  } finally {
    if (onDone) onDone();
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
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
  let html = `<div class="chat-bubble">${text}</div>`;
  const widgets = data.widgets || [];
  if (widgets.some((w) => w && w.type === "file_upload")) {
    html += `
      <div class="chat-widget">
        <label class="chat-upload-btn">
          <input type="file" class="sr-only" accept="image/jpeg,image/png,image/webp,image/gif,video/mp4,video/webm,video/quicktime" multiple data-chat-upload />
          <span>Upload photos or video</span>
        </label>
        <p class="chat-upload-hint">Attach damage photos or a short video</p>
      </div>`;
  }
  botBubble.innerHTML = html;
  thread.appendChild(botBubble);
  botBubble.querySelectorAll("[data-chat-upload]").forEach((input) => {
    input.addEventListener("change", () => {
      uploadChatFiles(input.files, {
        onReply: (payload) => appendAssistantMessage(thread, payload),
        onError: (msg) => appendAssistantMessage(thread, { text: msg }),
        onDone: () => {
          input.value = "";
        },
      });
    });
  });
  thread.scrollTop = thread.scrollHeight;
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
        sendBtn.disabled = !input.value.trim();
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
      const files = Array.from(attachInput.files || []);
      if (alpine && typeof alpine.onFilesSelected === "function") {
        alpine.onFilesSelected({ target: attachInput });
        return;
      }
      uploadChatFiles(files, {
        onReply: (data) => {
          const suggestions = document.getElementById("chat-suggestions");
          if (suggestions) suggestions.hidden = true;
          appendAssistantMessage(document.getElementById("chat-thread"), data);
        },
        onError: (msg) => {
          appendAssistantMessage(document.getElementById("chat-thread"), { text: msg });
        },
        onDone: () => {
          attachInput.value = "";
        },
      });
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

async function submitChatMessage() {
  const alpine = getChatAlpine();
  if (alpine && typeof alpine.sendMessage === "function") {
    alpine.syncInputFromDom();
    await alpine.sendMessage();
    return;
  }

  const input = document.getElementById("chat-input");
  const text = (input && input.value || "").trim();
  if (!text) return;

  const suggestions = document.getElementById("chat-suggestions");
  if (suggestions) suggestions.hidden = true;
  if (input) input.value = "";

  const thread = document.getElementById("chat-thread");
  if (thread) {
    const userBubble = document.createElement("div");
    userBubble.className = "chat-message chat-message--user";
    userBubble.innerHTML = `<div class="chat-bubble">${text.replace(/</g, "&lt;")}</div>`;
    thread.appendChild(userBubble);
  }

  try {
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
  } catch (_err) {
    appendAssistantMessage(thread, {
      text: "I couldn't reach the server. Check your connection and try again.",
    });
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initChatChrome);
} else {
  initChatChrome();
}

// Move profile chip into sidebar before Alpine scans the DOM.
mountUserChromeInSidebar();
