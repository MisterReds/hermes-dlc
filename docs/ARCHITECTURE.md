# Архитектура Hermes DLC

Основано на исходниках `NousResearch/hermes-agent` (ноябрь 2026) и `plastic-labs/honcho`.
Правило Hermes: плагин не трогает ядро, только `ctx`-API, хуки и скиллы. DLC следует ему.

## Что даёт Hermes «из коробки» и что добавляет DLC

| Слой | Hermes | DLC |
|---|---|---|
| Канбан | SQLite-доска, диспетчер в gateway, воркер = профиль (`hermes -p <assignee>`), хуки `kanban_task_*` | Протокол планирования, автозапись результатов прогонов по хукам |
| Агенты | Профили: свой `SOUL.md`, модель, скиллы, `--description` для маршрутизации | Библиотека: поиск по компетенции, forge, статистика, уроки, эволюция SOUL с версиями, retire |
| Память | `memory.provider: honcho` (+ встроенные MEMORY.md/USER.md) | Self-hosted Honcho на локальных эмбеддингах EmbeddingGemma |
| Знания | Нет RAG-подсистемы | `dlc_rag_ingest` / `dlc_rag_search` на тех же локальных эмбеддингах |
| Самоулучшение | `skill_manage`, curator, `/learn` | Ретроспектива → уроки → новая версия SOUL конкретного агента |

## Поток работы

```
Задача пользователя
  └─ оркестратор (default-профиль) + скилл dlc:task-planning
       1. понимание: цель, артефакты, DoD, ограничения, неизвестные (clarify)
       2. триаж: trivial | simple | moderate | complex | novel
          trivial/simple → делает сам
       3. декомпозиция по КОМПЕТЕНЦИЯМ, не по ролям
       4. на каждую подзадачу: dlc_agent_find(need) → reuse | adapt | forge
              forge/adapt → dlc_agent_forge (скилл dlc:agent-forge) → новый профиль ag-<slug>
       5. kanban_create(assignee=ag-<slug>, parents=[...]) + DoD в теле
  └─ диспетчер gateway запускает воркеров: hermes -p ag-<slug>
       воркер видит WORKER_PROTOCOL: работать в зоне компетенции, блокировать чужое,
       самопроверка по DoD, раздел 'Lessons:' в summary
  └─ хук kanban_task_completed / kanban_task_blocked → runs (dlc.db)
  └─ оркестратор: dlc_retro_pending → скилл dlc:retrospective
       → dlc_run_record (оценка) → dlc_agent_learn (уроки) → dlc_agent_evolve (SOUL vN+1)
       → dlc_agent_retire для систематически слабых
```

## Хранилище

`~/.hermes/dlc/` — общее для всех профилей (воркеры работают в своих `HERMES_HOME`,
поэтому `plugin_data_dir()` не подходит — он следует активному профилю).

- `dlc.db` — `agents`, `runs`, `lessons`, `chunks` (RAG).
- `history/<slug>/vN.SOUL.md` — все версии SOUL каждого агента (откат = копирование файла).
- Профили агентов: `~/.hermes/profiles/ag-<slug>/` (стандартные профили Hermes).

## Подбор агента

`rank = similarity × (0.75 + 0.25 × success_rate)`; success_rate сглажен по Лапласу (новый = 0.5).
Пороги (env): `DLC_REUSE_AT=0.78`, `DLC_ADAPT_AT=0.60` для косинуса EmbeddingGemma.
Без эмбеддера — fallback на Jaccard по токенам. Пороги откалибровать на реальных данных (ROADMAP, фаза 2).

## Эмбеддинги

Один локальный эндпоинт для всего: Ollama `embeddinggemma` (Google, 768d, OpenAI-совместимый API).
- Honcho: `EMBEDDING_VECTOR_DIMENSIONS=768` задаётся ДО первой миграции (размер pgvector-колонки).
- DLC: префиксы задач EmbeddingGemma (`task: search result | query:` / `title: none | text:`).

## Разграничение памяти

| Что | Где |
|---|---|
| Кто пользователь, предпочтения, стиль, история диалогов | Honcho |
| Документация, код, спецификации проекта | DLC RAG |
| Как делать работу в конкретной области | SOUL агента (уроки) + его скиллы |
| Как планировать | скиллы `dlc:*` + память оркестратора |
