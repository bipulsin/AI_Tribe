/**
 * Per-claim organised-fraud neighborhood diagram (vis-network CDN).
 * Always renders: clear single-node + green badge, or local neighborhood.
 */
function renderFraudNetwork(containerId, payload) {
  const container = document.getElementById(containerId);
  if (!container || typeof vis === "undefined") return;

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

  const network = new vis.Network(
    container,
    { nodes, edges },
    {
      interaction: { dragNodes: false, dragView: false, zoomView: false, selectable: false },
      physics: { enabled: !data.clear, stabilization: { iterations: 40 } },
      layout: data.clear
        ? { randomSeed: 1 }
        : { improvedLayout: true },
    }
  );

  const badge = document.getElementById(`${containerId}-clear-badge`);
  if (badge) {
    badge.hidden = !data.clear;
  }

  return network;
}
