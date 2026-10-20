import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "/Users/knightnm/Documents/AutoScheduler-SL-CPU-Scheduler";
const skillDir = "/Users/knightnm/.codex/plugins/cache/openai-primary-runtime/presentations/26.1015.12040/skills/presentations";
const buildDir = path.join(workspaceDir, ".codex-pptx-build");
const previewDir = path.join(buildDir, "previews");
const finalPath = path.join(workspaceDir, "docs/presentation/AutoScheduler_Project_Review.pptx");
const runtimePython = "/Users/knightnm/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3";
process.env.RUNTIME_NODE_MODULES = "/Users/knightnm/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules";
const ganttPath = path.join(workspaceDir, "results/dynamic_v3_demo01/gantt.png");

const { applyPresentationChartFont, finalizePresentation } = await import(
  pathToFileURL(path.join(skillDir, "container_tools/artifact_tool_utils.mjs")).href
);

const W = 1280;
const H = 720;
const FONT = "Arial";
const C = {
  bg: "#F8F9FA",
  paper: "#FFFFFF",
  ink: "#111111",
  muted: "#555B63",
  light: "#D6DADE",
  lighter: "#EEF1F4",
  blue: "#1E5AA8",
  blueLight: "#E8F0FA",
  green: "#2C6E49",
  amber: "#A05A00",
};

await fs.mkdir(previewDir, { recursive: true });
await fs.mkdir(path.dirname(finalPath), { recursive: true });
const ganttBytes = await fs.readFile(ganttPath);

const deck = Presentation.create({ slideSize: { width: W, height: H } });

function box(slide, x, y, w, h, opts = {}) {
  return slide.shapes.add({
    geometry: opts.geometry ?? "rect",
    position: { left: x, top: y, width: w, height: h },
    fill: opts.fill ?? C.paper,
    line: opts.line ?? { style: "solid", fill: C.light, width: 1 },
    ...(opts.borderRadius ? { borderRadius: opts.borderRadius } : {}),
  });
}

function text(slide, value, x, y, w, h, opts = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    position: { left: x, top: y, width: w, height: h },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  shape.text = value;
  shape.text.style = {
    typeface: FONT,
    fontSize: opts.size ?? 20,
    color: opts.color ?? C.ink,
    bold: opts.bold ?? false,
    italic: opts.italic ?? false,
    ...(opts.align ? { alignment: opts.align } : {}),
  };
  return shape;
}

function line(slide, x, y, w, color = C.light, width = 1) {
  return slide.shapes.add({
    geometry: "line",
    position: { left: x, top: y, width: w, height: 0 },
    line: { style: "solid", fill: color, width },
  });
}

function vline(slide, x, y, h, color = C.light, width = 1) {
  return slide.shapes.add({
    geometry: "line",
    position: { left: x, top: y, width: 0, height: h },
    line: { style: "solid", fill: color, width },
  });
}

function baseSlide(titleValue, slideNo, section = "AUTOSCHEDULER") {
  const slide = deck.slides.add();
  slide.background.fill = C.bg;
  text(slide, section, 54, 24, 300, 22, { size: 12, bold: true, color: C.blue });
  text(slide, titleValue, 54, 50, 1120, 54, { size: 32, bold: true });
  line(slide, 54, 112, 1172, C.ink, 1.2);
  text(slide, String(slideNo).padStart(2, "0"), 1180, 678, 44, 18, {
    size: 11,
    bold: true,
    color: C.muted,
    align: "right",
  });
  return slide;
}

function citation(slide, refs) {
  text(slide, refs, 54, 681, 1080, 18, { size: 10, color: C.muted });
}

function setNotes(slide, body, sources = []) {
  const sourceText = sources.length ? `\n\nSources:\n${sources.join("\n")}` : "";
  slide.speakerNotes.text = `${body}${sourceText}`;
  slide.speakerNotes.setVisible(true);
}

function styleTable(table, rows, cols, opts = {}) {
  table.borders.assign({ style: "solid", fill: C.light, width: 1 });
  table.cells.block({ row: 0, column: 0, rowCount: 1, columnCount: cols }).assign({
    fill: C.ink,
    textStyle: { typeface: FONT, fontSize: opts.headerSize ?? 15, bold: true, color: C.paper },
    margins: { left: 6, right: 6, top: 4, bottom: 4 },
    anchor: "middle",
  });
  if (rows > 1) {
    table.cells.block({ row: 1, column: 0, rowCount: rows - 1, columnCount: cols }).assign({
      fill: C.paper,
      textStyle: { typeface: FONT, fontSize: opts.bodySize ?? 15, color: C.ink },
      margins: { left: 6, right: 6, top: 4, bottom: 4 },
      anchor: "middle",
    });
  }
}

