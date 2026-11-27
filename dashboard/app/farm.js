// The farm drawn on Home and Map (isometric, from the approved mockups) and the small top-down
// map of "Where is it?". Plain SVG strings: no library. Water flows (CSS class "flow", see
// app.css) only while irrigating.

const SECT = {
  A: { poly: "150,20 215,52.5 150,85 85,52.5", d: [0, 0], label: [150, 55], pin: [165, 50] },
  B: { poly: "215,52.5 280,85 215,117.5 150,85", d: [65, 32.5], label: [215, 88], pin: [240, 84] },
  C: { poly: "85,52.5 150,85 85,117.5 20,85", d: [-65, 32.5], label: [85, 88], pin: [78, 84] },
  D: { poly: "150,85 215,117.5 150,150 85,117.5", d: [0, 65], label: [150, 120], pin: [165, 116] },
};
const ROWS = [[101.25, 60.625, 166.25, 28.125], [117.5, 68.75, 182.5, 36.25], [133.75, 76.875, 198.75, 44.375]];

// 4 sectors: the demo farm; 2 sectors (A, B): the test bench, branch A and branch B
const LAYOUT = {
  4: {
    base: "20,85 150,150 280,85 280,95 150,160 20,95",
    main: "M58,146 L85,117.5 L150,85 L215,52.5", subs: ["M150,85 L85,52.5", "M150,85 L215,117.5"],
    pump: [30, 140], sensors: [[85, 117.5], [150, 85], [215, 52.5], [85, 52.5], [215, 117.5], [70, 132]],
  },
  2: {
    base: "85,52.5 150,85 215,117.5 280,85 280,95 215,127.5 150,95 85,62.5",
    main: "M112,104 L150,85 L215,52.5", subs: ["M150,85 L85,52.5", "M150,85 L215,117.5"],
    pump: [84, 98], sensors: [[122, 99], [182, 50], [232, 96]],
  },
};

const FONT = 'font-family="Inter,system-ui,sans-serif"';

export function farmSvg({ sectors, irrigating, leakSector, sensors }) {
  const L = LAYOUT[sectors.length === 2 ? 2 : 4];
  let s = `<svg viewBox="0 0 300 172" width="100%" role="img" aria-hidden="true" style="display:block">`;
  s += `<polygon points="${L.base}" fill="#9cc9a6"/>`;
  for (const k of sectors) {
    const v = SECT[k];
    const leak = k === leakSector, on = irrigating.includes(k);
    const fill = leak ? "#fde2e2" : on ? "#c9f2d6" : "#e3ece5";
    const row = leak ? "#f2a4a4" : on ? "#3f9d61" : "#b8c6bd";
    s += `<polygon data-sector="${k}" points="${v.poly}" fill="${fill}" stroke="#fff" stroke-width="1.5"/>`;
    for (const r of ROWS) {
      s += `<line x1="${r[0] + v.d[0]}" y1="${r[1] + v.d[1]}" x2="${r[2] + v.d[0]}" y2="${r[3] + v.d[1]}" stroke="${row}" stroke-width="2.2" stroke-linecap="round" stroke-dasharray="1 5"/>`;
    }
    s += `<text x="${v.label[0]}" y="${v.label[1]}" text-anchor="middle" font-size="12" font-weight="800" fill="#14532D" opacity=".55" ${FONT}>${k}</text>`;
  }
  for (const d of [L.main, ...L.subs]) s += `<path d="${d}" stroke="#a9c9ee" stroke-width="${d === L.main ? 5 : 3.5}" fill="none" stroke-linecap="round"/>`;
  if (irrigating.length) {
    for (const d of [L.main, ...L.subs]) s += `<path class="flow" d="${d}" stroke="#1D5FA8" stroke-width="${d === L.main ? 3 : 2.4}" fill="none" stroke-linecap="round"/>`;
  }
  const [px, py] = L.pump;
  s += `<rect x="${px}" y="${py}" width="34" height="20" rx="6" fill="#fff" stroke="#1D5FA8" stroke-width="1.5"/><text x="${px + 17}" y="${py + 14}" text-anchor="middle" font-size="8.5" font-weight="700" fill="#1D5FA8" ${FONT}>Pump</text>`;
  if (sensors) for (const [x, y] of L.sensors) s += `<circle data-sensor cx="${x}" cy="${y}" r="5.5" fill="#15803D" stroke="#fff" stroke-width="2"/>`;
  if (leakSector && SECT[leakSector]) s += pin(...SECT[leakSector].pin);
  return s + "</svg>";
}

function pin(x, y) {
  return `<g data-pin><circle cx="${x}" cy="${y + 2}" r="8" fill="#DC2626" opacity=".35"><animate attributeName="r" values="6;20" dur="1.6s" repeatCount="indefinite"/><animate attributeName="opacity" values=".45;0" dur="1.6s" repeatCount="indefinite"/></circle>`
    + `<path d="M${x} ${y - 24}c-6.6 0-11 4.9-11 10.6 0 7.6 11 16.4 11 16.4s11-8.8 11-16.4C${x + 11} ${y - 19.1} ${x + 6.6} ${y - 24} ${x} ${y - 24}z" fill="#DC2626" stroke="#fff" stroke-width="1.5"/><circle cx="${x}" cy="${y - 14}" r="3.8" fill="#fff"/></g>`;
}

/** Top-down view of the leak zone: the pipe line, the probable spot, the farmer, the route. */
export function whereSvg({ tap }) {
  let s = `<svg viewBox="0 0 270 150" width="100%" role="img" aria-hidden="true" style="display:block;background:#e7f3ea">`;
  for (let i = 0; i < 9; i++) s += `<line x1="0" y1="${12 + i * 16}" x2="270" y2="${12 + i * 16}" stroke="#bfe3c9" stroke-width="5" stroke-dasharray="2 7" stroke-linecap="round"/>`;
  s += `<path d="M0 60 H270" stroke="#1D5FA8" stroke-width="4" opacity=".75"/>`;
  s += `<rect x="128" y="50" width="78" height="20" rx="10" fill="#DC2626" opacity=".18"/>`;
  s += `<path d="M48 128 C 80 128, 110 110, 160 76" stroke="#15803D" stroke-width="2.5" fill="none" stroke-dasharray="5 5"/>`;
  s += `<circle cx="48" cy="128" r="7" fill="#15803D" stroke="#fff" stroke-width="2.5"/>`;
  s += pin(167, 56);
  if (tap) s += `<text x="190" y="40" font-size="12" font-weight="800" fill="#DC2626" ${FONT}>${tap}</text>`;
  return s + "</svg>";
}
