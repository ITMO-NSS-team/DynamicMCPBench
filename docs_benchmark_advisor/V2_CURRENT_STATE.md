# Benchmark Advisor V2: что сделано в BA5/BA6 и зачем

Дата среза: 2026-07-06.

Этот документ можно использовать как основу для презентации текущего состояния
Benchmark Advisor V2. Логика рассказа:

1. Почему Benchmark Advisor V1 был полезен, но недостаточен.
2. Какие проблемы закрывает V2.
3. Как это реализовано технически: Statistical Engine, v2 contracts, reports,
   Studio UI и guarded handoff.

## Executive Summary

Benchmark Advisor V2 превращает Stage 0 в DMCP Studio из формы с вердиктом и
JSON preview в статистический workbench перед генерацией benchmark corpus.

Ключевая архитектурная идея:

```text
guide-first planner -> Statistical Engine scores parameters -> deterministic rules decide
```

То есть не LLM, не RAG и не UI-текст решают, можно ли доверять дизайну.
Решение строится на:

- `STATISTICAL_GUIDE.md` как статическом статистическом контракте;
- deterministic Statistical Engine;
- typed v2 schemas;
- validator rules;
- all-issue reporting;
- explicit claim boundaries;
- guarded corpus-only handoff.

Главное отличие от V1: статистика стала центральной частью Advisor, а не
декоративным набором rough numbers после того, как planner уже выбрал параметры.

## 1. Почему V1 не устраивал

V1 был хорошим safety gate: он принимал intent, строил структурированный
`AdvisorDesign`, валидировал его, показывал warnings/refusals и отдавал dry-run
`ExportConfig`. Но для настоящего statistical advisor этого было мало.

### Проблема 1: параметры выбирались до статистики

В V1 поток был ближе к такому:

```text
intent -> planner picks design defaults -> validator checks -> planning stats explain/warn
```

Это означает, что task budget, attempts, target detectable effect, task mix и
claim boundary могли выглядеть как planner defaults. Статистика объясняла уже
выбранный дизайн, но не была ядром выбора.

### Проблема 2: MDE был rough heuristic без workbench

V1 показывал planning MDE/CI как эвристику. Это полезно, но не отвечает на
практические вопросы пользователя:

- что именно покупает больший бюджет;
- где граница между smoke, warning и defensible claim;
- как attempts влияют на reliability, но не на iid sample size;
- почему 40 задач с 3 attempts не становятся 120 независимыми задачами;
- какой claim честен при текущем MDE;
- какая stronger alternative нужна для меньшего detectable effect.

### Проблема 3: не было полноценного post-run report

V1 декларировал outcome tensor как будущий Stage 2 contract, но не умел
превращать completed outcomes в statistical report. После прогона не было
единых scoped claims, CIs, effect sizes, rank stability, missingness и
multiplicity notes.

### Проблема 4: UI был preview, а не statistical workbench

Stage 0 показывал advisor cards и export JSON, но не делал статистику главной
частью пользовательского опыта. Пользователь не видел полноценный claim card,
assumptions panel, method card, power curve, alternatives, repair actions и
post-run report view как единый workflow.

### Проблема 5: handoff был preview-only

V1 export указывал на `scripts/build_corpus.py`, но сам Advisor не переносил
approved design в Collect как устойчивое состояние и не имел guarded launch
job/status/artifacts слоя.

Важно для текущего среза: BA6 уже добавил guarded carry/launch в Studio, но это
пока corpus/specs/traces handoff. Это не full downstream benchmark/eval
pipeline и не `dmcp bench`.

## 2. Что V2 решает

V2 закрывает эти проблемы через BA5 и BA6.

### Новый поток V2

```text
AdvisorV2DesignRequest
  -> deterministic preflight planner
  -> Statistical Engine candidate search
  -> deterministic validator for every candidate
  -> EngineDecision
  -> StatisticalPlan
  -> Studio statistical workbench
  -> guarded carry into Collect
  -> guarded corpus/specs/traces launch
```

Если intent недопустим или неполный, V2 возвращает `refused` или
`needs_clarification` без launchable export.

### V1 vs V2