// Slide 1
{
  const slide = deck.slides.add();
  slide.background.fill = C.paper;
  box(slide, 0, 0, 18, H, { fill: C.blue, line: { fill: C.blue, width: 0 } });
  text(slide, "AUTOSCHEDULER", 82, 92, 570, 34, { size: 15, bold: true, color: C.blue });
  text(slide, "Workload-aware CPU\nscheduling", 82, 160, 620, 152, { size: 50, bold: true });
  text(slide, "Machine-learning-guided CPU scheduling prototype", 84, 338, 650, 46, {
    size: 24,
    color: C.muted,
  });
  line(slide, 84, 418, 1110, C.light, 1.2);
  text(
    slide,
    "The system observes recent workload behavior and selects an existing scheduling policy. It keeps the policy implementations separate from the learning layer.",
    84,
    458,
    750,
    105,
    { size: 22, color: C.ink },
  );
  box(slide, 916, 146, 226, 226, {
    geometry: "ellipse",
    fill: C.blueLight,
    line: { style: "solid", fill: C.blue, width: 2 },
  });
  text(slide, "OBSERVE", 960, 210, 140, 30, { size: 17, bold: true, color: C.blue, align: "center" });
  text(slide, "SELECT", 960, 257, 140, 30, { size: 17, bold: true, color: C.blue, align: "center" });
  text(slide, "SCHEDULE", 950, 304, 160, 30, { size: 17, bold: true, color: C.blue, align: "center" });
  text(slide, "Academic project review", 84, 650, 300, 24, { size: 13, color: C.muted });
  setNotes(slide, "AutoScheduler studies whether a compact model can observe recent workload behavior and choose among existing CPU scheduling policies. The current result is a validated research prototype, not a deployed kernel scheduler.");
}

// Slide 2
{
  const slide = baseSlide("Problem and research gap", 2);
  text(slide, "One fixed policy cannot serve every workload equally well", 64, 136, 540, 36, { size: 22, bold: true });
  const workloadRows = [
    ["Interactive", "Needs a quick first response"],
    ["CPU-heavy", "Needs sustained processor service"],
    ["I/O-heavy", "Blocks and returns often"],
    ["Changing", "Needs stable policy transitions"],
  ];
  workloadRows.forEach(([name, detail], i) => {
    const y = 194 + i * 74;
    box(slide, 64, y, 18, 48, { fill: i === 3 ? C.blue : C.ink, line: { fill: "none", width: 0 } });
    text(slide, name, 100, y + 2, 150, 25, { size: 18, bold: true });
    text(slide, detail, 250, y + 2, 345, 44, { size: 17, color: C.muted });
  });
  vline(slide, 638, 150, 330, C.light, 1);
  box(slide, 665, 150, 525, 330, { fill: C.paper, line: { style: "solid", fill: C.light, width: 1.2 } });
  text(slide, "What earlier work established", 692, 176, 460, 30, { size: 21, bold: true, color: C.blue });
  text(slide, "Policy prediction and scheduler tuning can improve workload-specific outcomes [1], [4].", 692, 226, 452, 58, { size: 18 });
  text(slide, "Learned routers can choose among expert policies while stability filters limit rapid switching [2].", 692, 302, 452, 68, { size: 18 });
  text(slide, "Recent systems separate learned control from a small execution path [3], [6].", 692, 392, 452, 56, { size: 18 });
  box(slide, 64, 522, 1126, 112, { fill: C.blueLight, line: { style: "solid", fill: C.blue, width: 1.5 } });
  text(slide, "AutoScheduler contribution", 88, 558, 250, 26, { size: 18, bold: true, color: C.blue });
  text(slide, "A lightweight selector, observed-only features, guarded switching, and one shared simulator for all policy comparisons.", 354, 549, 792, 54, { size: 18 });
  citation(slide, "Prior work: [1] Biswas et al.  [2] Wang et al.  [3] Fu et al.  [4] Lee et al.  [6] Seo et al.");
  setNotes(slide, "Static schedulers make different trade-offs. AutoScheduler builds on policy prediction, learned routing, adaptive priority control, parameter tuning, and interpretable safety controls.", [
    "[1] https://doi.org/10.1109/STI59863.2023.10464816",
    "[2] https://arxiv.org/abs/2511.11628",
    "[3] https://www.usenix.org/system/files/atc24-fu.pdf",
    "[4] https://doi.org/10.3390/app12147072",
    "[6] https://doi.org/10.1109/VTC2025-SPRING65109.2025.11174897",
  ]);
}

