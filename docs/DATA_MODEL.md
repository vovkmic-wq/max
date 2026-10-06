# Модель данных и состояния

Идентификаторы внутренних сущностей — UUID. Время хранится в UTC, расписание отображается в зоне канала. Внешние идентификаторы MAX и Telegram хранить строками с сохранением точности int64; преобразование к требуемому типу выполняет адаптер. Все изменяемые редакционные объекты имеют revision и optimistic locking.

## Сущности

| Сущность | Основные поля | Ограничения |
| --- | --- | --- |
| Channel | id, profile_id, platform, external_chat_id, bot_account_ref, capabilities, state | Уникальная пара platform и external_chat_id |
| ConfigVersion | id, revision, topic_hash, source_hash, validated_snapshot, activated_at, actor | Активный снимок неизменяем |
| Source | id, type, endpoint, channel_ids, interval, rights, trust, capability_state | Уникальный id; секрет только по ссылке |
| SourceCursor | source_id, cursor, etag, last_modified, last_success, next_due | Контрольная точка обновляется после постоянной записи страницы |
| InboxEvent | platform, event_key, payload_ref, received_at, processed_at | unique(platform, event_key) |
| Material | source_id, external_id, canonical_url, language, raw_hash, text_hash, event_time, fetched_at, revision | unique(source_id, external_id, revision) при наличии external_id |
| RawBlob | id, sha256, relative_path, mime, size, rights_ref, expires_at | Содержимое адресуется по хешу |
| Story | id, event_signature, entity_features, event_date, state | Кластер допускает ручное разделение |
| StoryMaterial | story_id, material_id, reason, score, algorithm_version | unique(story_id, material_id) |
| ChannelDecision | channel_id, story_id, config_id, relevance, reason_codes, state | Решение зависит от темы канала |
| GenerationRun | job_id, task_type, opencode_version, model, session_id, prompt_hash, usage, cost, state | Все попытки сохраняются отдельно |
| DraftRevision | draft_id, revision, channel_id, story_id, story_revision, body, claims, sources, config_id, content_hash | Ревизия не меняется после сохранения |
| Approval | draft_id, revision, actor, approved_hash, config_id, approved_at, revoked_at | Только для конкретного текста и конфигурации |
| QualityCheck | draft_id, revision, check_type, result, evidence, version | Одна ревизия имеет набор проверок |
| PublicationIntent | channel_id, story_id, story_revision, draft_id, draft_revision, operation, scheduled_at, key, state | unique(key); уникальность события по каналу и story_revision для create |
| PublicationAttempt | intent_id, attempt_no, started_at, result_class, external_id, safe_error | Не хранить токены и полные HTTP заголовки |
| Publication | intent_id, external_message_id, permalink, published_at, body_hash, revision | unique(channel_id, external_message_id) |
| Job | type, subject_id, config_id, due_at, priority, attempts, lease_until, fencing_token, state | unique(idempotency_key) |
| BudgetLedger | channel_id, action_ref, reservation, actual_cost, currency, price_version, state | Расход резервируется транзакционно |
| Campaign | channel_id, hypothesis, destination, cap, approvals, spend, outcome | Состояния planning, approved, running, completed, stopped |
| MetricSnapshot | channel_id, publication_id, metric, value, measured_at, origin | origin: api, import, manual, calculated |
| AuditEvent | actor, action, entity, revision, trace_id, timestamp, safe_diff | Приложение не изменяет ранее записанные события |

## Жизненные циклы

Материал: collected → normalized → classified → linked_to_story; альтернативы quarantined, rejected и duplicate_linked. Повтор не уничтожает историю происхождения. Исправленный исходник создаёт новую revision с прежним внешним идентификатором.

Черновик: drafting → validating → review_pending или approved → scheduled → publishing → published. Альтернативы rejected, stale, failed и cancelled. В autopublish approved означает автоматическое прохождение всех правил, с записью actor=policy_engine; спорный материал остаётся review_pending.

Intent: pending → sending → confirmed. Если отказ однозначен, возможны retry_wait или failed. Если результат потенциально применён на стороне площадки — unknown → reconciling → confirmed либо review_required. Повтор допустим только после доказательства отсутствия публикации или явного решения редактора, зафиксированного в аудите.

Job: queued → leased → succeeded. Альтернативы retry_wait, dead_letter, cancelled. Истёкший lease возвращает обычное вычислительное задание в очередь; публикационное задание сначала проверяет intent, поскольку внешняя операция могла завершиться.

## Ключи и транзакции

Ключ сбора включает source_id и идентификатор страницы либо события. Ключ редакционной генерации включает тип задания, story revision, канал, config_id и prompt_hash. Ключ create публикации включает channel_id и story revision; изменение текста до публикации заменяет содержимое того же intent после аннулирования одобрения, а не создаёт вторую публикацию.

Сохранение материала и продвижение cursor выполняются в одной транзакции после обработки страницы. Создание intent, занятие слота и резерв бюджета выполняются атомарно. Перевод расхода из reservation в actual происходит по результату провайдера; неизвестная стоимость не считается нулевой.

## Хранение и очистка

Исходные HTML и тексты: начальная retention 30 суток, если право хранения позволяет; использованные доказательства и происхождение опубликованного материала сохраняются не менее 365 суток. Временные медиа очищаются после подтверждения и срока retention. Индексы точных повторов и история публикаций сохраняются при переносе и не удаляются с сырьём. Семантическое сравнение использует 180 дневное окно по умолчанию.

Удаление по запросу правообладателя сохраняет минимальный факт снятия, хеш и причину без запрещённого содержимого. Конкретный срок хранения уточняется владельцем по условиям источников. Миграции, backup manifest и версии алгоритмов обязательны для воспроизводимости.
