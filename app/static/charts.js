function drawLineChart(canvasId, points, opts) {
  const canvas = document.getElementById(canvasId);
  if (!canvas || !points || points.length === 0) return;
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || 600;
  const cssH = canvas.clientHeight || 180;
  canvas.width = cssW * dpr;
  canvas.height = cssH * dpr;
  ctx.scale(dpr, dpr);

  const pad = { t: 16, r: 12, b: 28, l: 12 };
  const w = cssW - pad.l - pad.r;
  const h = cssH - pad.t - pad.b;
  const values = points.map((p) => p.value);
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (min === max) {
    min *= 0.95;
    max *= 1.05;
  }
  const span = max - min || 1;

  ctx.clearRect(0, 0, cssW, cssH);

  // grid
  ctx.strokeStyle = "rgba(14,26,23,0.08)";
  ctx.lineWidth = 1;
  for (let i = 0; i < 4; i++) {
    const y = pad.t + (h * i) / 3;
    ctx.beginPath();
    ctx.moveTo(pad.l, y);
    ctx.lineTo(pad.l + w, y);
    ctx.stroke();
  }

  const xy = points.map((p, i) => {
    const x = pad.l + (points.length === 1 ? w / 2 : (w * i) / (points.length - 1));
    const y = pad.t + h - ((p.value - min) / span) * h;
    return { x, y, label: p.label };
  });

  // area
  const grad = ctx.createLinearGradient(0, pad.t, 0, pad.t + h);
  grad.addColorStop(0, "rgba(31,122,92,0.28)");
  grad.addColorStop(1, "rgba(31,122,92,0)");
  ctx.beginPath();
  xy.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
  ctx.lineTo(xy[xy.length - 1].x, pad.t + h);
  ctx.lineTo(xy[0].x, pad.t + h);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  // line
  ctx.beginPath();
  xy.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
  ctx.strokeStyle = "#1f7a5c";
  ctx.lineWidth = 2.5;
  ctx.lineJoin = "round";
  ctx.stroke();

  // dots
  xy.forEach((p) => {
    ctx.beginPath();
    ctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
    ctx.fillStyle = "#0e1a17";
    ctx.fill();
  });

  // last label
  const last = xy[xy.length - 1];
  ctx.fillStyle = "#5a6e66";
  ctx.font = "12px Manrope, sans-serif";
  ctx.textAlign = "right";
  ctx.fillText(opts && opts.format ? opts.format(points[points.length - 1].value) : String(points[points.length - 1].value), last.x, pad.t + h + 18);
}

function money(n) {
  return Math.round(n).toLocaleString("ru-RU") + " ₽";
}

function drawSparkline(canvas, values) {
  if (!canvas || !values || values.length < 2) return;
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.width;
  const h = canvas.height;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  canvas.style.width = w + "px";
  canvas.style.height = h + "px";
  ctx.scale(dpr, dpr);

  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const up = values[values.length - 1] >= values[0];
  const color = up ? "#176b50" : "#b42318";

  ctx.beginPath();
  values.forEach((v, i) => {
    const x = (i / (values.length - 1)) * (w - 2) + 1;
    const y = h - 2 - ((v - min) / span) * (h - 4);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.6;
  ctx.lineJoin = "round";
  ctx.stroke();
}