// Slide 3
{
  const slide = baseSlide("Dataset sources and split discipline", 3);
  box(slide, 54, 142, 558, 364, { fill: C.paper, line: { style: "solid", fill: C.ink, width: 1.1 } });
  text(slide, "CAPTURED LINUX TRACES", 78, 164, 300, 22, { size: 13, bold: true, color: C.blue });
  text(slide, "9 accepted traces", 78, 200, 300, 36, { size: 27, bold: true });
  text(slide, "CPU and compression scenarios recorded on all CPUs in a Linux VM.", 78, 244, 480, 54, { size: 18, color: C.muted });
  text(slide, "2,590,010", 78, 322, 160, 34, { size: 26, bold: true, color: C.blue });
  text(slide, "scheduler events", 78, 355, 160, 24, { size: 14, color: C.muted });
  text(slide, "25", 270, 322, 100, 34, { size: 26, bold: true, color: C.blue });
  text(slide, "processes", 270, 355, 100, 24, { size: 14, color: C.muted });
  text(slide, "1,053", 398, 322, 110, 34, { size: 26, bold: true, color: C.blue });
  text(slide, "state snapshots", 398, 355, 140, 24, { size: 14, color: C.muted });
  text(slide, "5,265 action-cost rows", 78, 405, 310, 30, { size: 20, bold: true });
  text(slide, "Cleaned and anonymized. Incomplete traces rejected. Group split: 6 train, 1 validation, 2 test.", 78, 447, 490, 50, { size: 16, color: C.muted });

  box(slide, 642, 142, 584, 364, { fill: C.paper, line: { style: "solid", fill: C.ink, width: 1.1 } });
  text(slide, "CONTROLLED DYNAMIC V3 CORPUS", 668, 164, 360, 22, { size: 13, bold: true, color: C.blue });
  text(slide, "144 grouped development traces", 668, 200, 510, 36, { size: 26, bold: true });
  text(slide, "Generated by the project simulator across controlled workload families and changing phases.", 668, 244, 500, 54, { size: 18, color: C.muted });
  text(slide, "10,387", 668, 322, 150, 34, { size: 26, bold: true, color: C.blue });
  text(slide, "decision rows", 668, 355, 150, 24, { size: 14, color: C.muted });
  text(slide, "100 / 22 / 22", 850, 322, 200, 34, { size: 26, bold: true, color: C.blue });
  text(slide, "trace-group split", 850, 355, 180, 24, { size: 14, color: C.muted });
  text(slide, "60 separate validation workloads", 668, 405, 410, 30, { size: 20, bold: true });
  text(slide, "Used to compare model families and exercise changing-workload routing under controlled conditions.", 668, 447, 500, 50, { size: 16, color: C.muted });

  const stageX = [90, 338, 586, 834, 1082];
  const stageNames = ["Capture", "Clean", "Extract", "Split", "Evaluate"];
  const stageDetails = ["all CPUs", "remove identity", "past events", "whole traces", "locked groups"];
  const stageShapes = stageX.map((x, i) => {
    const s = box(slide, x - 54, 558, 108, 62, { fill: i === 4 ? C.blueLight : C.paper, line: { style: "solid", fill: i === 4 ? C.blue : C.light, width: 1.2 } });
    text(slide, stageNames[i], x - 45, 568, 90, 22, { size: 15, bold: true, align: "center", color: i === 4 ? C.blue : C.ink });
    text(slide, stageDetails[i], x - 48, 592, 96, 18, { size: 11, color: C.muted, align: "center" });
    return s;
  });
  for (let i = 0; i < stageShapes.length - 1; i += 1) {
    slide.shapes.connect(stageShapes[i], stageShapes[i + 1], {
      kind: "straight",
      fromSide: "right",
      toSide: "left",
      line: { style: "solid", fill: C.muted, width: 1.5 },
      tail: { type: "triangle", width: "sm", length: "sm" },
    });
  }
  setNotes(slide, "The project uses two evidence tracks. Captured Linux traces validate the real trace pipeline. The larger controlled corpus supports model-family comparison and the Dynamic V3 routing demonstration. Whole trace groups remain in one split to prevent leakage.", [
    path.join(workspaceDir, "data/processed/linux/full-002/cleaned.jsonl"),
    path.join(workspaceDir, "data/processed/linux/full-002/observed_features.csv"),
    path.join(workspaceDir, "data/processed/linux/full-002/action_costs.csv"),
    path.join(workspaceDir, "artifacts/dynamic_v3_demo01/training.csv"),
    path.join(workspaceDir, "artifacts/dynamic_v3_demo01/split.json"),
  ]);
}

