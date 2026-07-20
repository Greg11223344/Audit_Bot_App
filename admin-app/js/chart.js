// Minimal, dependency-free SVG bar chart. No Chart.js/Recharts available (no npm on this
// machine) -- this covers exactly what the dashboard trend needs: a responsive bar chart with
// axis labels and hover tooltips, styled to match the rest of the app.

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// data: [{label, value}], rendered oldest-to-newest left-to-right regardless of page direction
// (kept LTR intentionally -- charts conventionally read left-to-right even in RTL UIs).
export function renderBarChart(container, data, options = {}) {
  const width = options.width || 640;
  const height = options.height || 220;
  const padding = { top: 16, right: 12, bottom: 28, left: 12 };
  const barGap = 6;
  const color = options.color || "#52796f";
  const labelEvery = options.labelEvery || Math.max(1, Math.ceil(data.length / 6));

  const maxValue = Math.max(1, ...data.map((d) => d.value));
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const barWidth = data.length ? plotWidth / data.length - barGap : 0;

  let bars = "";
  let labels = "";

  data.forEach((d, i) => {
    const barHeight = maxValue > 0 ? (d.value / maxValue) * plotHeight : 0;
    const x = padding.left + i * (barWidth + barGap);
    const y = padding.top + (plotHeight - barHeight);

    bars += `
      <rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barWidth.toFixed(1)}" height="${Math.max(barHeight, 1).toFixed(1)}"
            rx="3" fill="${color}" class="chart-bar">
        <title>${escapeHtml(d.label)}: ${d.value}</title>
      </rect>`;

    if (i % labelEvery === 0 || i === data.length - 1) {
      labels += `<text x="${(x + barWidth / 2).toFixed(1)}" y="${height - 8}" text-anchor="middle" class="chart-axis-label">${escapeHtml(d.label)}</text>`;
    }
  });

  container.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" class="chart-svg" dir="ltr" preserveAspectRatio="xMidYMid meet">
      ${bars}
      ${labels}
    </svg>
  `;
}
