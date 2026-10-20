import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "/Users/knightnm/Documents/AutoScheduler-SL-CPU-Scheduler";
const skillDir = "/Users/knightnm/.codex/plugins/cache/openai-primary-runtime/presentations/26.1015.12040/skills/presentations";
const buildDir = path.join(workspaceDir, ".codex-pptx-build/simple-bw");
const previewDir = path.join(buildDir, "previews");
const finalPath = path.join(workspaceDir, "docs/presentation/AutoScheduler_Project_Review_Simple_BW.pptx");
const runtimePython = "/Users/knightnm/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3";
const runtimeModules = "/Users/knightnm/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules";
const ganttPath = path.join(workspaceDir, "results/dynamic_v3_demo01/gantt.png");
const ganttBwPath = path.join(buildDir, "gantt-bw.png");
process.env.RUNTIME_NODE_MODULES = runtimeModules;

const { finalizePresentation, makeNativeBulletParagraphs } = await import(
  pathToFileURL(path.join(skillDir, "container_tools/artifact_tool_utils.mjs")).href
);

const W = 1280;
const H = 720;
const FONT = "Arial";
const BLACK = "#000000";
const WHITE = "#FFFFFF";
const deck = Presentation.create({ slideSize: { width: W, height: H } });
await fs.mkdir(previewDir, { recursive: true });
await fs.mkdir(path.dirname(finalPath), { recursive: true });
const ganttBytes = await fs.readFile(ganttBwPath);

function addText(slide, value, left, top, width, height, options = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    position: { left, top, width, height },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  shape.text = value;
  shape.text.style = {
    typeface: FONT,
    fontSize: options.size ?? 20,
    color: options.color ?? BLACK,
    bold: options.bold ?? false,
    italic: options.italic ?? false,
    ...(options.align ? { alignment: options.align } : {}),
  };
  return shape;
}

function addBullets(slide, items, left, top, width, height, options = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    position: { left, top, width, height },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  shape.text = makeNativeBulletParagraphs(items, {
    marginLeftPoints: options.marginLeftPoints ?? 18,
    hangingPoints: options.hangingPoints ?? 9,
    spaceAfterPoints: options.spaceAfterPoints ?? 10,
  });
  shape.text.style = {
    typeface: FONT,
    fontSize: options.size ?? 20,
    color: BLACK,
    autoFit: "none",
  };
  return shape;
}

function baseSlide(title, slideNo) {
  const slide = deck.slides.add();
  slide.background.fill = WHITE;
  addText(slide, title, 60, 44, 1140, 54, { size: 34, bold: true });
  addText(slide, String(slideNo), 1170, 682, 40, 18, { size: 11, align: "right" });
  return slide;
}

function citation(slide, value) {
  addText(slide, value, 60, 678, 1080, 20, { size: 10 });
}

function setNotes(slide, body, sources = []) {
  slide.speakerNotes.text = `${body}${sources.length ? `\n\nSources:\n${sources.join("\n")}` : ""}`;
  slide.speakerNotes.setVisible(true);
}

function styleTable(table, rows, columns, bodySize = 15) {
  table.borders.assign({ style: "solid", fill: BLACK, width: 1 });
  table.cells.block({ row: 0, column: 0, rowCount: 1, columnCount: columns }).assign({
    fill: BLACK,
    textStyle: { typeface: FONT, fontSize: bodySize, bold: true, color: WHITE },
    margins: { left: 6, right: 6, top: 4, bottom: 4 },
    anchor: "middle",
  });
  table.cells.block({ row: 1, column: 0, rowCount: rows - 1, columnCount: columns }).assign({
    fill: WHITE,
    textStyle: { typeface: FONT, fontSize: bodySize, color: BLACK },
    margins: { left: 6, right: 6, top: 4, bottom: 4 },
    anchor: "middle",
  });
}

// 1. Title
{
  const slide = deck.slides.add();
  slide.background.fill = WHITE;
  addText(slide, "AutoScheduler", 86, 168, 900, 72, { size: 52, bold: true });
  addText(slide, "Machine-learning-guided CPU scheduling prototype", 90, 258, 900, 40, { size: 25 });
  addBullets(slide, [
    "Observes recent workload behavior.",
    "Selects an existing CPU scheduling policy.",
    "Keeps the learning layer separate from scheduler implementations.",
  ], 90, 360, 930, 170, { size: 22, spaceAfterPoints: 12 });
  addText(slide, "Academic project review", 90, 640, 300, 24, { size: 14 });
  setNotes(slide, "AutoScheduler studies whether a compact model can observe recent workload behavior and choose among existing CPU scheduling policies. The current result is a validated research prototype, not a deployed kernel scheduler.");
}