| Область | V1 | V2 |
|---|---|---|
| Основная роль | pre-run sanity gate | statistical workbench |
| Выбор параметров | planner defaults + validator | Statistical Engine candidate search |
| MDE | rough planning helper | engine-owned MDE/CI/power diagnostics |
| Attempts | предупреждения через validator | explicit n_eff caveat: attempts не умножают iid N |
| Claims | claim boundary в design | claim card: allowed / not allowed claims |
| Issues | warnings + main refusal | all `StatisticalIssue` objects |
| UI | cards + JSON preview | claim, method, power curve, assumptions, alternatives, repairs |
| Post-run | stub/future | `OutcomeTensor` -> `StatisticalReport` |
| Handoff | dry-run export preview | carry into Collect + guarded launch job |
| Launch scope | no launch | corpus/specs/traces only, no leaderboard/eval |
| RAG/LLM | not required | still not required; guide-first deterministic MVP |

## 3. Что конкретно сделано в BA5

BA5 сделал статистику центральной частью Advisor V2.

### BA5.1: v2 contracts

Добавлены строгие Pydantic v2-схемы в
`benchmark_advisor/v2_schema.py`.

Основные типы:

- `AdvisorV2DesignRequest`, `AdvisorV2DesignResponse`;
- `AdvisorV2ValidationRequest`, `AdvisorV2ValidationResponse`;
- `StatisticalPlan`;
- `EngineDecision`;
- `ParameterSearchSpace`, `ParameterCandidate`;
- `PowerAnalysis`, `PowerCurvePoint`, `BudgetAlternative`;
- `AssumptionLedger`;
- `PlanningDiagnostic`;
- `StatisticalIssue`;
- `OutcomeTensor`, `StatisticalReport`;
- `LaunchRequest`, `LaunchJob`.

Зачем это нужно: frontend/backend больше не обмениваются неявными blob-объектами.
V2 contract фиксирует, какие поля есть у statistical plan, report и launch job.

### BA5.2: guide citation index вместо обязательного RAG

Реализован `benchmark_advisor/guide_citations.py`.

Он offline парсит `STATISTICAL_GUIDE.md` и дает v2 плану citation cards:

- rule id;
- section;
- evidence status;
- source keys;
- snippet;
- guide references.

Это решает source visibility без RAG. Важно: citations объясняют, но не решают.
Статусы и launchability определяются Statistical Engine и validator rules.

### BA5.3: guide-first v2 composition

Реализован `benchmark_advisor/v2_service.py`.

Сервис:

- принимает `AdvisorV2DesignRequest`;
- делает preflight через существующий deterministic planner;
- вызывает `run_statistical_engine`;
- оборачивает `EngineDecision` в `StatisticalPlan`;
- строит `ExportConfig`, если статус exportable;
- возвращает `launchable` только для approved/warning plan.

Routes в Studio backend:

- `POST /api/advisor/v2/design`;
- `POST /api/advisor/v2/validate`;
- `POST /api/advisor/v2/report`;
- `POST /api/advisor/v2/launch`;
- `GET /api/advisor/v2/launch/{job_id}`.

### BA5.4: Statistical Engine

Реализован `benchmark_advisor/v2_engine.py` с расчетами из
`benchmark_advisor/stats.py`.

Statistical Engine теперь делает то, чего не хватало V1: выбирает параметры до
final recommendation.

Engine:

- строит finite candidate grid;
- перебирает task budgets, attempts и target effect;
- для каждого candidate строит structured design через deterministic planner;
- валидирует каждый candidate;
- добавляет mode-specific statistical issues;
- считает MDE, CI width, budget alternatives и diagnostics;
- собирает assumption ledger;
- выбирает recommended candidate deterministic scoring;
- возвращает alternatives и computation trace.

#### Как считается MDE

MDE означает minimum detectable effect. В Advisor он хранится в percentage
points и отвечает на pre-run вопрос:

> эффект какого размера этот план примерно способен различить при данном числе
> unique tasks и assumptions?

Текущая no-prior формула в `stats.py`:

```text
delta = (z_alpha + z_power) * sqrt(2 * p * (1 - p) / n)
MDE_pp = delta * 100
```

