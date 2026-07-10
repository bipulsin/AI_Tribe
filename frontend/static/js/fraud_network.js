/**
 * Per-claim organised-fraud neighborhood diagram (vis-network CDN).
 * Always renders: clear single-node + green badge, or local neighborhood.
 * Caption: network of claims sharing garage/surveyor.
 *
 * Options:
 *   interactive — enable pan/zoom/drag (used in the enlarge modal)
 */
function buildFraudNetworkData(payload) {
  const data = payload || { nodes: [], edges: [], clear: true };
  const nodes = new vis.DataSet(
    (data.nodes || []).map((node) => {
      const colors = {
        claimant: { background: "#1e3a5f", border: "#94a3b8" },
        surveyor: { background: "#1e3a5f", border: "#b8860b" },
        garage: { background: "#1e3a5f", border: "#64748b" },
      };
      const base = colors[node.kind] || colors.claimant;
      if (node.flagged) {
        return {
          id: node.id,
          label: node.label,
          color: {
            background: "rgba(120, 53, 15, 0.45)",
            border: "#fbbf24",
            highlight: { background: "rgba(120, 53, 15, 0.55)", border: "#fde68a" },
          },
          borderWidth: 2,
          font: { color: "#fde68a", size: 12 },
          shape: "dot",
          size: 16,
          title: `${node.kind} · degree ${node.degree} · pattern of interest`,
        };
      }
      return {
        id: node.id,
        label: node.label,
        color: {
          background: base.background,
          border: base.border,
          highlight: { background: "#254a73", border: "#e8ecf1" },
        },
        borderWidth: 1,
        font: { color: "#e8ecf1", size: 12 },
        shape: "dot",
        size: data.clear ? 18 : 14,
        title: `${node.kind}${node.degree ? ` · degree ${node.degree}` : ""}`,
      };
    })
  );

  const edges = new vis.DataSet(
    (data.edges || []).map((edge, index) => ({
      id: `e${index}`,
      from: edge.from,
      to: edge.to,
      color: { color: "rgba(148, 163, 184, 0.55)" },
      width: 1,
      title: edge.title || "",
    }))
  );

  return { data, nodes, edges };
}

function renderFraudNetwork(containerId, payload, options = {}) {
  const container = document.getElementById(containerId);
  if (!container || typeof vis === "undefined") return null;

  const interactive = !!options.interactive;
  const { data, nodes, edges } = buildFraudNetworkData(payload);

  const network = new vis.Network(
    container,
    { nodes, edges },
    {
      interaction: {
        dragNodes: interactive,
        dragView: interactive,
        zoomView: interactive,
        selectable: interactive,
        navigationButtons: false,
        keyboard: interactive,
      },
      physics: { enabled: !data.clear, stabilization: { iterations: 40 } },
      layout: data.clear ? { randomSeed: 1 } : { improvedLayout: true },
    }
  );

  const badge = document.getElementById(`${containerId}-clear-badge`);
  if (badge) {
    badge.hidden = !data.clear;
  }

  if (interactive) {
    // Ensure layout after the modal becomes visible.
    requestAnimationFrame(() => {
      network.redraw();
      network.fit({ animation: false });
    });
  }

  return network;
}

(function initFraudNetworkModal() {
  let payloadCache = null;
  let modalNetwork = null;

  function getModal() {
    return document.getElementById("fraud-network-modal");
  }

  function closeModal() {
    const modal = getModal();
    if (!modal) return;
    modal.hidden = true;
    document.body.classList.remove("fraud-network-modal-open");
    if (modalNetwork) {
      modalNetwork.destroy();
      modalNetwork = null;
    }
    const canvas = document.getElementById("fraud-network-modal-canvas");
    if (canvas) canvas.innerHTML = "";
  }

  function openModal() {
    const modal = getModal();
    if (!modal || !payloadCache) return;
    modal.hidden = false;
    document.body.classList.add("fraud-network-modal-open");
    const panel = modal.querySelector(".fraud-network-modal-panel");
    if (panel) panel.focus();

    const canvas = document.getElementById("fraud-network-modal-canvas");
    if (canvas) canvas.innerHTML = "";
    modalNetwork = renderFraudNetwork("fraud-network-modal-canvas", payloadCache, {
      interactive: true,
    });
  }

  function zoomBy(factor) {
    if (!modalNetwork) return;
    const scale = modalNetwork.getScale() * factor;
    const position = modalNetwork.getViewPosition();
    modalNetwork.moveTo({
      scale: Math.max(0.2, Math.min(scale, 4)),
      position,
      animation: { duration: 180, easingFunction: "easeInOutQuad" },
    });
  }

  function bindModalChrome() {
    const modal = getModal();
    if (!modal || modal.dataset.bound === "1") return;
    modal.dataset.bound = "1";

    modal.querySelectorAll("[data-fraud-network-close]").forEach((el) => {
      el.addEventListener("click", closeModal);
    });

    document.addEventListener("keydown", (event) => {
      if (modal.hidden) return;
      if (event.key === "Escape") {
        event.preventDefault();
        closeModal();
      }
    });

    const zoomIn = document.getElementById("fraud-network-zoom-in");
    const zoomOut = document.getElementById("fraud-network-zoom-out");
    if (zoomIn) zoomIn.addEventListener("click", () => zoomBy(1.3));
    if (zoomOut) zoomOut.addEventListener("click", () => zoomBy(1 / 1.3));

    const opener = document.getElementById("fraud-network-open");
    if (opener) {
      opener.addEventListener("click", openModal);
      opener.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openModal();
        }
      });
    }
  }

  window.setFraudNetworkPayload = function setFraudNetworkPayload(payload) {
    payloadCache = payload;
  };

  window.openFraudNetworkModal = openModal;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindModalChrome);
  } else {
    bindModalChrome();
  }
})();
