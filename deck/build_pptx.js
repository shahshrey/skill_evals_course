// Renders content.json as a PowerPoint file with pptxgenjs.
// Run: node build_pptx.js   (writes skill-evals.pptx next to this file)
const pptxgen = require("pptxgenjs");
const fs = require("fs");
const path = require("path");

const content = JSON.parse(fs.readFileSync(path.join(__dirname, "content.json"), "utf8"));

const NAVY = "1B2A41", WHITE = "FFFFFF", ACCENT = "C9651F", INK = "1B2A41";
const MUTED = "5B6472", LINE = "D9DDE3", CARD = "F4F6F8", WARM = "FBF1E8", WARM_LINE = "EAD3C2";
const HEAD = "Georgia", BODY = "Calibri";
const W = 10, H = 5.625, M = 0.5;          // slide size in inches and the margin

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.title = content.title;
pres.author = "Shrey";

const bulletRuns = (lines, opts = {}) =>
  lines.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < lines.length - 1, paraSpaceAfter: 4, ...opts } }));

function footer(slide, dark) {
  slide.addText(content.title, { x: M, y: H - 0.42, w: 5, h: 0.3, fontFace: BODY, fontSize: 9,
    color: dark ? "8A94A6" : "8A8F99", margin: 0 });
}

function eyebrow(slide, text, y, color = ACCENT) {
  slide.addText(text.toUpperCase(), { x: M, y, w: 9, h: 0.3, fontFace: BODY, fontSize: 10, bold: true,
    charSpacing: 3, color, margin: 0 });
}

function card(slide, x, y, w, h, title, lines, warm) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.12,
    fill: { color: warm ? WARM : CARD }, line: { color: warm ? WARM_LINE : LINE, width: 0.75 } });
  slide.addText(title, { x: x + 0.25, y: y + 0.18, w: w - 0.5, h: 0.35, fontFace: BODY, fontSize: 14,
    bold: true, color: INK, margin: 0 });
  slide.addText(bulletRuns(lines), { x: x + 0.25, y: y + 0.6, w: w - 0.5, h: h - 0.75, fontFace: BODY,
    fontSize: 12.5, color: MUTED, valign: "top", margin: 0 });
}

function statement(slide, s) {
  slide.background = { color: NAVY };
  eyebrow(slide, s.eyebrow, 1.55, "E8A36A");
  slide.addText(s.title, { x: M, y: 1.9, w: 8.4, h: 1.4, fontFace: HEAD, fontSize: s.kind === "cover" ? 40 : 30,
    bold: true, color: "F7F5F0", valign: "top", margin: 0 });
  slide.addText(s.text, { x: M, y: 3.4, w: 8.6, h: 1.0, fontFace: BODY, fontSize: 15, color: "C9D1D9",
    valign: "top", margin: 0 });
  footer(slide, true);
}

function cards(slide, s) {
  slide.background = { color: WHITE };
  eyebrow(slide, s.eyebrow, 0.45);
  slide.addText(s.title, { x: M, y: 0.75, w: 9, h: 0.7, fontFace: HEAD, fontSize: 26, bold: true, color: INK, margin: 0 });
  const n = s.cards.length, gap = 0.25, cw = (W - 2 * M - gap * (n - 1)) / n;
  const top = 1.7, ch = s.footer ? 2.4 : 2.6;
  s.cards.forEach((c, i) => card(slide, M + i * (cw + gap), top, cw, ch, c.title, c.lines, false));
  if (s.footer) slide.addText(s.footer, { x: M, y: top + ch + 0.15, w: 9, h: 0.4, fontFace: BODY, fontSize: 12,
    color: MUTED, italic: true, margin: 0 });
  footer(slide, false);
}

function typeSlide(slide, s) {
  slide.background = { color: WHITE };
  // The big numeral is the slide's visual anchor; it repeats on all eleven.
  // Calibri has lining figures, so every numeral sits at the same height;
  // Georgia's old-style figures bounced up into the eyebrow on 6 and 8.
  slide.addText(String(s.number), { x: M, y: 0.72, w: 1.1, h: 0.9, fontFace: BODY, fontSize: 54, bold: true,
    color: ACCENT, margin: 0, valign: "top" });
  eyebrow(slide, s.group, 0.45);
  const tx = 1.6;
  slide.addText(s.title, { x: tx, y: 0.75, w: W - M - tx, h: 0.55, fontFace: HEAD, fontSize: 26, bold: true, color: INK, margin: 0 });
  slide.addText(s.question, { x: tx, y: 1.32, w: W - M - tx, h: 0.6, fontFace: BODY, fontSize: 13.5, color: MUTED,
    italic: true, valign: "top", margin: 0 });
  const top = 2.1, ch = 2.55, gap = 0.25, cw = (W - 2 * M - gap) / 2;
  card(slide, M, top, cw, ch, "How it works", s.method, false);
  card(slide, M + cw + gap, top, cw, ch, "Watch out for", s.watch, true);
  footer(slide, false);
}

function rules(slide, s) {
  slide.background = { color: WHITE };
  eyebrow(slide, s.eyebrow, 0.45);
  slide.addText(s.title, { x: M, y: 0.75, w: 9, h: 0.6, fontFace: HEAD, fontSize: 26, bold: true, color: INK, margin: 0 });
  const cols = 2, rows = 3, gap = 0.2, top = 1.55;
  const cw = (W - 2 * M - gap) / cols, rh = (H - top - 0.6 - gap * (rows - 1)) / rows;
  s.rules.forEach((text, i) => {
    const x = M + (i % cols) * (cw + gap), y = top + Math.floor(i / cols) * (rh + gap);
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: cw, h: rh, rectRadius: 0.1,
      fill: { color: CARD }, line: { color: LINE, width: 0.75 } });
    slide.addText(String(i + 1), { x: x + 0.2, y: y + 0.1, w: 0.5, h: rh - 0.2, fontFace: HEAD, fontSize: 28,
      bold: true, color: ACCENT, valign: "middle", margin: 0 });
    slide.addText(text, { x: x + 0.75, y: y + 0.1, w: cw - 0.95, h: rh - 0.2, fontFace: BODY, fontSize: 12,
      color: INK, valign: "middle", margin: 0 });
  });
  footer(slide, false);
}

const renderers = { cover: statement, close: statement, cards, type: typeSlide, rules };
for (const s of content.slides) {
  const slide = pres.addSlide();
  renderers[s.kind](slide, s);
  if (s.notes) slide.addNotes(s.notes);
}

pres.writeFile({ fileName: path.join(__dirname, "skill-evals.pptx") }).then(f => console.log("wrote", f));