// Slide 4
{
  const slide = baseSlide("Observed-only feature extraction", 4);
  text(slide, "Linux observation window", 64, 140, 240, 22, { size: 14, bold: true, color: C.blue });
  text(slide, "2 seconds", 64, 166, 220, 42, { size: 31, bold: true });
  text(slide, "Decision interval", 300, 140, 200, 22, { size: 14, bold: true, color: C.blue });
  text(slide, "500 ms", 300, 166, 180, 42, { size: 31, bold: true });
  line(slide, 64, 222, 500, C.light, 1);

  const groups = [
    ["QUEUE STATE", "arrivals_seen\nready_count\nblocked_count\nrunning_count"],
    ["DELAY AND SERVICE", "wait_mean_ms\nwait_p95_ms\nobserved_service_mean_ms\nobserved_service_variance_ms2"],
    ["BURST AND I/O HISTORY", "completed_burst_mean_ms\ncompleted_burst_variance_ms2\nio_returns\nwakeups"],
    ["SCHEDULING CONTEXT", "priority_mean\npriority_variance\ncontext_switches\ncpu_busy_fraction"],
  ];
  groups.forEach(([heading, values], i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const x = 64 + col * 292;
    const y = 246 + row * 184;
    text(slide, heading, x, y, 260, 22, { size: 13, bold: true, color: C.blue });
    text(slide, values, x, y + 30, 270, 124, { size: 17, color: C.ink });
  });

  box(slide, 670, 144, 520, 438, { fill: C.paper, line: { style: "solid", fill: C.ink, width: 1.1 } });
  text(slide, "Decision-time boundary", 700, 172, 460, 30, { size: 23, bold: true });
  line(slide, 704, 246, 422, C.blue, 3);
  text(slide, "PAST EVENTS", 704, 216, 170, 22, { size: 13, bold: true, color: C.blue });
  text(slide, "DECISION", 1018, 216, 110, 22, { size: 13, bold: true, color: C.blue, align: "right" });
  text(slide, "Every feature comes from events observed before this line.", 700, 274, 438, 54, { size: 20, bold: true });
  text(slide, "Allowed", 700, 350, 140, 25, { size: 17, bold: true, color: C.green });
  text(slide, "Queue size, waiting history, completed service, I/O returns, priority, wakeups, and prior switches.", 700, 380, 438, 74, { size: 17 });
  text(slide, "Excluded", 700, 474, 140, 25, { size: 17, bold: true, color: C.amber });
  text(slide, "Future arrivals, declared total work, true remaining burst, later outcomes, and oracle identity.", 700, 504, 438, 62, { size: 17 });
  box(slide, 64, 618, 1126, 42, { fill: C.blueLight, line: { style: "solid", fill: C.blue, width: 1 } });
  text(slide, "Why these features: process history can predict scheduler behavior, while recent queue and service history supports adaptive control [3], [5].", 82, 628, 1090, 24, { size: 16 });
  citation(slide, "Feature precedent: [3] ALPS  [5] Negi and Pusukuri");
  setNotes(slide, "Feature extraction uses only the information available at each decision time. The 16 features summarize queue state, delays, observed service, completed burst behavior, I/O activity, priority, context switches, wakeups, and CPU busy fraction.", [
    "[3] https://www.usenix.org/system/files/atc24-fu.pdf",
    "[5] https://doi.org/10.1109/TENCON.2005.300837",
    path.join(workspaceDir, "configs/real_desktop_ml.json"),
  ]);
}

// Slide 5
{
  const slide = baseSlide("System modules and data flow", 5);
  const modules = [
    ["1", "Trace and workload input", "Linux scheduler events and controlled workload traces.", "Raw behavior enters the system."],
    ["2", "Data preparation", "Cleaning, replay, feature extraction, and grouped splitting.", "Past events become safe model inputs."],
    ["3", "Model comparison", "Action-cost labels compare five candidate model families.", "The lowest-cost validated model is frozen."],
    ["4", "Dynamic V3 router", "Confidence, dwell, and safe-boundary checks control switching.", "The model suggests. Guardrails decide."],
    ["5", "Shared simulator", "Policies run through one engine with metrics, logs, and a Gantt chart.", "Every scheduler faces the same test."],
  ];
  const xs = [44, 292, 540, 788, 1036];
  const shapes = [];
  modules.forEach(([n, titleValue, tech, plain], i) => {
    const s = box(slide, xs[i], 174, 200, 330, {
      fill: i === 3 ? C.blueLight : C.paper,
      line: { style: "solid", fill: i === 3 ? C.blue : C.ink, width: i === 3 ? 1.8 : 1.1 },
    });
    shapes.push(s);
    box(slide, xs[i] + 18, 194, 36, 36, { geometry: "ellipse", fill: i === 3 ? C.blue : C.ink, line: { fill: "none", width: 0 } });
    text(slide, n, xs[i] + 18, 201, 36, 20, { size: 14, bold: true, color: C.paper, align: "center" });
    text(slide, titleValue, xs[i] + 18, 248, 164, 64, { size: 20, bold: true });
    line(slide, xs[i] + 18, 326, 164, C.light, 1);
    text(slide, tech, xs[i] + 18, 348, 164, 82, { size: 16, color: C.ink });
    text(slide, plain, xs[i] + 18, 444, 164, 48, { size: 14, italic: true, color: C.muted });
  });
  for (let i = 0; i < shapes.length - 1; i += 1) {
    slide.shapes.connect(shapes[i], shapes[i + 1], {
      kind: "straight",
      fromSide: "right",
      toSide: "left",
      line: { style: "solid", fill: C.blue, width: 2 },
      tail: { type: "triangle", width: "sm", length: "sm" },
    });
  }
  box(slide, 138, 546, 1004, 80, { fill: C.paper, line: { style: "dashed", fill: C.muted, width: 1.2 } });
  text(slide, "Frozen research contract", 160, 562, 230, 24, { size: 17, bold: true, color: C.blue });
  text(slide, "Fixed policy set, score weights, feature rules, seeds, latency gate, and evidence boundary.", 404, 561, 704, 44, { size: 17 });
  citation(slide, "Architecture precedents: [1] policy selection  [2] learned routing  [3] separated learning and execution");
  setNotes(slide, "The architecture has five modules. The data module creates safe observed-state rows. The comparison module freezes a model. Dynamic V3 applies confidence and dwell safeguards. Every policy executes through the same simulator and reporting path.", [
    "[1] https://doi.org/10.1109/STI59863.2023.10464816",
    "[2] https://arxiv.org/abs/2511.11628",
    "[3] https://www.usenix.org/system/files/atc24-fu.pdf",
  ]);
}