// 2. Problem
{
  const slide = baseSlide("Problem and research gap", 2);
  addText(slide, "Why one fixed scheduler is insufficient", 72, 132, 520, 32, { size: 22, bold: true });
  addBullets(slide, [
    "Interactive workloads need a quick first response.",
    "CPU-heavy workloads need sustained processor service.",
    "I/O-heavy workloads block and return frequently.",
    "Changing workloads need stable policy transitions.",
  ], 72, 180, 520, 260, { size: 20 });
  addText(slide, "What earlier work established", 664, 132, 520, 32, { size: 22, bold: true });
  addBullets(slide, [
    "Policy prediction and scheduler tuning can improve workload-specific outcomes [1], [4].",
    "Learned routers can choose among expert policies while stability filters reduce rapid switching [2].",
    "Recent systems separate learned control from a small execution path [3], [6].",
  ], 664, 180, 520, 248, { size: 20 });
  addText(slide, "AutoScheduler contribution", 72, 488, 1110, 30, { size: 22, bold: true });
  addBullets(slide, [
    "Lightweight model selection using observed-only features.",
    "Guarded switching through confidence, dwell, and safe-boundary checks.",
    "One shared simulator for comparable scheduler results.",
  ], 72, 532, 1110, 120, { size: 19, spaceAfterPoints: 7 });
  citation(slide, "[1] Biswas et al.  [2] Wang et al.  [3] Fu et al.  [4] Lee et al.  [6] Seo et al.");
  setNotes(slide, "Static schedulers make different trade-offs. AutoScheduler builds on policy prediction, learned routing, adaptive priority control, parameter tuning, and interpretable safety controls.", [
    "[1] https://doi.org/10.1109/STI59863.2023.10464816",
    "[2] https://arxiv.org/abs/2511.11628",
    "[3] https://www.usenix.org/system/files/atc24-fu.pdf",
    "[4] https://doi.org/10.3390/app12147072",
    "[6] https://doi.org/10.1109/VTC2025-SPRING65109.2025.11174897",
  ]);
}

// 3. Data
{
  const slide = baseSlide("Dataset sources", 3);
  addText(slide, "Captured Linux traces", 72, 132, 520, 32, { size: 23, bold: true });
  addBullets(slide, [
    "Nine accepted all-CPU traces from a Linux VM.",
    "CPU and compression workload scenarios.",
    "2,590,010 scheduler events across 25 processes.",
    "1,053 observed-state snapshots and 5,265 action-cost rows.",
    "Cleaning removed identifying details and rejected incomplete traces.",
    "Whole-trace allocation: 6 train, 1 validation, 2 test.",
  ], 72, 178, 520, 390, { size: 19, spaceAfterPoints: 8 });
  addText(slide, "Controlled Dynamic V3 corpus", 664, 132, 520, 32, { size: 23, bold: true });
  addBullets(slide, [
    "144 grouped development traces from the project simulator.",
    "Controlled workload families and changing workload phases.",
    "10,387 decision rows.",
    "Trace-group allocation: 100 train, 22 validation, 22 test.",
    "60 separate workloads for validation of scheduling outcomes.",
  ], 664, 178, 520, 338, { size: 19, spaceAfterPoints: 8 });
  addText(slide, "Split rule", 664, 536, 520, 28, { size: 21, bold: true });
  addBullets(slide, ["Related traces stay in one split to prevent information leakage."], 664, 576, 520, 66, { size: 19 });
  setNotes(slide, "The project uses two evidence tracks. Captured Linux traces validate the real trace pipeline. The larger controlled corpus supports model-family comparison and the Dynamic V3 routing demonstration. Whole trace groups remain in one split to prevent leakage.", [
    path.join(workspaceDir, "data/processed/linux/full-002/cleaned.jsonl"),
    path.join(workspaceDir, "data/processed/linux/full-002/observed_features.csv"),
    path.join(workspaceDir, "data/processed/linux/full-002/action_costs.csv"),
    path.join(workspaceDir, "artifacts/dynamic_v3_demo01/training.csv"),
    path.join(workspaceDir, "artifacts/dynamic_v3_demo01/split.json"),
  ]);
}

