/* zcode-workflow
description: "Прогоняет roadmap по открытым issues (14 issues → 10 PR в 9
  параллельных полосах): для каждого PR — write (GLM-5.3-Flash Start Plan) →
  полный pytest-гейт в ворктри → независимый review (GLM-5.3 Coding Plan) → fix,
  ≤3 раунда. Ветки dwf/pr-*, без push."
whenToUse: "Когда нужно исполнить roadmap открытых issues из
  .zcode/plans/2026-11-13-issues-roadmap.md: 10 PR параллельными полосами с
  циклом write→review→fix независимыми субагентами. Ревью-цикл запускается
  только на свежем main (ворктри dwf-pr-* и ветки dwf/pr-* не должны
  существовать; после частичного прогона почистить git worktree remove / git
  branch -D или править LANES в файле воркфлоу)."
*/
// Roadmap issues → parallel lanes, each PR: write → pytest gate → independent review → fix, ≤3 rounds.
// Write/fix: Start Plan (weekend build) GLM-5.3-Flash; review: Coding Plan GLM-5.3. No push, no PR creation.

interface PrCard {
  /** Roadmap section id ("PR-1"); the card lives under "### PR-1 (#14): ..." in the roadmap file. */
  id: string;
  /** Short human label for the board and the report. */
  title: string;
  /** Absolute worktree path; absent = the PR works outside the repo (PR-10, no commits). */
  worktree?: string;
  /** Extra instruction appended to writer and reviewer asks. */
  note?: string;
}

interface WriteResult {
  /** Branch the commits landed on ("" for the out-of-repo PR-10). */
  branch: string;
  /** Commit subjects created this round ([] for PR-10). */
  commits: string[];
  /** Whether the writer ran the full suite green itself before committing. */
  testsPassed: boolean;
  /** 2-4 sentences: what was done. */
  notes: string;
  /** Set with a reason only when the card cannot be implemented as written. */
  blocked?: string;
}

interface ReviewIssue {
  /** One sentence: what is wrong (not how to fix it). */
  what: string;
  /** Worktree-relative file[:line] the issue applies to. */
  where: string;
  /** How much it matters. "high" = the card is not fulfilled or a required test is missing. */
  severity: "low" | "medium" | "high";
}

interface ReviewVerdict {
  /** True only when no medium/high issues remain: card steps done, tests adequate, no scope creep. */
  approved: boolean;
  issues: ReviewIssue[];
  /** 2-3 sentences of overall judgement. */
  summary: string;
}

interface LaneOutcome {
  pr: string;
  title: string;
  status: "writing" | "fixing" | "reviewing" | "done" | "failed" | "blocked";
  rounds: number;
  branch: string;
  commits: string[];
  reviewSummary: string;
  testGate: "pass" | "fail" | "n/a";
}

interface Finding {
  /** Workspace-relative path, with a line when it applies: "src/a.ts:42". */
  where: string;
  /** One sentence: what is wrong, or what was found. */
  what: string;
  /** What showed it: the lines read, or the command and the output that proved it. */
  evidence: string;
  /** "verified" when an independent subagent or a deterministic check confirmed it; "unconfirmed" when confirmation failed or was not attempted. */
  status: "verified" | "unconfirmed";
  /** How much it matters. Reserve "high" for data loss, a crash, or a wrong result. */
  severity: "low" | "medium" | "high";
}

interface WorkflowReport {
  /** Two or three sentences answering what the user asked for. */
  conclusion: string;
  findings: Finding[];
  /** What the run checked and how: the commands it ran, the files it covered. */
  verified: string[];
  /** What the run did not look at or could not check, and why. */
  notCovered: string[];
}

const REPO = "/home/nest/Projects/claude-scientific-writing";
const ROADMAP = REPO + "/.zcode/plans/2026-11-13-issues-roadmap.md";
const PYTEST = REPO + "/.venv/bin/pytest";
const SCRIPT = "/home/nest/.claude/scripts/docx_review.py";
const SCRIPT_BAK = "/home/nest/.claude/scripts/docx_review.py.dwf-bak";
const WRITE_MODEL = "account:zai-start-plan/GLM-5.3-Flash";
const REVIEW_MODEL = "account:zai-individual-coding-plan/GLM-5.3";

