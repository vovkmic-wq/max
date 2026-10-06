# Контракты сервисов и адаптеров

Это API будущего приложения, а не описание уже реализованных endpoint. Контракты отделяют редакционные решения от доставки и дают возможность менять SDK и мессенджеры без переписывания основного потока.

## Адаптер источника

`capabilities()` возвращает fetch_history, receive_events, fetch_media, read_metrics и ограничения. `validate_access(source)` возвращает available, unsupported, needs_auth или forbidden с safe_reason. `collect(source, cursor, limits)` возвращает materials, next_cursor, complete, retry_after и ошибки отдельных элементов.

MaterialEnvelope содержит source_id, external_id при наличии, canonical_url, title, text, language_hint, published_at, fetched_at, raw_ref, attachments, rights_policy_id и content_revision. При неполной странице cursor не перескакивает через несохранённые записи. Источник может поддерживать только события; история не предполагается.

## OpenCode адаптер

`generate(task, context, deadline, cancellation)` возвращает проверяемый EditorResult либо типизированную ошибку. Адаптер сохраняет runtime_version, API snapshot hash, model, session_id, usage, price_version и duration. Он умеет отменять задания и завершать сессию. `probe()` проверяет совместимость, а live тест дополнительно проверяет осмысленный видимый ответ.

Минимальная форма результата:

```json
{
  "schema_version": "1.0",
  "task_id": "UUID_FROM_INPUT",
  "task_type": "draft",
  "status": "completed",
  "decision": "review",
  "reason_codes": ["EDITOR_REVIEW_REQUIRED"],
  "source_ids": ["MATERIAL_ID_FROM_INPUT"],
  "language": "ru",
  "title": "Заголовок",
  "body": "Текст черновика со ссылкой на источник",
  "claims": [
    {
      "text": "Проверяемое утверждение",
      "kind": "fact",
      "evidence": [
        {
          "material_id": "MATERIAL_ID_FROM_INPUT",
          "span_id": "SPAN_ID_FROM_INPUT"
        }
      ]
    }
  ],
  "confidence": 0.8,
  "warnings": [],
  "payload": {}
}
```

task_type: classify, cluster, translate, draft, verify, bootstrap, growth_plan. status: completed, insufficient_evidence, failed. decision: accept, reject, review, duplicate, update. confidence — оценка модели, не вероятность истинности. payload имеет отдельную схему по типу задания: классификация — relevance и topic_matches; cluster — story_candidates и различия; translate — alignment и сохранённые числа; verify — результаты проверки claims; bootstrap — варианты оформления и календарь; growth_plan — гипотезы, действие, бюджет и метрика.

Сервис реализует строгие discriminated schemas для каждого task_type. task_id и все material_id должны принадлежать входу. Связи evidence проверяются по сохранённым span, а не по выдуманной модели ссылке. JSON с лишними полями или неверным типом не принимается. Пустой текст для draft — ошибка; для classify и cluster текст может отсутствовать в соответствующей схеме. До двух ограниченных исправлений формата, затем review либо failed.

Коды редакционных решений: OUT_OF_SCOPE, EXCLUDED_TOPIC, STALE_SOURCE, EXACT_DUPLICATE, SAME_EVENT, EVENT_UPDATE, RIGHTS_UNCLEAR, UNSUPPORTED_LANGUAGE, DISPUTED_FACT, INSUFFICIENT_EVIDENCE, LENGTH_EXCEEDED, BUDGET_EXCEEDED, EDITOR_REVIEW_REQUIRED, SOURCE_UNAVAILABLE. Разработчик документирует новые коды, сохраняя стабильность старых.

## Адаптер публикации

`inspect_channel(chat_id)` возвращает метаданные, права и capabilities. `publish(intent)` возвращает confirmed с external_id и permalink; rejected с однозначной причиной; либо unknown. `reconcile(intent)` возвращает подтверждённое совпадение, неоднозначность или отсутствие доказательства. Отсутствие доказательства само по себе не разрешает повтор.

`edit(publication, approved_revision)` и `remove(publication, approved_action)` доступны только при принятой capability. Нельзя полагаться на автоматические повторы write запросов SDK: их политика должна учитывать неизвестный исход. idempotency_key приложения не передаётся как несуществующий параметр MAX.

## API управления приложением

| Метод и путь | Действие |
| --- | --- |
| GET /health/live | Процесс отвечает |
| GET /health/ready | База, миграции, конфигурация и локальные компоненты готовы |
| GET /api/v1/integrations/status | Раздельные статусы OpenCode, MAX и каждого источника |
| POST /api/v1/config/validate | Проверка кандидата конфигурации без активации |
| POST /api/v1/config/activate | Применение проверенной версии владельцем |
| GET /api/v1/channels | Каналы и их режимы |
| POST /api/v1/channels/{id}/connect | Привязка MAX и проверка прав |
| POST /api/v1/channels/{id}/pause | Остановка внешних отправок |
| POST /api/v1/channels/{id}/resume | Возобновление с проверкой очереди |
| GET /api/v1/sources | Состояние источников |
| POST /api/v1/sources/{id}/collect | Одно ограниченное задание сбора |
| GET /api/v1/drafts | Черновики и причины решений |
| POST /api/v1/drafts/{id}/approve | Одобрение указанной revision и content_hash |
| POST /api/v1/drafts/{id}/reject | Отказ с причиной |
| GET /api/v1/publications | История и неизвестные результаты |
| POST /api/v1/publications/{id}/reconcile | Запуск сверки |
| POST /api/v1/publications/{id}/correct | Одобренное исправление |
| GET /api/v1/reports | Отчёты и экспорт |
| POST /webhooks/max | Проверенный входящий Update |
| POST /webhooks/telegram | Проверенный входящий Update |

Роли owner, editor и viewer проверяются на сервере. Входящие webhook не используют сессию панели, а проверяют секрет соответствующего адаптера. Изменения требуют revision, audit actor и Idempotency-Key приложения. Ответ 409 означает конфликт ревизии, 422 — невалидную конфигурацию; ошибки имеют code, safe_message, trace_id и retryable. Значения секретов никогда не входят в ответы.

Внешняя недоступность источника не делает весь процесс неживым. ready не является свидетельством принятой live интеграции; панель отдельно показывает enabled, available и live_verified_at по каждой capability.
