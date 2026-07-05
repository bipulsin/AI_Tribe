function labVmmrLabeling() {
  return {
    stats: {},
    item: null,
    catalog: [],
    make: "",
    model: "",
    loading: true,
    busy: false,
    message: "",

    async init() {
      await this.refreshStats();
      await this.loadNext();
      this.loading = false;
    },

    async refreshStats() {
      const resp = await fetch("/api/lab/vmmr-labeling/stats");
      if (resp.ok) this.stats = await resp.json();
    },

    async loadNext() {
      const resp = await fetch("/api/lab/vmmr-labeling/next");
      if (!resp.ok) {
        this.message = "Could not load next label.";
        this.item = null;
        return;
      }
      const data = await resp.json();
      this.item = data.item;
      this.catalog = data.catalog || [];
      if (this.item) {
        this.make = this.item.suggested_make || "";
        this.model = this.item.suggested_model || "";
      }
    },

    applyAlt(alt) {
      this.make = alt.make || "";
      this.model = alt.model || "";
    },

    useSuggestion() {
      if (!this.item) return;
      this.make = this.item.suggested_make || "";
      this.model = this.item.suggested_model || "";
    },

    async confirmLabel() {
      if (!this.item || this.busy) return;
      this.busy = true;
      this.message = "";
      try {
        const resp = await fetch(`/api/lab/vmmr-labeling/${this.item.id}/confirm`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ make: this.make.trim(), model: this.model.trim() }),
        });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          this.message = err.detail || "Confirm failed.";
          return;
        }
        await this.refreshStats();
        await this.loadNext();
        this.message = "Label saved to lab dataset (not live pipeline).";
      } finally {
        this.busy = false;
      }
    },

    async skipLabel() {
      if (!this.item || this.busy) return;
      this.busy = true;
      try {
        await fetch(`/api/lab/vmmr-labeling/${this.item.id}/skip`, { method: "POST" });
        await this.refreshStats();
        await this.loadNext();
      } finally {
        this.busy = false;
      }
    },

    async buildQueue() {
      this.busy = true;
      this.message = "Building overlap queue (may take several minutes)…";
      try {
        const resp = await fetch("/api/lab/vmmr-labeling/build-overlap-queue", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ split: "val", limit: 0 }),
        });
        const data = await resp.json().catch(() => ({}));
        this.message = resp.ok
          ? `Overlap queue: ${data.queued ?? 0} items.`
          : data.detail || "Build failed.";
      } finally {
        this.busy = false;
      }
    },

    async importQueue() {
      this.busy = true;
      try {
        const resp = await fetch("/api/lab/vmmr-labeling/import-queue", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_guess: true }),
        });
        const data = await resp.json().catch(() => ({}));
        this.message = resp.ok
          ? `Imported ${data.imported ?? 0} (skipped ${data.skipped ?? 0}).`
          : data.detail || "Import failed.";
        await this.refreshStats();
        await this.loadNext();
      } finally {
        this.busy = false;
      }
    },
  };
}
