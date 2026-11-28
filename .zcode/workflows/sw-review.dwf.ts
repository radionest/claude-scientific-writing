/* zcode-workflow
description: "Ревью русской научной прозы по полосам: план измерений из lib.review_plan,
  полосы из lib.lanes, каждое измерение — параллельный субагент с явной моделью своей
  полосы. Ничего не пишет на диск: возвращает план и находки по измерениям, файл отчёта
  составляет вызывающий."
whenToUse: "Когда нужно прогнать ансамбль ревью (ансамбль prose-reviewer) по .qmd с
  явными моделями полос fast/strong — например, в контуре spec→write→review→fix или для
  замера находок против золотой таблицы (lib.lane_measure)."
args:
  document:
    type: string
    description: "Абсолютный путь к .qmd"
    required: true
  mode:
    type: string
    description: "diff | light | deep | full (как в lib.review_plan)"
    default: "diff"
  before:
    type: string
    description: "Исходник до правки (добавляет измерение fidelity)"
  fast_model:
    type: string
    description: "Модель полосы fast: providerId/modelId[$level] из ListModels"
    required: true
  strong_model:
    type: string
    description: "Модель полосы strong: providerId/modelId[$level] из ListModels"
    required: true
  dimensions:
    type: string
    description: "Фильтр измерений: id через запятую (пусто — все из плана)"
*/

interface PlanDimension {
  /** id измерения из реестра (calques, repeats, …). */
  id: string;
  /** Полоса измерения: fast | strong. */
  tier: string;
  /** Условие включения в план. */
  when: string;
  /** Причина включения, одна строка. */
  reason: string;
  /** true — измерение уже закрывает линтер, дублирующего ревьюера не запускаем. */
  covered_by_lint: boolean;
}

interface ReviewFinding {
  /** Путь к файлу находки. */
  file: string;
  /** Номер строки. */
  line: number;
  /** Измерение ансамбля. */
  dimension: string;
  /** Строгость: blocker | warning | nit. */
  severity: "blocker" | "warning" | "nit";
  /** Одна фраза: в чём проблема. */
  problem: string;
  /** Предлагаемая правка. */
  fix: string;
}

interface DimensionRun {
  dimension: string;
  tier: string;
  findings: ReviewFinding[];
}

const REPO = "/home/nest/Projects/claude-scientific-writing";
const doc = String(args.document);
const mode = args.mode ? String(args.mode) : "diff";
const beforePath = args.before ? String(args.before) : null;
const fastModel = String(args.fast_model);
const strongModel = String(args.strong_model);
const wanted = args.dimensions
  ? String(args.dimensions).split(",").map((s) => s.trim()).filter((s) => s.length > 0)
  : null;

phase("План ревью и полосы");
const planOut = await world.run("/home/nest/Projects/claude-scientific-writing/.venv/bin/python", [
  "-c",
  "import sys, json; sys.path.insert(0, '" + REPO + "'); " +
  "from dataclasses import asdict; from pathlib import Path; " +
  "from lib.review_plan import plan as review_plan; " +
  "p = review_plan(Path(sys.argv[1]), mode='" + mode + "', " +
  "before=Path(sys.argv[2]) if sys.argv[2] else None); " +
  "print(json.dumps({'mode': p.mode, 'dimensions': [asdict(d) for d in p.dimensions]}))",
  doc,
  beforePath ?? "",
], { output: { tail: 65536 } });
if (planOut.exitCode !== 0) {
  throw new Error("lib.review_plan failed: " + (planOut.stderr || planOut.stdout).slice(-2000));
}
const plan = JSON.parse(planOut.stdout) as { mode: string; dimensions: PlanDimension[] };

const lanesOut = await world.run("/home/nest/Projects/claude-scientific-writing/.venv/bin/python", [
  "-c",
  "import sys, json; sys.path.insert(0, '" + REPO + "'); " +
  "from lib.lanes import load_lanes; l = load_lanes(sys.argv[1]); " +
  "print(json.dumps({'writer': l.writer, 'judge': l.judge, 'tiers': dict(l.tiers)}))",
  doc,
], { output: { tail: 16384 } });
if (lanesOut.exitCode !== 0) {
  throw new Error("lib.lanes failed: " + (lanesOut.stderr || lanesOut.stdout).slice(-2000));
}
const lanes = JSON.parse(lanesOut.stdout) as { writer: string; judge: string; tiers: Record<string, string> };

const contractsOut = await world.run("/home/nest/Projects/claude-scientific-writing/.venv/bin/python", [
  "-c",
  "import sys, json; sys.path.insert(0, '" + REPO + "'); " +
  "from lib.review_plan import dimension_contracts; " +
  "print(json.dumps(dimension_contracts('" + REPO + "')))",
], { output: { tail: 65536 } });
if (contractsOut.exitCode !== 0) {
  throw new Error("dimension_contracts failed: " + (contractsOut.stderr || contractsOut.stdout).slice(-2000));
}
const contracts = JSON.parse(contractsOut.stdout) as Record<string, string>;

const dispatched = plan.dimensions
  .filter((d) => (wanted ? wanted.includes(d.id) : true))
  .filter((d) => !d.covered_by_lint);
log("План " + plan.mode + ": измерений " + dispatched.length + " из " + plan.dimensions.length +
  " (полосы: writer=" + lanes.writer + ", judge=" + lanes.judge + ")");
log("Модели: fast=" + fastModel + ", strong=" + strongModel);

phase("Параллельное ревью по измерениям");
// Один join в конце: вызывающий собирает полный отчёт из всех измерений сразу.
const runs: DimensionRun[] = await Promise.all(dispatched.map(async (d) => {
  const model = d.tier === "strong" ? strongModel : fastModel;
  const reviewer = agent("Ревьюер " + d.id, {
    system:
      "Ты — один ревьюер в ансамбле проверки русской научной прозы, измерение " + d.id +
      " (полоса " + d.tier + "). Твой контракт:\n" + (contracts[d.id] ?? "") +
      "\n\nПрочитай документ " + doc + " и его спецификацию " +
      doc.replace(/\.qmd$/, ".spec.md") + " (если существует), жанровый профиль из canon/profiles " +
      "и применяй только своё измерение. Никаких правок файлов. Верни строго JSON-список находок " +
      "[{file, line, dimension, severity, problem, fix}] — только находки, не переписывай документ.",
    model,
  });
  const findings = await reviewer.ask<ReviewFinding[]>(
    "Прогони измерение " + d.id + " по документу " + doc +
    (beforePath ? " (исходник до правки: " + beforePath + ")" : "") +
    ". Верни только JSON-список находок.");
  return { dimension: d.id, tier: d.tier, findings };
}));

return {
  plan: { mode: plan.mode, dimensions: plan.dimensions },
  runs,
};
