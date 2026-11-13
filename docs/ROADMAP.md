# Roadmap

## Фаза 0 — проверка фундамента (вручную, до всего остального)
- [ ] `ollama pull embeddinggemma`; `curl .../v1/embeddings` возвращает 768 чисел.
- [ ] `infra/honcho/setup.sh` → `/health` ok; `hermes memory status` показывает honcho.
- [ ] Диалог из 10+ сообщений → `hermes honcho peers` / `honcho_search` находит факты о тебе.
      Проверить, что deriver реально пишет выводы (логи контейнера `deriver`).
- [ ] `hermes kanban init`, `hermes gateway start`, тестовая задача на default-профиль доходит до done.

## Фаза 1 — установка DLC (этот репозиторий)
- [ ] `hermes plugins install MisterReds/hermes-dlc/dlc --enable` (или симлинк `dlc/` в `~/.hermes/plugins/dlc`).
- [ ] `hermes plugins validate ~/.hermes/plugins/dlc` — без ошибок.
- [ ] В чате: `/agents` → «библиотека пуста»; `dlc_rag_ingest` по своему проекту; `dlc_rag_search`.
- [ ] Реальная задача moderate-уровня: проверить, что оркестратор проходит триаж → find → forge → kanban.

## Фаза 2 — калибровка
- [ ] Собрать 20–30 пар «потребность → правильный агент», подобрать `DLC_REUSE_AT/ADAPT_AT`.
- [ ] Проверить, что `--description` профилей используется kanban-декомпозером.
- [ ] Ограничить разрастание: правило слияния агентов с близкими специализациями (sim > 0.9).

## Фаза 3 — качество исполнения
- [ ] Ревьюер-специалист: подбор ревьюера через `dlc_agent_find` для `review_dispatch`.
- [ ] Хук `pre_verify` для воркеров: принудительная самопроверка по DoD.
- [ ] Автоматическая ретроспектива по cron (`hermes cron`) раз в N часов.
- [ ] Скиллы агентов: перенос повторяющихся уроков из SOUL в скиллы профиля (`skill_manage`).

## Фаза 4 — масштаб и наблюдаемость
- [ ] RAG: sqlite-vec вместо brute-force при >100k чанков; реранкер.
- [ ] Дашборд библиотеки (dashboard-плагин Hermes): агенты, success rate, версии SOUL, diff.
- [ ] A/B: тот же класс задач на двух версиях агента, откат по метрикам.
- [ ] Экспорт/импорт библиотеки (`hermes profile export` + dlc.db) для переноса между машинами.