// 4. Features
{
  const slide = baseSlide("Observed-only feature extraction", 4);
  addText(slide, "Linux timing", 72, 128, 330, 30, { size: 22, bold: true });
  addBullets(slide, ["Two-second observation window.", "Decision every 500 ms."], 72, 170, 420, 108, { size: 20 });
  addText(slide, "The 16 features", 72, 296, 330, 30, { size: 22, bold: true });
  addBullets(slide, [
    "Queue state: arrivals, ready, blocked, and running counts.",
    "Delay and service: mean wait, P95 wait, service mean, and service variance.",
    "CPU and I/O history: completed-burst mean, completed-burst variance, I/O returns, and wakeups.",
    "Scheduling context: priority mean, priority variance, context switches, and CPU busy fraction.",
  ], 72, 338, 548, 300, { size: 18, spaceAfterPoints: 8 });
  addText(slide, "Decision-time rule", 668, 128, 520, 30, { size: 22, bold: true });
  addBullets(slide, [
    "Every feature uses events observed before the decision time.",
    "Allowed: queue size, waiting history, completed service, I/O returns, priorities, wakeups, and prior context switches.",
    "Excluded: future arrivals, declared total work, true remaining burst, later outcomes, and oracle identity.",
  ], 668, 170, 520, 264, { size: 20, spaceAfterPoints: 12 });
  addText(slide, "Selection rationale", 668, 468, 520, 30, { size: 22, bold: true });
  addBullets(slide, [
    "Process history can predict scheduler behavior [5].",
    "Recent queue and service history supports adaptive control [3].",
  ], 668, 510, 520, 112, { size: 19 });
  citation(slide, "[3] Fu et al.  [5] Negi and Pusukuri");
  setNotes(slide, "Feature extraction uses only the information available at each decision time. The 16 features summarize queue state, delays, observed service, completed burst behavior, I/O activity, priority, context switches, wakeups, and CPU busy fraction.", [
    "[3] https://www.usenix.org/system/files/atc24-fu.pdf",
    "[5] https://doi.org/10.1109/TENCON.2005.300837",
    path.join(workspaceDir, "configs/real_desktop_ml.json"),
  ]);
}

// 5. Modules
{
  const slide = baseSlide("System modules", 5);
  addText(slide, "The prototype runs through five modules", 72, 128, 1120, 32, { size: 22, bold: true });
  addBullets(slide, [
    "Trace and workload input: Linux scheduler events and controlled workload traces enter the system.",
    "Data preparation: cleaning, replay, feature extraction, and grouped splitting create safe model inputs.",
    "Model comparison: action-cost labels compare five model families and freeze the validated choice.",
    "Dynamic V3 router: confidence, dwell, and safe-boundary checks decide whether a suggested switch can occur.",
    "Shared simulator and reporting: every policy runs through one engine that produces metrics, a decision log, and a Gantt chart.",
  ], 72, 182, 1100, 340, { size: 20, spaceAfterPoints: 13 });
  addText(slide, "Frozen research contract", 72, 548, 380, 30, { size: 22, bold: true });
  addBullets(slide, [
    "Fixed policy set, score weights, feature rules, seeds, latency gate, and evidence boundary.",
  ], 72, 590, 1100, 64, { size: 19 });
  citation(slide, "Architecture precedents: [1] policy selection  [2] learned routing  [3] separated learning and execution");
  setNotes(slide, "The architecture has five modules. The data module creates safe observed-state rows. The comparison module freezes a model. Dynamic V3 applies confidence and dwell safeguards. Every policy executes through the same simulator and reporting path.", [
    "[1] https://doi.org/10.1109/STI59863.2023.10464816",
    "[2] https://arxiv.org/abs/2511.11628",
    "[3] https://www.usenix.org/system/files/atc24-fu.pdf",
  ]);
}