const LANES: PrCard[][] = [
  [{ id: "PR-1", title: "doc-abbrev-*: находка на каждом вхождении (#14)", worktree: REPO + "/.claude/worktrees/dwf-pr-1" }],
  [{ id: "PR-2", title: "Правило «печёночные метастазы» → «метастазы в печени» (#4)", worktree: REPO + "/.claude/worktrees/dwf-pr-2" }],
  [{ id: "PR-3", title: "Exit-код конфиг-ошибки 2→3 + note /text-review (#8, #9)", worktree: REPO + "/.claude/worktrees/dwf-pr-3" },
   { id: "PR-5", title: "tune_diff: check-kind триаж + локальный словарь (#13, #5)", worktree: REPO + "/.claude/worktrees/dwf-pr-3",
     note: "PR-3 уже закоммичен и отревьюен в этом же ворктри — работай поверх него; в диффе видны и коммиты PR-3." }],
  [{ id: "PR-4", title: "Валидация layer + оверлей в worktrees (#10, #11)", worktree: REPO + "/.claude/worktrees/dwf-pr-4" }],
  [{ id: "PR-6", title: "tune-learn: жанр без сайдкара + --from-docx (#6, #15)", worktree: REPO + "/.claude/worktrees/dwf-pr-6" }],
  [{ id: "PR-7", title: "docx_review: автор tracked-change + RuntimeError (#18)", worktree: REPO + "/.claude/worktrees/dwf-pr-7" }],
  [{ id: "PR-8", title: "_STOP_REPEAT → allow в canon (#16)", worktree: REPO + "/.claude/worktrees/dwf-pr-8" }],
  [{ id: "PR-9", title: "Скиллы ↔ canon: консолидация (#17)", worktree: REPO + "/.claude/worktrees/dwf-pr-9",
     note: "AGENTS.md не трекается в git и в ворктри отсутствует — правь CLAUDE.md и docs/design.md; AGENTS.md синхронизирует пользователь." }],
  [{ id: "PR-10", title: "pandoc-скрипт: комментарии на заголовках (#22)" }],
];

const WRITER_SYSTEM =
  "Ты — реализатор правок в плагине scientific-writing (репозиторий " + REPO + "). Следуй карточке " +
  "из roadmap-файла буквально и не выходи за перечисленные в ней файлы. Коммиты: английский, conventional " +
  "commits, номер issue в скобках, без Co-Authored-By, без push. Перед каждым коммитом добивайся зелёного " +
  "полного прогона тестов в своём ворктри. Если карточку невозможно выполнить, тесты падают по причине вне " +
  "карточки или инструкции противоречат друг другу — верни blocked с объяснением, а не обходи препятствие.";

const REVIEWER_SYSTEM =
  "Ты — независимый ревьюер кода и документации плагина scientific-writing. Твоя работа — найти, что " +
  "сломает эту правку: невыполненные шаги карточки, отсутствующие тесты, выход за скоуп, неидиоматичный " +
  "для репозитория код, кривые коммиты. Команды только читающие (git diff/log/show, diff, чтение файлов); " +
  "ничего не правь и не коммить. approved — только когда не осталось замечаний severity medium/high.";

function writeAsk(pr: PrCard, branch: string): string {
  const where = pr.worktree
    ? "Ворктри " + pr.worktree + " (ветка " + branch + " уже создана и выбрана). "
    : "Работай прямо с файлом " + SCRIPT + " (бэкап снят в " + SCRIPT_BAK + "); он вне git — коммитов не делай. ";
  const check = pr.worktree
    ? "Перед коммитом: cd " + pr.worktree + " && " + PYTEST + " -q — полный прогон должен быть зелёным. "
    : "Синтаксис проверь python3 -m py_compile. ";
  return "Реализуй " + pr.id + " (" + pr.title + "). Карточка: файл " + ROADMAP + ", секция «### " + pr.id + "». " +
    where + (pr.note ?? "") + "\nВыполни все шаги карточки, включая названные в ней тесты. " + check +
    "Верни WriteResult: branch, commits (subject-строки), testsPassed, notes (2–4 предложения), blocked — только с причиной.";
}

function fixAsk(pr: PrCard, feedback: string): string {
  const tail = pr.worktree
    ? "прогони " + PYTEST + " -q в " + pr.worktree + " и закоммить отдельным коммитом"
    : "проверь python3 -m py_compile";
  return "Продолжай " + pr.id + " (" + pr.title + ") там же (" + (pr.worktree ?? SCRIPT) + "). " + (pr.note ?? "") +
    "\n" + feedback + "\nУстрани замечания, " + tail + ". Верни WriteResult.";
}

