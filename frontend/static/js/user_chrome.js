function userChrome() {
  return {
    initialName: "",
    profile: {
      full_name: "",
      date_of_birth: "",
      has_photo: false,
      photo_url: null,
      username: "",
      role: "",
    },
    menuOpen: false,
    profileOpen: false,
    settingsOpen: false,
    adminOpen: false,
    isAdmin: false,
    photoMessage: "",
    nameMessage: "",
    dobMessage: "",
    passwordMessage: "",
    passwordCurrent: "",
    passwordNew: "",
    llmSettings: null,
    selectedProvider: "",
    apiKeyDraft: "",
    llmMessage: "",
    llmSaving: false,
    llmTesting: false,
    llmTestMessage: "",
    llmTestOk: false,
    adminUsers: [],
    newUserEmail: "",
    adminMessage: "",
    adminSubmitting: false,

    get initials() {
      const name = this.profile.full_name || this.initialName || "?";
      return name
        .split(/\s+/)
        .filter(Boolean)
        .slice(0, 2)
        .map((p) => p[0]?.toUpperCase() || "")
        .join("") || "?";
    },

    get savedKeyHint() {
      if (!this.llmSettings || !this.selectedProvider) return null;
      if (
        this.llmSettings.active_provider === this.selectedProvider &&
        this.llmSettings.key_hint
      ) {
        return this.llmSettings.key_hint;
      }
      return null;
    },

    async init() {
      this.initialName = this.$el.dataset.initialName || "User";
      this.profile.full_name = this.initialName;
      await this.refreshProfile();
      window.addEventListener("ai-tribe:open-profile", () => this.openProfile());
      window.addEventListener("ai-tribe:open-settings", () => this.openSettings());
      window.addEventListener("ai-tribe:open-admin", () => this.openAdmin());
    },

    async refreshProfile() {
      const resp = await fetch("/api/user/profile");
      if (!resp.ok) return;
      const data = await resp.json();
      this.profile = {
        full_name: data.full_name || "",
        date_of_birth: data.date_of_birth || "",
        has_photo: !!data.has_photo,
        photo_url: data.photo_url,
        username: data.username || "",
        role: data.role || "",
      };
      this.isAdmin = data.role === "admin" || !!data.is_admin;
      if (data.full_name) this.initialName = data.full_name;
    },

    toggleMenu() {
      this.menuOpen = !this.menuOpen;
    },

    closeMenu() {
      this.menuOpen = false;
    },

    openProfile() {
      this.closeMenu();
      this.settingsOpen = false;
      this.adminOpen = false;
      this.profileOpen = true;
      document.body.classList.add("chrome-panel-open");
    },

    closeProfile() {
      this.profileOpen = false;
      if (!this.settingsOpen && !this.adminOpen) {
        document.body.classList.remove("chrome-panel-open");
      }
    },

    async openSettings() {
      this.closeMenu();
      this.profileOpen = false;
      this.adminOpen = false;
      this.settingsOpen = true;
      document.body.classList.add("chrome-panel-open");
      await this.refreshLlmSettings();
    },

    closeSettings() {
      this.settingsOpen = false;
      if (!this.profileOpen && !this.adminOpen) {
        document.body.classList.remove("chrome-panel-open");
      }
    },

    async openAdmin() {
      this.closeMenu();
      this.profileOpen = false;
      this.settingsOpen = false;
      this.adminOpen = true;
      this.adminMessage = "";
      document.body.classList.add("chrome-panel-open");
      await this.refreshAdminUsers();
    },

    closeAdmin() {
      this.adminOpen = false;
      if (!this.profileOpen && !this.settingsOpen) {
        document.body.classList.remove("chrome-panel-open");
      }
    },

    async refreshLlmSettings() {
      this.llmMessage = "";
      this.llmTestMessage = "";
      const resp = await fetch("/api/user/llm-settings");
      if (!resp.ok) {
        this.llmMessage = "Could not load LLM settings.";
        return;
      }
      this.llmSettings = await resp.json();
      this.selectedProvider = this.llmSettings.active_provider || "";
      this.apiKeyDraft = "";
    },

    async saveLlmKey() {
      const provider = (this.selectedProvider || "").trim();
      const apiKey = (this.apiKeyDraft || "").trim();
      if (!provider || !apiKey) return;
      this.llmSaving = true;
      this.llmMessage = "";
      this.llmTestMessage = "";
      try {
        const resp = await fetch("/api/user/llm-settings/keys", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ provider, api_key: apiKey }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          this.llmMessage = data.detail || "Could not save API key.";
          return;
        }
        this.llmSettings = data.settings;
        this.selectedProvider = this.llmSettings.active_provider || provider;
        this.apiKeyDraft = "";
        this.llmMessage = "API key saved for your account.";
      } finally {
        this.llmSaving = false;
      }
    },

    async removeLlmKey() {
      const provider = (this.selectedProvider || this.llmSettings?.active_provider || "").trim();
      if (!provider) return;
      this.llmMessage = "";
      const resp = await fetch(`/api/user/llm-settings/keys/${provider}`, {
        method: "DELETE",
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        this.llmMessage = data.detail || "Could not remove key.";
        return;
      }
      this.llmSettings = data;
      this.apiKeyDraft = "";
      this.llmTestMessage = "";
      this.llmMessage = "API key removed.";
    },

    async testLlmKey() {
      const provider = (this.selectedProvider || "").trim();
      if (!provider) return;
      this.llmTesting = true;
      this.llmTestMessage = "";
      const body = {};
      const draft = (this.apiKeyDraft || "").trim();
      if (draft) body.api_key = draft;
      try {
        const resp = await fetch(`/api/user/llm-settings/keys/${provider}/test`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const data = await resp.json().catch(() => ({}));
        this.llmTestOk = !!data.ok;
        this.llmTestMessage = data.message || data.detail || "Test failed.";
      } finally {
        this.llmTesting = false;
      }
    },

    async saveLlmPreferences() {
      if (!this.llmSettings) return;
      this.llmMessage = "";
      const resp = await fetch("/api/user/llm-settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          toggle_deepfake: this.llmSettings.toggles.toggle_deepfake,
          toggle_vmmr: this.llmSettings.toggles.toggle_vmmr,
          toggle_estimation: this.llmSettings.toggles.toggle_estimation,
          toggle_fraud: this.llmSettings.toggles.toggle_fraud,
        }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        this.llmMessage = data.detail || "Could not save preferences.";
        return;
      }
      this.llmSettings = data;
    },

    async setLlmToggle(toggle, enabled) {
      if (!this.llmSettings) return;
      this.llmSettings.toggles[toggle] = enabled;
      await this.saveLlmPreferences();
    },

    async refreshAdminUsers() {
      const resp = await fetch("/api/admin/users");
      if (!resp.ok) {
        this.adminMessage = "Could not load users.";
        return;
      }
      const data = await resp.json();
      this.adminUsers = data.users || [];
    },

    async createUser() {
      const email = (this.newUserEmail || "").trim();
      if (!email) return;
      this.adminSubmitting = true;
      this.adminMessage = "";
      try {
        const resp = await fetch("/api/admin/users", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          this.adminMessage = data.detail || "Could not create user.";
          return;
        }
        this.newUserEmail = "";
        this.adminMessage = `User created. A password was emailed to ${data.email}.`;
        await this.refreshAdminUsers();
      } finally {
        this.adminSubmitting = false;
      }
    },

    async deleteUser(row) {
      if (!row?.id || !row.is_active) return;
      if (!window.confirm(`Deactivate ${row.email}? They will not be able to sign in.`)) return;
      this.adminMessage = "";
      const resp = await fetch(`/api/admin/users/${row.id}`, { method: "DELETE" });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        this.adminMessage = data.detail || "Could not delete user.";
        return;
      }
      this.adminMessage = `${row.email} deactivated.`;
      await this.refreshAdminUsers();
    },

    async saveFullName() {
      this.nameMessage = "";
      const resp = await fetch("/api/user/profile/full-name", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ full_name: this.profile.full_name.trim() }),
      });
      const data = await resp.json().catch(() => ({}));
      this.nameMessage = resp.ok ? "Name saved." : data.detail || "Could not save name.";
      if (resp.ok) {
        this.initialName = this.profile.full_name;
        await this.refreshProfile();
      }
    },

    async saveDob() {
      this.dobMessage = "";
      const resp = await fetch("/api/user/profile/date-of-birth", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date_of_birth: this.profile.date_of_birth || null }),
      });
      const data = await resp.json().catch(() => ({}));
      this.dobMessage = resp.ok ? "Date of birth saved." : data.detail || "Could not save date.";
    },

    async savePassword() {
      this.passwordMessage = "";
      const resp = await fetch("/api/user/profile/password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          current_password: this.passwordCurrent,
          new_password: this.passwordNew,
        }),
      });
      const data = await resp.json().catch(() => ({}));
      if (resp.ok) {
        this.passwordMessage = "Password updated.";
        this.passwordCurrent = "";
        this.passwordNew = "";
      } else {
        this.passwordMessage = data.detail || "Could not update password.";
      }
    },

    async uploadPhoto(event) {
      this.photoMessage = "";
      const file = event.target.files?.[0];
      if (!file) return;
      const form = new FormData();
      form.append("photo", file);
      const resp = await fetch("/api/user/profile/photo", { method: "POST", body: form });
      const data = await resp.json().catch(() => ({}));
      this.photoMessage = resp.ok ? "Photo updated." : data.detail || "Upload failed.";
      if (resp.ok) await this.refreshProfile();
      event.target.value = "";
    },

    async removePhoto() {
      this.photoMessage = "";
      const resp = await fetch("/api/user/profile/photo", { method: "DELETE" });
      if (resp.ok) {
        this.photoMessage = "Photo removed.";
        await this.refreshProfile();
      }
    },
  };
}