// 6. Models
{
  const slide = baseSlide("Five machine-learning models", 6);
  addBullets(slide, [
    "Dummy: minimum reference baseline.",
    "Ridge: fast regularized linear cost estimator.",
    "Decision Tree: interpretable nonlinear decision rules.",
    "Random Forest: averaged tree ensemble that reduces single-tree variance.",
    "Histogram Gradient Boosting: sequential trees that correct earlier errors.",
  ], 72, 140, 1090, 310, { size: 22, spaceAfterPoints: 15 });
  addText(slide, "Fair comparison", 72, 488, 400, 30, { size: 22, bold: true });
  addBullets(slide, [
    "All models receive the same 16 features.",
    "All models use the same grouped split, action-cost targets, and tuning budget.",
  ], 72, 530, 1090, 112, { size: 20 });
  citation(slide, "[7] scikit-learn  [8] Ridge  [9] Decision Trees  [10] Random Forest  [11] Gradient Boosting  Scheduling use: [1], [5]");
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

// 7. Model results
{
  const slide = baseSlide("Model comparison results", 7);
  const values = [
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
    left: 56,
    top: 132,
    width: 1168,
    height: 342,
    columnWidths: [276, 132, 132, 188, 220, 220],
    values,
  });
  styleTable(table, 6, 6, 16);
  addBullets(slide, [
    "Accuracy measures agreement with the deterministic lowest-cost action. It does not decide the winner by itself.",
    "Decision Tree produced the lowest validation scheduling score: 0.120669.",
    "Captured traces gave Ridge and Decision Tree equal realized cost and action agreement. The configured simplicity rule selected Ridge.",
  ], 72, 506, 1110, 142, { size: 18, spaceAfterPoints: 7 });
  setNotes(slide, "The controlled grouped split shows that action accuracy and scheduling outcome can disagree. Decision Tree has the lowest validation scheduling score, so the prototype freezes it. In the separate captured-trace bake-off, Ridge and Decision Tree tie on realized cost and action agreement. The configured simplicity rule selects Ridge, even though the tree has lower measured P99 inference time.", [
    path.join(workspaceDir, "results/dynamic_v3_demo01/REPORT.md"),
    path.join(workspaceDir, "results/dynamic_v3_demo01/model_family_bakeoff.csv"),
    path.join(workspaceDir, "results/real_desktop_ml/decision-tree-demo/prototype_comparison_report.md"),
  ]);
}

// 8. Tree formulations
{
  const slide = baseSlide("Classifier tree and policy-cost tree", 8);
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
    top: 132,
    width: 760,
    height: 390,
    columnWidths: [360, 200, 200],
    values,
  });
  styleTable(table, 7, 3, 16);
  addText(slide, "How they differ", 880, 132, 320, 30, { size: 22, bold: true });
  addBullets(slide, [
    "Classifier tree directly proposes one scheduler.",
    "Policy-cost tree predicts each scheduler's cost and selects the minimum estimate.",
  ], 880, 174, 328, 180, { size: 19, spaceAfterPoints: 12 });
  addText(slide, "Prototype choice", 880, 398, 320, 30, { size: 22, bold: true });
  addBullets(slide, [
    "The demonstration freezes the classifier tree because its validation scheduling score and P95 response were better.",
    "The policy-cost tree remains an evaluated alternative.",
  ], 880, 440, 328, 178, { size: 18, spaceAfterPoints: 10 });
  setNotes(slide, "The classifier optimizes direct policy choice. The policy-cost tree estimates each candidate action. The classifier is frozen for the demonstration because it produced the lower validation scheduling score and much lower P95 response, even though the policy-cost tree had lower test action regret and fewer starvation events.", [
    path.join(workspaceDir, "results/dynamic_v3_demo01/tree_variant_comparison.json"),
  ]);
}

// 9. Demonstration
{
  const slide = baseSlide("End-to-end Dynamic V3 demonstration", 9);
  slide.images.add({
    blob: new Uint8Array(ganttBytes.buffer, ganttBytes.byteOffset, ganttBytes.byteLength),
    contentType: "image/png",
    alt: "Dynamic V3 CPU execution timeline for the unseen changing workload",
    fit: "contain",
    position: { left: 54, top: 130, width: 760, height: 470 },
  });
  addText(slide, "Router workflow", 858, 132, 340, 30, { size: 22, bold: true });
  addBullets(slide, [
    "Observe the workload every 10 ticks.",
    "The classifier proposes a scheduler.",
    "Confidence and 20-tick dwell checks review the proposal.",
    "The router switches only at a safe dispatch boundary.",
  ], 858, 174, 340, 236, { size: 18, spaceAfterPoints: 9 });
  addText(slide, "Observed result", 858, 430, 340, 30, { size: 22, bold: true });
  addBullets(slide, [
    "52 reviews and 8 accepted switches.",
    "Initial policy: MLFQ. Final policy: Priority.",
    "Decision P99: 0.456 ms.",
  ], 858, 470, 340, 132, { size: 18, spaceAfterPoints: 7 });
  addText(slide, "The demonstration validates the prototype workflow and latency target. It does not establish Linux kernel performance or universal policy superiority.", 72, 622, 1120, 44, { size: 15 });
  setNotes(slide, "This demonstration uses an unseen changing workload with CPU-intensive, interactive, and batch phases. The router reviews the observed state every 10 ticks. Confidence, a 20-tick minimum dwell, and safe dispatch boundaries limit switching. The result proves the prototype control flow and measured decision latency for this run. It does not prove Linux kernel scheduling performance or superiority over every fixed scheduler.", [
    path.join(workspaceDir, "results/dynamic_v3_demo01/summary.json"),
    path.join(workspaceDir, "results/dynamic_v3_demo01/decision_log.csv"),
    ganttPath,
  ]);
}