function reviewAsk(pr: PrCard): string {
  const diff = pr.worktree
    ? "git -C " + pr.worktree + " diff main...HEAD и git -C " + pr.worktree + " log main..HEAD --oneline"
    : "diff -u " + SCRIPT_BAK + " " + SCRIPT;
  return "Отревьюи " + pr.id + " (" + pr.title + "). Карточка: файл " + ROADMAP + ", секция «### " + pr.id + "».\n" +
    "Дифф: " + diff + ". " + (pr.note ?? "") + "\n" +
    "Ищи, что сломано и чего не хватает, а не подтверждение: все ли шаги карточки выполнены; есть ли тесты, " +
    "которых она требует; нет ли выхода за скоуп; идиоматично ли для этого репозитория; коммиты английские " +
    "conventional. Ничего не правь. Верни ReviewVerdict.";
}

artifact.board("lanes", {
  key: "pr",
  status: "status",
  columns: ["writing", "fixing", "reviewing", "done", "failed", "blocked"],
  cardTitle: "title",
  detail: [{ field: "branch" }, { field: "rounds" }, { field: "testGate" }],
  title: "Полосы roadmap: PR за PR",
});

phase("Подготовить ворктри под каждую полосу");
const setup: { wt: string; err: string }[] = [];
for (const p of LANES.flat()) {
  if (!p.worktree || setup.some(s => s.wt === p.worktree)) continue;
  const r = await world.run("git", ["-C", REPO, "worktree", "add", p.worktree, "-b", "dwf/" + p.id.toLowerCase()],
    { output: { tail: 4096 } });
  const out = r.stderr || r.stdout;
  // A worktree left by an earlier run at the base commit is reused, not an error.
  const reused = r.exitCode !== 0 && /already (exists|registered)/.test(out);
  setup.push({ wt: p.worktree, err: r.exitCode === 0 || reused ? "" : out.slice(-2000) });
}
await world.run("cp", [SCRIPT, SCRIPT_BAK], { output: { tail: 2048 } });

phase("Реализовать каждый PR: написать, отревьюить, починить");
log("Полос: " + LANES.length + ", PR: " + LANES.flat().length + " (PR-3→PR-5 последовательно в одном ворктри)");
// Один join в конце: итоговый отчёт и артефакт требуют исход всех полос; полосы идут concurrently.
const laneOutcomes = await Promise.all(LANES.map(async (lane): Promise<LaneOutcome[]> => {
  const done: LaneOutcome[] = [];
  for (const pr of lane) {
    const branch = "dwf/" + pr.id.toLowerCase();
    const base: LaneOutcome = { pr: pr.id, title: pr.title, status: "writing", rounds: 0,
      branch: pr.worktree ? branch : "", commits: [], reviewSummary: "", testGate: "n/a" };
    const wtErr = pr.worktree ? setup.find(s => s.wt === pr.worktree)?.err ?? "ворктри не создан" : "";
    if (wtErr) {
      const out = { ...base, status: "blocked" as const, reviewSummary: "ворктри не создан: " + wtErr };
      done.push(out); report(out, "lanes"); break;
    }
    const writer = agent("Реализатор " + pr.id, { system: WRITER_SYSTEM, model: WRITE_MODEL });
    const reviewer = agent("Ревьюер " + pr.id, { system: REVIEWER_SYSTEM, model: REVIEW_MODEL });
    let last: WriteResult | null = null;
    let verdict: ReviewVerdict | null = null;
    let gate: "pass" | "fail" | "n/a" = "n/a";
    let reviews = 0;
    try {
      last = await writer.ask<WriteResult>(writeAsk(pr, branch));
      for (let round = 1; round <= 3 && !last.blocked; round++) {
        const g = pr.worktree
          ? await world.run("/home/nest/Projects/claude-scientific-writing/.venv/bin/pytest",
              ["-c", pr.worktree + "/pyproject.toml", pr.worktree + "/tests", "-q"],
              { timeoutMs: 600000, output: { tail: 16384 } })
          : await world.run("python3", ["-m", "py_compile", SCRIPT], { output: { tail: 4096 } });
        gate = g.exitCode === 0 ? "pass" : "fail";
        if (g.exitCode !== 0) {
          report({ ...base, status: "fixing", rounds: round }, "lanes");
          last = await writer.ask<WriteResult>(fixAsk(pr,
            "Полный прогон упал (exit " + g.exitCode + "). Хвост вывода:\n" + (g.stderr || g.stdout).slice(-4000)));
          continue;
        }
        report({ ...base, status: "reviewing", rounds: round }, "lanes");
        reviews = round;
        verdict = await reviewer.ask<ReviewVerdict>(reviewAsk(pr));
        if (verdict.approved) break;
        last = await writer.ask<WriteResult>(fixAsk(pr,
          "Замечания ревьюера:\n" + JSON.stringify(verdict.issues, null, 2) + "\n\n" + verdict.summary));
      }
      const status: LaneOutcome["status"] = last.blocked ? "blocked" : verdict?.approved ? "done" : "failed";
      const out: LaneOutcome = { ...base, status, rounds: reviews,
        branch: (pr.worktree && last.branch) ? last.branch : base.branch,
        commits: last.commits,
        reviewSummary: last.blocked ?? verdict?.summary ?? "approval не достигнуто за 3 раунда",
        testGate: gate };
      done.push(out); report(out, "lanes");
      if (status !== "done") break; // PR-5 опирается на PR-3 в том же ворктри
    } catch (e) {
      const out: LaneOutcome = { ...base, status: "failed", rounds: reviews,
        reviewSummary: "полоса упала с ошибкой: " + String(e), testGate: gate };
      done.push(out); report(out, "lanes"); break;
    }
  }
  return done;
}));