// Slide 6
{
  const slide = baseSlide("Five model families under one experiment contract", 6);
  const models = [
    ["Dummy", "Minimum baseline", "Repeats a simple reference prediction."],
    ["Ridge", "Fast linear estimator", "Fits one regularized linear cost function."],
    ["Decision Tree", "Interpretable nonlinear rules", "Splits observed states into readable decisions."],
    ["Random Forest", "Averaged tree ensemble", "Reduces single-tree variance by voting across trees."],
    ["Histogram Gradient Boosting", "Sequential tree ensemble", "Adds compact trees that correct earlier errors."],
  ];
  models.forEach(([name, label, detail], i) => {
    const y = 144 + i * 94;
    text(slide, String(i + 1).padStart(2, "0"), 64, y + 4, 40, 28, { size: 15, bold: true, color: C.blue });
    text(slide, name, 116, y, 260, 28, { size: 21, bold: true });
    text(slide, label, 390, y, 260, 26, { size: 18, bold: true, color: C.blue });
    text(slide, detail, 664, y, 500, 48, { size: 17, color: C.muted });
    line(slide, 116, y + 64, 1048, C.light, 1);
  });
  box(slide, 64, 624, 1100, 42, { fill: C.blueLight, line: { style: "solid", fill: C.blue, width: 1 } });
  text(slide, "Same 16 features, grouped split, action-cost targets, and tuning budget for every model.", 82, 633, 1060, 24, { size: 17, bold: true });
  citation(slide, "Methods: [7] scikit-learn  [8] Ridge  [9] Trees  [10] Random Forest  [11] Gradient Boosting  Scheduling use: [1], [5]");
  setNotes(slide, "The bake-off holds the data, features, group split, target, and tuning budget constant. This isolates model-family behavior from dataset changes.", [
    "[7] F. Pedregosa et al., Journal of Machine Learning Research, 2011.",
    "[8] https://doi.org/10.1080/00401706.1970.10488634",
    "[9] https://doi.org/10.1007/BF00116251",
    "[10] https://doi.org/10.1023/A:1010933404324",
    "[11] https://doi.org/10.1214/aos/1013203451",
    "[1] https://doi.org/10.1109/STI59863.2023.10464816",
    "[5] https://doi.org/10.1109/TENCON.2005.300837",
  ]);
}