// 10. References
{
  const slide = baseSlide("References", 10);
  const left = [
    "[1] S. Biswas et al., “A Machine Learning Approach for Predicting Efficient CPU Scheduling Algorithm,” STI, 2023, doi: 10.1109/STI59863.2023.10464816.",
    "[2] X. Wang et al., “Mixture-of-Schedulers: An Adaptive Scheduling Agent as a Learned Router for Expert Policies,” arXiv:2511.11628, 2025.",
    "[3] Y. Fu et al., “ALPS: An Adaptive Learning, Priority OS Scheduler for Serverless Functions,” USENIX ATC, 2024.",
    "[4] H. Lee, S. Jung, and H. Jo, “STUN: Reinforcement-Learning-Based Optimization of Kernel Scheduler Parameters,” Applied Sciences, 2022.",
    "[5] A. Negi and K. K. Pusukuri, “Applying Machine Learning Techniques to Improve Linux Process Scheduling,” TENCON, 2005.",
    "[6] D. Seo et al., “SCHED: Safe CPU Scheduling Framework with Reinforcement Learning and Decision Trees,” VTC-Spring, 2025.",
  ];
  const right = [
    "[7] F. Pedregosa et al., “Scikit-learn: Machine Learning in Python,” Journal of Machine Learning Research, vol. 12, pp. 2825–2830, 2011.",
    "[8] A. E. Hoerl and R. W. Kennard, “Ridge Regression: Biased Estimation for Nonorthogonal Problems,” Technometrics, vol. 12, no. 1, pp. 55–67, 1970.",
    "[9] J. R. Quinlan, “Induction of Decision Trees,” Machine Learning, vol. 1, pp. 81–106, 1986.",
    "[10] L. Breiman, “Random Forests,” Machine Learning, vol. 45, pp. 5–32, 2001.",
    "[11] J. H. Friedman, “Greedy Function Approximation: A Gradient Boosting Machine,” Annals of Statistics, vol. 29, no. 5, pp. 1189–1232, 2001.",
  ];
  left.forEach((value, index) => addText(slide, value, 64, 126 + index * 84, 548, 72, { size: 14 }));
  right.forEach((value, index) => addText(slide, value, 666, 126 + index * 100, 548, 88, { size: 14 }));
  setNotes(slide, "IEEE-style bibliography for all numbered citations used in the deck.", [
    "/Users/knightnm/Documents/OS_Project/AutoSchedulerPapers.md",
  ]);
}

for (let index = 0; index < deck.slides.items.length; index += 1) {
  const slide = deck.slides.items[index];
  const png = await deck.export({ slide, format: "png", scale: 1 });
  await fs.writeFile(path.join(previewDir, `slide-${String(index + 1).padStart(2, "0")}.png`), new Uint8Array(await png.arrayBuffer()));
}
const montage = await deck.export({ format: "webp", montage: true });
await fs.writeFile(path.join(buildDir, "montage.webp"), new Uint8Array(await montage.arrayBuffer()));

const stagingDir = path.join(workspaceDir, ".codex-finalizer");
await fs.mkdir(stagingDir, { recursive: true });
const candidatePath = path.join(stagingDir, "autoscheduler-simple-bw-candidate.pptx");
await (await PresentationFile.exportPptx(deck)).save(candidatePath);

const requirements = {
  explicitTotalSlideCount: 10,
  requiredNativeTableOwnerSlides: [7, 8],
  requiredNativeChartOwnerSlides: [],
  requiredEmbeddedWorkbookChartOwnerSlides: [],
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
    "--validate-bullet-geometry",
    "--validate-heading-fit",
    "--require-native-table-slide", "7",
    "--require-native-table-slide", "8",
  ],
  requiredNativeTableOwnerSlides: requirements.requiredNativeTableOwnerSlides,
  requiredNativeChartOwnerSlides: [],
  fontPolicy: { basis: "design", families: [FONT] },
  verifyArtifactToolImport: true,
  receiptPath: path.join(stagingDir, "AutoScheduler_Project_Review_Simple_BW_release.validation.json"),
});

console.log(JSON.stringify({ finalPath, previewDir, validation: result }, null, 2));