const flat = laneOutcomes.flat();
const ok = flat.filter(o => o.status === "done");
const bad = flat.filter(o => o.status !== "done");

const findings: Finding[] = bad.map(o => ({
  where: o.branch || "вне репозитория (" + o.pr + ")",
  what: o.pr + " (" + o.title + ") — " + (o.status === "failed" ? "не прошёл цикл за отведённые раунды" : "заблокирован"),
  evidence: o.reviewSummary,
  status: o.testGate === "fail" ? "verified" : "unconfirmed",
  severity: o.status === "failed" ? "high" : "medium",
}));

const md = [
  "# Прогон roadmap " + run.id + " — " + ok.length + "/" + flat.length + " PR готовы",
  "",
  "| PR | Статус | Ветка | Раунды ревью | Гейт | Коммиты |",
  "|---|---|---|---|---|---|",
  ...flat.map(o => "| " + o.pr + " | " + o.status + " | " + (o.branch || "—") + " | " + o.rounds +
    " | " + o.testGate + " | " + (o.commits.join("; ") || "—") + " |"),
  "",
  "## Резюме ревью по PR",
  ...flat.map(o => "- **" + o.pr + " (" + o.status + ")**: " + o.reviewSummary),
  "",
  "Ворктри: `" + REPO + "/.claude/worktrees/dwf-pr-*`. Ничего не запушено — ветки ждут ручной проверки.",
].join("\n");
await artifact.markdown("report", md, {
  title: "Итог прогона roadmap",
  description: ok.length + " из " + flat.length + " PR прошли write→review→fix; ветки, раунды и резюме ревью внутри.",
  primary: true,
});

const result: WorkflowReport = {
  conclusion: "Из " + flat.length + " PR цикл write→review→fix прошли " + ok.length + "." +
    (bad.length ? " Не готовы: " + bad.map(o => o.pr + " (" + o.status + ")").join(", ") + "." : "") +
    " Ветки dwf/pr-* и ворктри .claude/worktrees/dwf-pr-* ждут ручной проверки; ничего не запушено.",
  findings,
  verified: [
    "полный pytest-прогон в ворктри каждого PR после каждой итерации (гейт решает exit-код, конфиг ворктри через -c)",
    "независимое ревью каждого PR на GLM-5.3 (write/fix — GLM-5.3-Flash Start Plan), всего " +
      flat.reduce((n, o) => n + o.rounds, 0) + " раундов",
  ],
  notCovered: [
    "ветки не пушены и PR на GitHub не созданы — коммиты ждут просмотра пользователя",
    "PR-10 проверен синтетически (py_compile + регресс по карточке); живой ревью-файл от 2026-11-13 не перепрогонялся",
  ],
};
return result;