// Slide 7
{
  const slide = baseSlide("Model comparison: scheduling outcome decides the prototype", 7);
  const rows = [
    ["Model", "Val. acc.", "Test acc.", "Val. score", "Val. regret", "Test regret"],
    ["Dummy", "21.27%", "36.77%", "0.162973", "0.008352", "0.011888"],
    ["Ridge", "27.53%", "35.35%", "0.143103", "0.005457", "0.005816"],
    ["Decision Tree", "43.46%", "42.23%", "0.120669", "0.004216", "0.004394"],
    ["Random Forest", "44.82%", "43.18%", "0.126164", "0.003888", "0.004612"],
    ["Histogram Gradient Boosting", "27.65%", "44.84%", "0.140503", "0.004523", "0.004257"],
  ];
  const table = slide.tables.add({
    rows: 6,
    columns: 6,
    left: 54,
    top: 148,
    width: 790,
    height: 318,
    columnWidths: [214, 92, 92, 128, 132, 132],
    values: rows,
  });
  styleTable(table, 6, 6, { headerSize: 14, bodySize: 14 });
  table.cells.block({ row: 3, column: 0, rowCount: 1, columnCount: 6 }).assign({ fill: C.blueLight });
  table.getCell(3, 0).text.style = { typeface: FONT, fontSize: 14, bold: true, color: C.blue };
  table.getCell(3, 3).text.style = { typeface: FONT, fontSize: 14, bold: true, color: C.blue };

  text(slide, "Validation score × 1,000  |  lower is better", 880, 150, 330, 26, { size: 17, bold: true });
  const chart = slide.charts.add("bar", {
    position: { left: 874, top: 188, width: 340, height: 278 },
    categories: ["Dummy", "Ridge", "Tree", "Forest", "HGB"],
    series: [{ name: "Score", values: [162.973, 143.103, 120.669, 126.164, 140.503], fill: C.blue }],
    hasLegend: false,
    dataLabels: { showValue: false },
    yAxis: {
      minimumScale: 100,
      maximumScale: 170,
      majorUnit: 20,
      numberFormat: "0",
      majorGridlines: { style: "solid", fill: C.lighter, width: 1 },
    },
  });
  applyPresentationChartFont(chart, { fontFamily: FONT });

  text(slide, "Accuracy means agreement with the deterministic lowest-cost action. Raw accuracy did not choose the winner.", 64, 492, 760, 50, { size: 17, color: C.muted });
  box(slide, 54, 548, 1160, 106, { fill: C.blueLight, line: { style: "solid", fill: C.blue, width: 1.2 } });
  text(slide, "Prototype choice", 74, 565, 180, 24, { size: 17, bold: true, color: C.blue });
  text(slide, "Decision Tree produced the lowest validation scheduling score: 0.120669.", 268, 563, 900, 30, { size: 17, bold: true });
  text(slide, "Captured traces: Ridge and Decision Tree tied on cost and action agreement. Decision Tree had lower P99 latency, while the configured simplicity rule selected Ridge.", 74, 611, 1100, 30, { size: 14, color: C.ink });
  setNotes(slide, "The controlled grouped split shows that action accuracy and scheduling outcome can disagree. Decision Tree has the lowest validation scheduling score, so the prototype freezes it. In the separate captured-trace bake-off, Ridge and Decision Tree tie on realized cost and action agreement. The configured simplicity rule selects Ridge, even though the tree has lower measured P99 inference time.", [
    path.join(workspaceDir, "results/dynamic_v3_demo01/REPORT.md"),
    path.join(workspaceDir, "results/dynamic_v3_demo01/model_family_bakeoff.csv"),
    path.join(workspaceDir, "results/real_desktop_ml/decision-tree-demo/prototype_comparison_report.md"),
  ]);
}

// Slide 8
{
  const slide = baseSlide("Classifier tree and policy-cost tree answer different questions", 8);
  const values = [
    ["Metric", "Classifier tree", "Policy-cost tree"],
    ["Validation action accuracy", "47.67%", "36.06%"],
    ["Test action accuracy", "40.81%", "46.62%"],
    ["Test action regret", "0.006111", "0.003887"],
    ["Validation scheduling score", "0.119128", "0.128198"],
    ["P95 response", "31.593", "73.526"],
    ["Starvation count", "15.317", "14.500"],
  ];
  const table = slide.tables.add({
    rows: 7,
    columns: 3,
    left: 72,
    top: 158,
    width: 760,
    height: 392,
    columnWidths: [360, 200, 200],
    values,
  });
  styleTable(table, 7, 3, { headerSize: 16, bodySize: 16 });
  table.cells.block({ row: 4, column: 1, rowCount: 1, columnCount: 1 }).assign({ fill: C.blueLight, textStyle: { typeface: FONT, fontSize: 16, bold: true, color: C.blue } });
  table.cells.block({ row: 5, column: 1, rowCount: 1, columnCount: 1 }).assign({ fill: C.blueLight, textStyle: { typeface: FONT, fontSize: 16, bold: true, color: C.blue } });
  table.cells.block({ row: 3, column: 2, rowCount: 1, columnCount: 1 }).assign({ fill: C.lighter, textStyle: { typeface: FONT, fontSize: 16, bold: true, color: C.ink } });
  table.cells.block({ row: 6, column: 2, rowCount: 1, columnCount: 1 }).assign({ fill: C.lighter, textStyle: { typeface: FONT, fontSize: 16, bold: true, color: C.ink } });

  box(slide, 882, 158, 322, 176, { fill: C.paper, line: { style: "solid", fill: C.ink, width: 1.1 } });
  text(slide, "Classifier tree", 908, 182, 270, 28, { size: 21, bold: true, color: C.blue });
  text(slide, "Directly proposes one scheduler from the observed state.", 908, 226, 268, 70, { size: 18 });
  box(slide, 882, 358, 322, 176, { fill: C.paper, line: { style: "solid", fill: C.ink, width: 1.1 } });
  text(slide, "Policy-cost tree", 908, 382, 270, 28, { size: 21, bold: true });
  text(slide, "Predicts every scheduler's cost, then selects the minimum estimate.", 908, 426, 268, 72, { size: 18 });
  box(slide, 72, 588, 1132, 66, { fill: C.blueLight, line: { style: "solid", fill: C.blue, width: 1.2 } });
  text(slide, "Frozen for the demonstration", 94, 603, 292, 25, { size: 18, bold: true, color: C.blue });
  text(slide, "Classifier tree, because its validation scheduling score and response time were better. The policy-cost tree remains an evaluated alternative.", 392, 598, 784, 46, { size: 17 });
  setNotes(slide, "The classifier optimizes direct policy choice. The policy-cost tree estimates each candidate action. The classifier is frozen for the demonstration because it produced the lower validation scheduling score and much lower P95 response, even though the policy-cost tree had lower test action regret and fewer starvation events.", [
    path.join(workspaceDir, "results/dynamic_v3_demo01/tree_variant_comparison.json"),
  ]);
}

