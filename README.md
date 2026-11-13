# hermes-dlc

Дополнение для [Hermes Agent](https://github.com/NousResearch/hermes-agent):

- **Планирование** — триаж сложности, понимание задачи, декомпозиция по компетенциям (скилл `dlc:task-planning`).
- **Библиотека агентов-специалистов** — каждый агент = профиль Hermes со своим SOUL; поиск по
  компетенции, создание узких специалистов, статистика, уроки, эволюция SOUL с версиями.
- **Kanban** — встроенная доска Hermes; DLC добавляет протокол и автоучёт результатов.
- **Память** — self-hosted Honcho на локальных эмбеддингах Google EmbeddingGemma.
- **RAG** — локальная база знаний проекта на тех же эмбеддингах.

Архитектура: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). План: [docs/ROADMAP.md](docs/ROADMAP.md).

## Структура

```
dlc/                      плагин Hermes (plugin.yaml + register(ctx))
  library.py              библиотека агентов: find / forge / learn / evolve / retire
  rag.py, embed.py        локальный RAG, клиент эмбеддингов
  tools.py                10 инструментов dlc_*
  skills/                 dlc:task-planning, dlc:agent-forge, dlc:retrospective
infra/honcho/             self-hosted Honcho + EmbeddingGemma (Ollama)
config/config.snippet.yaml  фрагмент ~/.hermes/config.yaml
tests/                    pytest без Hermes (фейковый эмбеддер)
```

## Установка

```bash
# 1. Эмбеддинги + память
ollama pull embeddinggemma
bash infra/honcho/setup.sh          # первый запуск создаст .env — впиши ключ LLM и запусти снова

# 2. Плагин
hermes plugins install MisterReds/hermes-dlc/dlc --enable
# или для разработки:
ln -s "$PWD/dlc" ~/.hermes/plugins/dlc && hermes plugins enable dlc

# 3. Kanban
hermes kanban init
hermes gateway start

# 4. Конфиг: влить config/config.snippet.yaml в ~/.hermes/config.yaml
```

## Тесты

```bash
pip install pytest && python -m pytest -q
```
