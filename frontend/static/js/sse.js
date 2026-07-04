/**
 * Live pipeline stage tracker via Server-Sent Events.
 * Renders the full stage chain on load; SSE transitions status and timers.
 * Timers are anchored to server-recorded pipeline_events timestamps.
 */
function pipelineTracker({
  claimId,
  stages = [],
  initialEvents = [],
  claimStatus = null,
} = {}) {
  return {
    claimId,
    stages: stages.map((stage) => ({
      key: stage.key,
      label: stage.label,
      status: stage.status || "pending",
      detail: stage.detail || null,
      startedAtMs: null,
      durationSeconds: null,
      timerLabel: "",
    })),
    complete: false,
    halted: false,
    haltMessage: "",
    reviewSent: false,
    connecting: false,
    estimateUrl: claimId ? `/claims/${claimId}/estimate` : "#",
    pipelineStartedAtMs: null,
    totalDurationSeconds: null,
    totalTimerLabel: "",
    nowMs: Date.now(),
    _source: null,
    _tickTimer: null,

    init() {
      if (!this.claimId) return;

      for (const event of initialEvents) {
        this.applyEvent(event, { fromHistory: true });
      }
      this.refreshTimers();

      const terminal =
        claimStatus === "estimate_ready" ||
        claimStatus === "authenticity_failed" ||
        claimStatus === "review_required" ||
        claimStatus === "closed";

      if (terminal) {
        this.complete = true;
        this.connecting = false;
        this.halted =
          claimStatus === "authenticity_failed" ||
          claimStatus === "review_required";
        if (this.halted && !this.haltMessage) {
          this.haltMessage =
            "This claim is paused and waiting for a surveyor to review it.";
        }
        if (claimStatus === "review_required") {
          this.reviewSent = true;
        }
        this.freezeTotalFromStages();
        this.refreshTimers();
        this.$nextTick(() => this.scrollToActiveStage({ instant: true }));
        return;
      }

      this.connecting = initialEvents.length === 0;
      this.startTicker();
      this.connect();
      this.$nextTick(() => this.scrollToActiveStage({ instant: true }));
    },

    activeStageKey() {
      const started = this.stages.find((stage) => stage.status === "started");
      if (started) return started.key;
      for (let i = this.stages.length - 1; i >= 0; i -= 1) {
        const stage = this.stages[i];
        if (
          stage.status === "passed" ||
          stage.status === "failed" ||
          stage.status === "warning"
        ) {
          return stage.key;
        }
      }
      return this.stages[0] ? this.stages[0].key : null;
    },

    scrollToActiveStage({ instant = false } = {}) {
      const windowEl = this.$refs.stageWindow;
      if (!windowEl) return;
      const key = this.activeStageKey();
      if (!key) return;
      const row = windowEl.querySelector(`[data-stage-key="${key}"]`);
      if (!row) return;
      // Keep the in-progress stage roughly centered in the ~5-row window.
      const rowTop = row.offsetTop;
      const rowHeight = row.offsetHeight;
      const target =
        rowTop - windowEl.clientHeight / 2 + rowHeight / 2;
      windowEl.scrollTo({
        top: Math.max(0, target),
        behavior: instant ? "auto" : "smooth",
      });
    },

    connect() {
      if (this._source) {
        this._source.close();
      }

      const source = new EventSource(`/api/pipeline/${this.claimId}/stream`);
      this._source = source;

      source.addEventListener("stage", (message) => {
        let payload;
        try {
          payload = JSON.parse(message.data);
        } catch (_err) {
          return;
        }
        this.applyEvent(payload);
      });

      source.onerror = () => {
        if (this.complete) {
          source.close();
        }
      };
    },

    startTicker() {
      if (this._tickTimer) return;
      this._tickTimer = setInterval(() => {
        this.nowMs = Date.now();
        this.refreshTimers();
      }, 250);
    },

    stopTicker() {
      if (this._tickTimer) {
        clearInterval(this._tickTimer);
        this._tickTimer = null;
      }
    },

    parseTs(iso) {
      if (!iso) return null;
      const ms = Date.parse(iso);
      return Number.isNaN(ms) ? null : ms;
    },

    formatSeconds(sec) {
      if (sec == null || Number.isNaN(sec) || sec < 0) return "";
      return `${Math.floor(sec)}s`;
    },

    refreshTimers() {
      for (const stage of this.stages) {
        if (stage.durationSeconds != null) {
          stage.timerLabel = this.formatSeconds(stage.durationSeconds);
        } else if (stage.status === "started" && stage.startedAtMs != null) {
          stage.timerLabel = this.formatSeconds(
            (this.nowMs - stage.startedAtMs) / 1000
          );
        } else {
          stage.timerLabel = "";
        }
      }

      if (this.totalDurationSeconds != null) {
        this.totalTimerLabel = this.formatSeconds(this.totalDurationSeconds);
      } else if (this.pipelineStartedAtMs != null) {
        this.totalTimerLabel = this.formatSeconds(
          (this.nowMs - this.pipelineStartedAtMs) / 1000
        );
      } else {
        this.totalTimerLabel = "";
      }
    },

    freezeTotalFromStages() {
      if (this.totalDurationSeconds != null) return;
      if (this.pipelineStartedAtMs == null) return;
      let endMs = null;
      for (const stage of this.stages) {
        if (stage.startedAtMs != null && stage.durationSeconds != null) {
          const stageEnd = stage.startedAtMs + stage.durationSeconds * 1000;
          if (endMs == null || stageEnd > endMs) endMs = stageEnd;
        }
      }
      if (endMs != null) {
        this.totalDurationSeconds = Math.max(
          0,
          (endMs - this.pipelineStartedAtMs) / 1000
        );
      }
    },

    applyEvent(event, { fromHistory = false } = {}) {
      if (!event) return;
      this.connecting = false;

      const ts = this.parseTs(event.created_at);

      if (event.stage_key && event.stage_key !== "pipeline_error") {
        const stage = this.stages.find((item) => item.key === event.stage_key);
        if (stage) {
          if (event.status === "started") {
            stage.status = "started";
            if (ts != null) {
              stage.startedAtMs = ts;
              stage.durationSeconds = null;
              if (
                this.pipelineStartedAtMs == null ||
                ts < this.pipelineStartedAtMs
              ) {
                this.pipelineStartedAtMs = ts;
              }
            }
          } else if (
            event.status === "passed" ||
            event.status === "failed" ||
            event.status === "warning"
          ) {
            stage.status = event.status;
            if (ts != null && stage.startedAtMs != null) {
              stage.durationSeconds = Math.max(
                0,
                (ts - stage.startedAtMs) / 1000
              );
            }
          } else if (event.status) {
            stage.status = event.status;
          }

          if (event.stage_label) {
            stage.label = event.stage_label;
          }
          if (Object.prototype.hasOwnProperty.call(event, "detail")) {
            stage.detail = event.detail;
          }

          if (!fromHistory) {
            this.$nextTick(() => this.scrollToActiveStage());
          }
        }
      }

      if (event.pipeline_complete) {
        this.complete = true;
        this.halted = Boolean(event.halted);
        if (event.halt_message) {
          this.haltMessage = event.halt_message;
        }
        if (event.redirect) {
          this.estimateUrl = event.redirect;
        }
        if (ts != null && this.pipelineStartedAtMs != null) {
          this.totalDurationSeconds = Math.max(
            0,
            (ts - this.pipelineStartedAtMs) / 1000
          );
        } else {
          this.freezeTotalFromStages();
        }
        this.refreshTimers();
        this.stopTicker();
        if (this._source) {
          this._source.close();
          this._source = null;
        }
        return;
      }

      if (!fromHistory) {
        this.refreshTimers();
      }
    },

    iconClass(status) {
      switch (status) {
        case "started":
          return "border-gold/50 bg-gold/15";
        case "passed":
          return "border-emerald-500/35 bg-emerald-500/10";
        case "failed":
          return "border-amber-400/40 bg-amber-500/10";
        case "warning":
          return "border-amber-400/35 bg-amber-500/10";
        default:
          return "border-navy/10 bg-canvas dark:border-white/10 dark:bg-ink/70";
      }
    },

    async requestReview() {
      if (!this.claimId || this.reviewSent) return;
      try {
        const response = await fetch(
          `/api/pipeline/${this.claimId}/request-review`,
          {
            method: "POST",
            credentials: "same-origin",
            headers: { Accept: "application/json" },
          }
        );
        if (response.ok) {
          this.reviewSent = true;
          this.haltMessage =
            "This claim has been sent for manual review. A surveyor will take it from here.";
        }
      } catch (_err) {
        // Keep the button available if the request fails.
      }
    },
  };
}
