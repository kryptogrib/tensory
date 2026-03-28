# LoCoMo Benchmark for Tensory

Тестирование Tensory на бенчмарке LoCoMo (Long-term Conversational Memory, ACL 2024).

## Два способа запуска

### 1. AMB (Agent Memory Benchmark) — рекомендуемый

Стандартный industry benchmark framework от Vectorize.io. Честное сравнение с Hindsight, Cognee, Mem0 и другими.

**Расположение:** `/Users/chelovek/Work/agent-memory-benchmark/`

#### Требуемые ключи в `.env`

```bash
# /Users/chelovek/Work/agent-memory-benchmark/.env
GEMINI_API_KEY=...          # Обязателен (AMB проверяет при старте)
OPENAI_API_KEY=...          # Для embeddings (text-embedding-3-small)
ANTHROPIC_API_KEY=...       # Для Haiku extraction (через proxy)
ANTHROPIC_BASE_URL=http://localhost:8317  # CLIProxyAPI proxy
GROQ_API_KEY=...            # Бесплатная модель для ответов (default)
OPENROUTER_API_KEY=sk-or-...  # Для выбора любой модели ответов
```

#### Команды запуска

```bash
cd /Users/chelovek/Work/agent-memory-benchmark

# Быстрый тест (3 вопроса, ~3 мин, ~$0.01)
OMB_ANSWER_LLM=openrouter \
OMB_ANSWER_MODEL=meta-llama/llama-4-scout-17b-16e-instruct \
OMB_JUDGE_LLM=openrouter \
OMB_JUDGE_MODEL=google/gemini-2.5-flash-lite \
uv run omb run --dataset locomo --split locomo10 --memory tensory --query-limit 3

# 25 вопросов (~5 мин, ~$0.06 extraction + модель ответов)
# Те же переменные, только --query-limit 25

# Полный бенчмарк (1540 вопросов, ~30 мин, ~$0.50-2.00)
# Те же переменные, без --query-limit
```

#### Выбор модели ответов (OMB_ANSWER_LLM + OMB_ANSWER_MODEL)

| Вариант | Env vars | Стоимость | Примечание |
|---------|----------|-----------|------------|
| **Groq (default)** | не задавать | Бесплатно | Лимит 30 req/min |
| **Groq через OpenRouter** | `openrouter` + `meta-llama/llama-4-scout-17b-16e-instruct` | ~$0.10/1540q | Без лимитов |
| **Gemini Pro (как Hindsight)** | `openrouter` + `google/gemini-2.5-pro` | ~$1.00/1540q | Honest comparison |
| **Gemini Flash** | `openrouter` + `google/gemini-2.5-flash` | ~$0.20/1540q | Хороший баланс |
| **Claude Sonnet** | `openrouter` + `anthropic/claude-sonnet-4` | ~$3.00/1540q | Дорого |
| **GPT-4o-mini** | `openai` + `gpt-4o-mini` | ~$0.30/1540q | Нужен OPENAI_API_KEY |

#### Выбор модели judge (OMB_JUDGE_LLM + OMB_JUDGE_MODEL)

Рекомендуется `google/gemini-2.5-flash-lite` через openrouter (как у конкурентов).

#### Что получаешь

- `outputs/locomo/tensory/rag/locomo10.json` — полный результат с per-question accuracy
- Таблица accuracy в терминале
- Cost summary от Tensory provider

#### Результаты конкурентов (из AMB manifest)

| Memory System | Answer LLM | Accuracy | Queries |
|---|---|:---:|:---:|
| **Hindsight** | Gemini 3.1 Pro | 92.0% | 1540 |
| **Cognee** | Gemini 3.1 Pro | 80.3% | 152 |
| **Hybrid Search** (Qdrant) | Gemini 3.1 Pro | 79.1% | 1540 |
| **Tensory** | Groq gpt-oss-120b | **88-92%** | 25 |

---

### 2. Свой runner — для быстрой итерации

Простой пайплайн для отладки extraction/search без overhead AMB.

**Расположение:** `benchmarks/locomo/` в tensory repo

#### Требуемые ключи в `.env`

```bash
# /Users/chelovek/Work/tensory/.env
OPENAI_API_KEY=...          # Для embeddings
ANTHROPIC_API_KEY=...       # Для Haiku extraction + Sonnet answers
ANTHROPIC_BASE_URL=http://localhost:8317
```

#### Команды

```bash
cd /Users/chelovek/Work/tensory

# Полный прогон (ingest + answer), 10 вопросов
uv run python -m benchmarks.locomo --conversation 0 --limit 10 -v

# Только ответы (skip ingest, reuse existing DB)
uv run python -m benchmarks.locomo --conversation 0 --limit 10 --skip-ingest -v

# Вопросы 6-10 (offset + limit)
uv run python -m benchmarks.locomo --conversation 0 --offset 5 --limit 5 --skip-ingest -v
```

#### CLI аргументы

| Аргумент | Default | Описание |
|----------|---------|----------|
| `--conversation` | 0 | Индекс диалога (0-9) |
| `--limit` | все | Макс вопросов |
| `--offset` | 0 | Пропустить N вопросов |
| `--search-limit` | 10 | Claims per search query |
| `--skip-ingest` | false | Reuse existing DB |
| `--db` | `.cache/tensory_locomo.db` | Путь к БД |
| `-v` | false | Verbose logging |

#### Метрика

Token-level F1 (строже чем LLM-judge в AMB). Наш результат: **F1 ~0.52** на 10 вопросах.

---

## Архитектура Tensory в AMB

```
LoCoMo JSON → AMB loads Documents (with session timestamps)
    │
    ▼
TensoryMemoryProvider.ingest()
    ├─ Prepend [Session date: ...] to content
    ├─ store.add() → Haiku extracts claims with dates in text
    └─ OpenAI embeds claims
    │
    ▼
TensoryMemoryProvider.retrieve()
    ├─ store.search() → hybrid FTS5 + vector + graph → RRF
    └─ Returns top-k claims as Documents
    │
    ▼
AMB Answer LLM (Groq/Gemini/etc) generates answer
    │
    ▼
AMB Judge LLM evaluates CORRECT/WRONG
```

**Ключевые оптимизации (уже реализованы):**
1. Session date injection — даты сессий prepend к content для temporal reasoning
2. Temporal extraction prompt — LLM встраивает абсолютные даты в claim text
3. FTS5 query sanitization — спецсимволы ?, ' не ломают поиск
4. Cost tracking — provider считает LLM + embedding расходы

**Известные ограничения:**
- Entity crowding: популярные entities (Caroline+counseling) затапливают rare facts
- Нет per-entity diversity caps (запланировано для search.py core)
- Extraction non-deterministic: accuracy колеблется 88-92% между прогонами

## Стоимость

| Компонент | За 1 диалог | За 10 диалогов |
|-----------|:-----------:|:--------------:|
| Haiku extraction (19 sessions) | ~$0.06 | ~$0.60 |
| OpenAI embeddings | ~$0.001 | ~$0.01 |
| Answer LLM (Groq) | бесплатно | бесплатно |
| Judge LLM (Gemini Flash Lite) | ~$0.01 | ~$0.10 |
| **ИТОГО** | **~$0.07** | **~$0.70** |