// Slide 9
{
  const slide = baseSlide("End-to-end Dynamic V3 demonstration", 9);
  slide.images.add({
    blob: new Uint8Array(ganttBytes.buffer, ganttBytes.byteOffset, ganttBytes.byteLength),
    contentType: "image/png",
    alt: "Dynamic V3 CPU execution timeline for the unseen changing workload",
    fit: "contain",
    position: { left: 54, top: 146, width: 760, height: 458 },
  });
  box(slide, 844, 146, 370, 458, { fill: C.paper, line: { style: "solid", fill: C.ink, width: 1.1 } });
  text(slide, "Router loop", 870, 168, 280, 28, { size: 22, bold: true, color: C.blue });
  const flow = [
    ["1", "Observe every 10 ticks"],
    ["2", "Model proposes a policy"],
    ["3", "Confidence and dwell checks"],
    ["4", "Switch at a safe boundary"],
  ];
  flow.forEach(([n, label], i) => {
    const y = 216 + i * 56;
    box(slide, 870, y, 28, 28, { geometry: "ellipse", fill: C.blue, line: { fill: "none", width: 0 } });
    text(slide, n, 870, y + 5, 28, 18, { size: 12, bold: true, color: C.paper, align: "center" });
    text(slide, label, 914, y + 2, 260, 32, { size: 17 });
  });
  line(slide, 870, 454, 316, C.light, 1);
  text(slide, "52 reviews", 870, 474, 140, 26, { size: 20, bold: true });
  text(slide, "8 accepted switches", 1020, 474, 170, 26, { size: 20, bold: true });
  text(slide, "Initial: MLFQ", 870, 520, 140, 24, { size: 16, color: C.muted });
  text(slide, "Final: Priority", 1020, 520, 160, 24, { size: 16, color: C.muted });
  text(slide, "Decision P99", 870, 558, 140, 22, { size: 14, bold: true, color: C.blue });
  text(slide, "0.456 ms", 1020, 552, 160, 32, { size: 25, bold: true, color: C.blue });
  box(slide, 54, 626, 1160, 40, { fill: C.blueLight, line: { style: "solid", fill: C.blue, width: 1 } });
  text(slide, "Result: the full model-selection and guarded-routing workflow runs within the prototype latency target. This does not establish kernel performance or universal policy superiority.", 70, 635, 1120, 22, { size: 14 });
  setNotes(slide, "This demonstration uses an unseen changing workload with CPU-intensive, interactive, and batch phases. The router reviews the observed state every 10 ticks. Confidence, a 20-tick minimum dwell, and safe dispatch boundaries limit switching. The result proves the prototype control flow and measured decision latency for this run. It does not prove Linux kernel scheduling performance or superiority over every fixed scheduler.", [
    path.join(workspaceDir, "results/dynamic_v3_demo01/summary.json"),
    path.join(workspaceDir, "results/dynamic_v3_demo01/decision_log.csv"),
    ganttPath,
  ]);
}

