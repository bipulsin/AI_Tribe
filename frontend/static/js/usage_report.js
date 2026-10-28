function usageReport({ defaultStart, defaultEnd, users = [] } = {}) {
  return {
    start: defaultStart || "",
    end: defaultEnd || "",
    userId: "",
    users: users || [],
    rows: [],
    details: {},
    expandedKey: "",
    detailLoadingKey: "",
    busy: false,
    scanning: false,
    error: "",
    scanMessage: "",

    init() {
      this.load();
    },

    rowKey(row) {
      return String(row.user.id);
    },

    isExpanded(row) {
      return this.expandedKey === this.rowKey(row);
    },

    dash(value) {
      if (value === null || value === undefined || value === "") return "—";
      return String(value);
    },

    formatTime(iso) {
      if (!iso) return "—";
      try {
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return String(iso);
        return d.toISOString().replace("T", " ").slice(0, 19) + " UTC";
      } catch (_err) {
        return String(iso);
      }
    },

    async load() {
      this.busy = true;
      this.error = "";
      try {
        const params = new URLSearchParams();
        if (this.start) params.set("start", this.start);
        if (this.end) params.set("end", this.end);
        if (this.userId) params.set("user_id", this.userId);
        const resp = await fetch(`/api/admin/usage-report?${params}`, {
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          this.error = data.detail || "Could not load report.";
          this.rows = [];
          return;
        }
        this.rows = data.rows || [];
        if (data.users) this.users = data.users;
        this.details = {};
        this.expandedKey = "";
      } catch (_err) {
        this.error = "Network error loading report.";
      } finally {
        this.busy = false;
      }
    },

    async scanHistory() {
      this.scanning = true;
      this.scanMessage = "";
      this.error = "";
      try {
        const resp = await fetch("/api/admin/usage-report/scan-history", {
          method: "POST",
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          this.error = data.detail || "History scan failed.";
          return;
        }
        this.scanMessage =
          `Imported ${data.inserted || 0} historical trace(s)` +
          (data.skipped ? ` (${data.skipped} already present)` : "") +
          ` from ${data.scanned || 0} scanned record(s).`;
        await this.load();
      } catch (_err) {
        this.error = "Network error during history scan.";
      } finally {
        this.scanning = false;
      }
    },

    async toggleDetail(row, event) {
      if (event) {
        const tag = (event.target && event.target.tagName) || "";
        if (tag === "A" || tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") {
          return;
        }
      }
      if (!row || row.status !== "accessed") return;
      const key = this.rowKey(row);
      if (this.expandedKey === key) {
        this.expandedKey = "";
        return;
      }
      this.expandedKey = key;
      if (this.details[key]) return;
      this.detailLoadingKey = key;
      this.error = "";
      try {
        const params = new URLSearchParams({
          user_id: String(row.user.id),
          start: row.range_start || this.start,
          end: row.range_end || this.end,
        });
        const resp = await fetch(`/api/admin/usage-report/detail?${params}`, {
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          this.error = data.detail || "Could not load detail.";
          this.expandedKey = "";
          return;
        }
        this.details = { ...this.details, [key]: data.events || [] };
      } catch (_err) {
        this.error = "Network error loading detail.";
        this.expandedKey = "";
      } finally {
        this.detailLoadingKey = "";
      }
    },

    onRowKeydown(row, event) {
      if (!event) return;
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        this.toggleDetail(row, event);
      }
    },
  };
}
