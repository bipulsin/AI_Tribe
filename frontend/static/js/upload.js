/**
 * Claim upload zone: drag-and-drop, thumbnails, submit via multipart FormData.
 */
function claimUpload({
  maxImages = 10,
  maxUploadMb = 25,
  surveyorName = "",
} = {}) {
  const maxBytes = maxUploadMb * 1024 * 1024;
  const imageTypes = ["image/jpeg", "image/png", "image/webp", "image/gif"];
  const videoTypes = ["video/mp4", "video/webm", "video/quicktime"];

  return {
    maxImages,
    maxUploadMb,
    garageName: "",
    surveyorName: surveyorName || "",
    accidentDate: "",
    accidentDateMax: (() => {
      const d = new Date();
      d.setDate(d.getDate() - 1);
      return d.toISOString().slice(0, 10);
    })(),
    images: [],
    video: null,
    dragOver: false,
    error: "",
    submitting: false,
    _idSeq: 0,

    get previews() {
      const items = [...this.images];
      if (this.video) items.push(this.video);
      return items;
    },

    get imageCounterLabel() {
      return `${this.images.length} of ${this.maxImages} images added`;
    },

    get canSubmit() {
      return this.images.length >= 1 && !!this.accidentDate && !this.submitting;
    },

    onDrop(event) {
      this.dragOver = false;
      this.addFiles(event.dataTransfer.files);
    },

    onFileSelect(event) {
      this.addFiles(event.target.files);
      event.target.value = "";
    },

    pickSuggestion(event, field) {
      const btn = event.target.closest("[data-suggest]");
      if (!btn) return;
      const value = btn.getAttribute("data-suggest") || "";
      if (field === "garageName") {
        this.garageName = value;
        if (this.$refs.garageNameSuggestions) {
          this.$refs.garageNameSuggestions.innerHTML = "";
        }
      } else if (field === "surveyorName") {
        this.surveyorName = value;
        if (this.$refs.surveyorNameSuggestions) {
          this.$refs.surveyorNameSuggestions.innerHTML = "";
        }
      }
    },

    addFiles(fileList) {
      this.error = "";
      const files = Array.from(fileList || []);
      // Reassign arrays so Alpine always detects the update.
      const nextImages = [...this.images];
      let nextVideo = this.video;

      for (const file of files) {
        if (file.size > maxBytes) {
          this.error = `"${file.name}" exceeds the ${maxUploadMb} MB limit.`;
          continue;
        }

        const isImage =
          imageTypes.includes(file.type) ||
          /\.(jpe?g|png|webp|gif)$/i.test(file.name);
        const isVideo =
          videoTypes.includes(file.type) ||
          /\.(mp4|webm|mov)$/i.test(file.name);

        if (isImage) {
          if (nextImages.length >= this.maxImages) {
            this.error = `You can add at most ${this.maxImages} images.`;
            continue;
          }
          nextImages.push(this._makeItem(file, false));
        } else if (isVideo) {
          if (nextVideo) {
            URL.revokeObjectURL(nextVideo.previewUrl);
          }
          nextVideo = this._makeItem(file, true);
        } else {
          this.error = `"${file.name}" is not a supported image or video type.`;
        }
      }

      this.images = nextImages;
      this.video = nextVideo;
    },

    _makeItem(file, isVideo) {
      this._idSeq += 1;
      return {
        id: this._idSeq,
        file,
        name: file.name,
        isVideo,
        previewUrl: URL.createObjectURL(file),
      };
    },

    removeItem(id) {
      const imageIndex = this.images.findIndex((item) => item.id === id);
      if (imageIndex >= 0) {
        URL.revokeObjectURL(this.images[imageIndex].previewUrl);
        this.images = this.images.filter((item) => item.id !== id);
        this.error = "";
        return;
      }
      if (this.video && this.video.id === id) {
        URL.revokeObjectURL(this.video.previewUrl);
        this.video = null;
        this.error = "";
      }
    },

    async submitClaim() {
      if (!this.canSubmit) return;

      this.submitting = true;
      this.error = "";

      const formData = new FormData();
      for (const item of this.images) {
        formData.append("images", item.file, item.name);
      }
      if (this.video) {
        formData.append("video", this.video.file, this.video.name);
      }
      if (this.garageName) {
        formData.append("garage_name", this.garageName.trim());
      }
      if (this.surveyorName) {
        formData.append("surveyor_name", this.surveyorName.trim());
      }
      if (this.accidentDate) {
        formData.append("accident_date", this.accidentDate.trim());
      }

      try {
        const response = await fetch("/claims", {
          method: "POST",
          body: formData,
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });

        if (response.status === 401) {
          window.location.href = "/login";
          return;
        }

        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          this.error = payload.detail || "Could not submit the claim. Try again.";
          this.submitting = false;
          return;
        }

        window.location.href = payload.redirect || `/claims/${payload.claim_id}/processing`;
      } catch (_err) {
        this.error = "Network error while submitting. Check your connection and try again.";
        this.submitting = false;
      }
    },
  };
}