Где:

- `p` — assumed baseline pass rate, по умолчанию `0.5`;
- `n` — unique tasks, а не `tasks * attempts`;
- alpha — `0.05`;
- target power — `0.80`.

Почему baseline `0.5`: для бинарной метрики это консервативная no-prior точка,
где дисперсия максимальна. Engine также добавляет sensitivity branches для
baseline rates `0.2`, `0.5`, `0.8`.

#### Почему это лучше V1

V2 явно фиксирует:

```text
unique tasks are the inference/planning unit
```

Repeated attempts могут поддерживать reliability/pass@k analysis, но не
умножают iid sample size для MDE/CI planning. Это защищает от типичной ошибки:
считать 40 tasks x 3 attempts как 120 независимых samples.

#### Какие diagnostics есть сейчас

Engine и stats layer покрывают:

- planned MDE по unique tasks;
- Wilson CI width;
- power/budget curve;
- required tasks для requested MDE;
- baseline-rate sensitivity;
- effective sample size caveat;
- leaderboard rank-resolution proxy;
- diagnostic slice task count;
- diagnostic slice Wilson CI width;
- regression non-inferiority margin checks;
- missingness warnings/refusals;
- floor/ceiling warnings;
- multiplicity policy;
- claim cards и not-allowed claims.

#### Как выбирается recommended design

Engine не берет первый вариант. Он считает candidates и score:

- approved лучше warning;
- warning лучше refused;
- structural statistical issues штрафуются;
- при одинаковом status предпочтительнее дешевый достаточный budget;
- stronger alternative остается доступной как вариант.

Пользователь видит:

- `budget_minimum`;
- `recommended`;
- `stronger`;
- `narrowed_claim`.

Это делает Advisor объяснимым: не просто "запрещено" или "можно", а
"вот что поддерживает текущий budget, вот что даст больший budget, вот какой
claim придется сузить".

### BA5.5: post-run statistical report

Реализован `benchmark_advisor/v2_report.py`.

Он принимает `OutcomeTensor` и возвращает `StatisticalReport`.

Поддержано:

- pairwise: task-level paired delta и bootstrap CI;
- leaderboard: pass-rate summaries и task-bootstrap rank stability;
- regression: non-inferiority margin handling;
- diagnostic: descriptive slice diagnostics;
- missingness summary и status downgrade;
- multiplicity summary;
- allowed / not-allowed claims.

Это не запускает evaluator и не меняет scoring. Это слой интерпретации уже
полученных outcomes.

### BA5.6: Studio statistical workbench

Frontend Stage 0 теперь использует v2 API и typed Zod schemas.

Пользователь видит:

- status и launchability;
- claim card;
- method card;
- MDE / CI width / power curve;
- assumptions panel;
- alternatives;
- evaluated candidates;
- issues и repair options;
- guide citations;
- typed export preview;
- post-run report fixture/view.

Edit UI вызывает `/api/advisor/v2/validate`, после чего backend пересчитывает
status, issues, power analysis, assumptions, export config и launchability.

## 4. Что сделано в BA6

BA6 связывает approved/warning v2 plan с corpus generation, но только через
guarded layer.

### BA6.1: carry advisor state into Collect

Studio state получил `advisorCarry`.

Carry сохраняет:

- `StatisticalPlan`;
- `ExportConfig`;
- advisor status;
- launchable flag;
- task budget;
- attempts;
- goal strategy;
- server scope;
- assumptions;
- sandbox requirements.

Если plan refused или needs clarification, он не становится launchable state.

### BA6.2: validate/edit UI

Пользователь может редактировать:

- budget;
- attempts;
- candidate models;
- server scope;
- target effect;
- task distribution;
- sandbox fields.

После edits Studio вызывает `/api/advisor/v2/validate` и показывает all issues.

### BA6.3: guarded corpus launch backend

Реализован `benchmark_advisor/v2_launch.py`.

Launch разрешен только если:

- запрос пришел из Studio UI;
- advisor status `approved` или `warning`;
- есть explicit confirmation;
- target — только `scripts/build_corpus.py`;
- export остается dry-run-only advisor handoff;
- sandbox confirmed, если sandbox required.

