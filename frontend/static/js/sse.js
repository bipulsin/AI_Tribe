/**
 * Live pipeline stage tracker via Server-Sent Events.
 * Replays history on connect, then applies live stage updates in place.
 */
function pipelineTracker({
  claimId,
  stages = [],
  initialEvents = [],
  claimStatus = null,
} = {}) {
  return {
    claimId,
    stages: stages.map((stage) => ({ ...stage })),
    complete: false,
    halted: false,
    haltMessage: "",
    reviewSent: false,
    connecting: false,
    estimateUrl: claimId ? `/claims/${claimId}/estimate` : "#",
    _source: null,

    init() {
      if (!this.claimId) return;

      for (const event of initialEvents) {
        this.applyEvent(event);
      }

      if (
        claimStatus === "estimate_ready" ||
        claimStatus === "authenticity_failed" ||
        claimStatus === "review_required" ||
        claimStatus === "closed"
      ) {
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
        return;
      }

      this.connecting = initialEvents.length === 0;
      this.connect();
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
        // Browser will retry EventSource automatically unless we close it.
        if (this.complete) {
          source.close();
        }
      };
    },

    applyEvent(event) {
      if (!event) return;
      this.connecting = false;

      if (event.stage_key && event.stage_key !== "pipeline_error") {
        const stage = this.stages.find((item) => item.key === event.stage_key);
        if (stage) {
          if (event.status) {
            stage.status = event.status;
          }
          if (event.stage_label) {
            stage.label = event.stage_label;
          }
          if (Object.prototype.hasOwnProperty.call(event, "detail")) {
            stage.detail = event.detail;
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
        if (this._source) {
          this._source.close();
          this._source = null;
        }
      }
    },

    iconClass(status) {
      switch (status) {
        case "started":
          return "border-gold/40 bg-gold/10";
        case "passed":
          return "border-emerald-200 bg-emerald-50";
        case "failed":
          return "border-amber-300 bg-amber-50";
        case "warning":
          return "border-amber-200 bg-amber-50";
        default:
          return "border-navy/10 bg-canvas";
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