// Slide 10
{
  const slide = baseSlide("References", 10);
  const leftRefs = [
    "[1] S. Biswas et al., “A Machine Learning Approach for Predicting Efficient CPU Scheduling Algorithm,” STI, 2023, doi: 10.1109/STI59863.2023.10464816.",
    "[2] X. Wang et al., “Mixture-of-Schedulers: An Adaptive Scheduling Agent as a Learned Router for Expert Policies,” arXiv:2511.11628, 2025.",
    "[3] Y. Fu et al., “ALPS: An Adaptive Learning, Priority OS Scheduler for Serverless Functions,” USENIX ATC, 2024.",
    "[4] H. Lee, S. Jung, and H. Jo, “STUN: Reinforcement-Learning-Based Optimization of Kernel Scheduler Parameters,” Applied Sciences, 2022.",
    "[5] A. Negi and K. K. Pusukuri, “Applying Machine Learning Techniques to Improve Linux Process Scheduling,” TENCON, 2005.",
    "[6] D. Seo et al., “SCHED: Safe CPU Scheduling Framework with Reinforcement Learning and Decision Trees,” VTC-Spring, 2025.",
  ];
  const rightRefs = [
    "[7] F. Pedregosa et al., “Scikit-learn: Machine Learning in Python,” Journal of Machine Learning Research, vol. 12, pp. 2825–2830, 2011.",
    "[8] A. E. Hoerl and R. W. Kennard, “Ridge Regression: Biased Estimation for Nonorthogonal Problems,” Technometrics, vol. 12, no. 1, pp. 55–67, 1970.",
    "[9] J. R. Quinlan, “Induction of Decision Trees,” Machine Learning, vol. 1, pp. 81–106, 1986.",
    "[10] L. Breiman, “Random Forests,” Machine Learning, vol. 45, pp. 5–32, 2001.",
    "[11] J. H. Friedman, “Greedy Function Approximation: A Gradient Boosting Machine,” Annals of Statistics, vol. 29, no. 5, pp. 1189–1232, 2001.",
  ];
  text(slide, "SCHEDULING AND SYSTEMS", 60, 142, 480, 22, { size: 13, bold: true, color: C.blue });
  text(slide, "MODEL FOUNDATIONS", 666, 142, 480, 22, { size: 13, bold: true, color: C.blue });
  leftRefs.forEach((ref, i) => text(slide, ref, 60, 178 + i * 78, 554, 68, { size: 14 }));
  rightRefs.forEach((ref, i) => text(slide, ref, 666, 178 + i * 92, 550, 82, { size: 14 }));
  vline(slide, 640, 150, 480, C.light, 1);
  setNotes(slide, "IEEE-style bibliography for all numbered citations used in the deck.", [
    "/Users/knightnm/Documents/OS_Project/AutoSchedulerPapers.md",
  ]);
}

for (let i = 0; i < deck.slides.items.length; i += 1) {
  const slide = deck.slides.items[i];
  const png = await deck.export({ slide, format: "png", scale: 1 });
  await fs.writeFile(path.join(previewDir, `slide-${String(i + 1).padStart(2, "0")}.png`), new Uint8Array(await png.arrayBuffer()));
}
const montage = await deck.export({ format: "webp", montage: true });
await fs.writeFile(path.join(buildDir, "montage.webp"), new Uint8Array(await montage.arrayBuffer()));

const stagingDir = path.join(workspaceDir, ".codex-finalizer");
await fs.mkdir(stagingDir, { recursive: true });
const candidatePath = path.join(stagingDir, "autoscheduler-project-review-candidate.pptx");
await (await PresentationFile.exportPptx(deck)).save(candidatePath);

const requirements = {
  explicitTotalSlideCount: 10,
  requiredNativeTableOwnerSlides: [7, 8],
  requiredNativeChartOwnerSlides: [7],
  requiredEmbeddedWorkbookChartOwnerSlides: [],
  materializeLiteralChartWorkbooks: true,
  nativeChartTargetApplication: "powerpoint",
};

const result = await finalizePresentation({
  ...requirements,
  workspaceDir,
  candidatePath,
  finalPath,
  pythonExecutable: runtimePython,
  integrityValidatorPath: path.join(skillDir, "container_tools/inspect_presentation_package_integrity.py"),
  layoutValidatorPath: path.join(skillDir, "container_tools/inspect_presentation_layout_geometry.py"),
  layoutArgs: [
    "--expected-slide-size-emu", "12192000,6858000",
    "--validate-heading-fit",
    "--require-native-table-slide", "7",
    "--require-native-table-slide", "8",
  ],
  requiredNativeTableOwnerSlides: requirements.requiredNativeTableOwnerSlides,
  requiredNativeChartOwnerSlides: requirements.requiredNativeChartOwnerSlides,
  materializeLiteralChartWorkbooks: true,
  nativeChartTargetApplication: "powerpoint",
  fontPolicy: { basis: "design", families: [FONT] },
  verifyArtifactToolImport: true,
  receiptPath: path.join(stagingDir, "AutoScheduler_Project_Review_release.validation.json"),
});

console.log(JSON.stringify({ finalPath, previews: previewDir, montage: path.join(buildDir, "montage.webp"), validation: result }, null, 2));