Command preview строится deterministic образом:

```text
python scripts/build_corpus.py --out data/advisor_runs/<launch_key> --budget <tasks> --strategies <mapped_strategies> ...
```

### BA6.4: job status and artifacts UI

Collect показывает:

- confirmation controls;
- queued/running/succeeded/failed status;
- command preview;
- logs;
- artifact paths для goals/specs/traces/coverage.

### BA6.5: corpus-only first handoff

Это сознательная safety boundary:

- можно запускать corpus/specs/traces path;
- нельзя запускать `dmcp bench`;
- нельзя запускать leaderboard/eval;
- нельзя запускать paid eval без отдельного future approval.

## 5. Что пока не нужно переобещать

Текущий BA5/BA6 — рабочий v2 MVP, но не финальный production advisor.

Честные ограничения:

- MDE/power пока planning heuristic, не final proof.
- No-prior baseline defaults не заменяют empirical calibration на реальных
  исторических логах.
- RAG/stat-agent не используется как источник решений и не нужен для MVP.
- Intent robustness еще остается BA7 задачей.
- Handoff сейчас corpus/specs/traces only.
- Если под "переносится дизайн далее" понимать full downstream benchmark/eval
  pipeline, это еще не сделано: дизайн carried into Collect и guarded launch
  строит corpus job, но не превращается автоматически в full leaderboard/eval.
- Launch jobs сейчас in-memory, что нормально для локального Studio MVP, но не
  является durable production queue.

## 6. Как это объяснять аудитории

### Короткая формулировка

Benchmark Advisor V2 делает benchmark planning статистически явным до запуска.
Он не просто говорит "можно запускать" или "нельзя". Он показывает, какой claim
поддерживает дизайн, какой MDE получится, какие assumptions важны, что даст
больший budget, какие claims запрещены, и как безопасно перейти к corpus
generation.

### Почему это важно

DynamicMCPBench оценивает trace-grounded tool-use behavior. Но качество
результата зависит не только от evaluator, а от того, был ли benchmark design
честным до запуска:

- достаточно ли unique tasks;
- не перепутали ли diagnostic и model-selection claim;
- не посчитали ли repeated attempts как независимые samples;
- зафиксировали ли non-inferiority margin до regression check;
- указали ли missingness и multiplicity policies;
- не запускаем ли expensive pipeline до явного approval.

Advisor V2 закрывает именно этот слой.

### Технический тезис

Статистика теперь не пост-фактум пояснение, а часть алгоритма выбора дизайна.
`Statistical Engine` перебирает candidates, считает MDE/CI/diagnostics,
валидирует каждый вариант, выбирает recommended design и показывает alternatives.

Это делает benchmarking доступнее: пользователю не нужно самому помнить все
статистические caveats, но система не прячет математику и не заменяет ее LLM
объяснениями.

## 7. Ключевые файлы

Backend:

- `benchmark_advisor/v2_schema.py`
- `benchmark_advisor/guide_citations.py`
- `benchmark_advisor/v2_engine.py`
- `benchmark_advisor/stats.py`
- `benchmark_advisor/v2_service.py`
- `benchmark_advisor/v2_report.py`
- `benchmark_advisor/v2_launch.py`
- `dmcp-studio/backend/app.py`

Frontend:

- `dmcp-studio/frontend/src/stages/Design.tsx`
- `dmcp-studio/frontend/src/stages/Collect.tsx`
- `dmcp-studio/frontend/src/api/schemas.ts`
- `dmcp-studio/frontend/src/api/client.ts`
- `dmcp-studio/frontend/src/store/reducer.ts`

Tests:

- `tests/test_benchmark_advisor_v2_schema.py`
- `tests/test_benchmark_advisor_guide_citations.py`
- `tests/test_benchmark_advisor_v2_engine.py`
- `tests/test_benchmark_advisor_v2_report.py`
- `dmcp-studio/backend/tests/test_studio_advisor.py`
- `dmcp-studio/frontend/src/stages/Design.test.tsx`
- `dmcp-studio/frontend/src/stages/Collect.test.tsx`
- `dmcp-studio/frontend/src/store/reducer.test.ts`
