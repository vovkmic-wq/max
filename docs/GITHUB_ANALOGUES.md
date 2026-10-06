# Аналогичные проекты на GitHub

Изучены шесть репозиториев: README, дерево файлов и выбранные исходники на фиксированных коммитах. Они покрывают разные части задачи. Среди этих проектов не найден готовый комплект, одновременно реализующий OpenCode V2, редакционный цикл MAX, перенос состояния и коммерческое развитие канала. Рекомендация — собственное приложение с небольшими адаптерами и проверенными зависимостями.

Ни один проект не устанавливался и не запускался. Выводы о надёжности ниже основаны на структуре и прочитанном коде, а не на испытании в production. Полный список просмотренных файлов находится в [inspected-files.json](research/inspected-files.json), метаданные и коммиты — в [github-snapshot.json](research/github-snapshot.json).

## Сравнение

| Проект | Организация | Применимо в нашем проекте | Что требует доработки |
| --- | --- | --- | --- |
| [max-messenger/max-bot-api-client-ts](https://github.com/max-messenger/max-bot-api-client-ts) | API модули, middleware, события, webhook, примеры и tests | Типизированная граница MAX, проверка webhook, последовательность по ключу | SDK не заменяет постоянную очередь, дедупликацию и редакционную политику |
| [max-messenger/max-botapi-python](https://github.com/max-messenger/max-botapi-python) | Bot, Dispatcher, methods, models, connection, примеры webhook | Организация Python адаптера и событий | В изученном transport указан botapi.max.ru; совместимость с текущим API нужно проверить |
| [yshuvaev/max_bot](https://github.com/yshuvaev/max_bot) | Node мост, routes, admin API, CLI, deploy и backup настройки | Маршруты источник → назначения, сбор альбомов, hot reload и администрирование | Очередь в памяти, discovery зависит от getAllChats; это мост перепубликации |
| [obodnikov/telegram-rss-news-bot](https://github.com/obodnikov/telegram-rss-news-bot) | RSS цикл, сменяемые переводчики, форматирование и варианты установки | Простой поток RSS → перевод → пост, интерфейс переводчика | seen_entries — Set в процессе; идентичность записи не равна смысловой дедупликации |
| [Rongronggg9/RSS-to-Telegram-Bot](https://github.com/Rongronggg9/RSS-to-Telegram-Bot) | web, db, command, migrations, Docker и подробная документация | Постоянные подписки, entry hashes, ETag и Last Modified | Цель — доставка RSS, а не проверка фактов и развитие канала; лицензия AGPL-3.0 требует отдельного решения при выборе кода |
| [different-ai/opencode-scheduler](https://github.com/different-ai/opencode-scheduler) | Plugin, job JSON, supervisor, scoped logs, адаптеры планировщиков ОС | Scope проекта, запрет перекрытий, тайм аут и история запусков | Windows путь имеет отличия; старый формат permissions нуждается в проверке с V2 |

## Проверенные фрагменты

### Клиент MAX на TypeScript

На коммите `d6d330b5915236055856ca382380be7cbf9517c5` [client.ts](https://github.com/max-messenger/max-bot-api-client-ts/blob/d6d330b5915236055856ca382380be7cbf9517c5/src/core/network/api/client.ts#L7) задаёт platform-api2.max.ru и передаёт токен заголовком. [webhook.ts](https://github.com/max-messenger/max-bot-api-client-ts/blob/d6d330b5915236055856ca382380be7cbf9517c5/src/core/network/webhook.ts#L169) проверяет secret, а [keyed-executor.ts](https://github.com/max-messenger/max-bot-api-client-ts/blob/d6d330b5915236055856ca382380be7cbf9517c5/src/core/keyed-executor.ts#L2) последовательно исполняет задачи с одним ключом через Map обещаний. Это полезно для порядка внутри процесса; сохранность после рестарта из такого механизма не следует.

### Клиент MAX на Python

На коммите `4a286baa06d38f2db9f7244d94f89508743f8fee` [base.py](https://github.com/max-messenger/max-botapi-python/blob/4a286baa06d38f2db9f7244d94f89508743f8fee/maxapi/connection/base.py#L38) содержит другой адрес API. Последний коммит default branch в снимке — 30 июля 2025 года. Организационная принадлежность не заменяет проверку актуальности transport. Для выбранного Python стека первой версии предпочтителен небольшой собственный HTTP адаптер MAX; принятие библиотеки возможно после контрактной проверки.

### Мост Telegram в MAX

На коммите `05b0855b85e1464ce454281d3f25cc88944f22b1` [index.js](https://github.com/yshuvaev/max_bot/blob/05b0855b85e1464ce454281d3f25cc88944f22b1/src/index.js#L379) хранит queue и mediaGroupBuffer в памяти. [bridge-init.js](https://github.com/yshuvaev/max_bot/blob/05b0855b85e1464ce454281d3f25cc88944f22b1/scripts/bridge-init.js#L152) вызывает getAllChats. С учётом [изменения GET /chats](https://dev.max.ru/docs-api/methods/GET/chats) discovery нельзя перенести без изменения. В новом сервисе маршруты сохраняются, но очередь переносится в PostgreSQL, а chat_id приходят из подключения и событий.

### RSS с переводом

На коммите `19347e9ceb94c7e94244522419f36567a606e7e9` [telegram_rss_bot_enhanced.py](https://github.com/obodnikov/telegram-rss-news-bot/blob/19347e9ceb94c7e94244522419f36567a606e7e9/telegram_rss_bot_enhanced.py#L330) выбирает переводчик по типу, а [RSSBot](https://github.com/obodnikov/telegram-rss-news-bot/blob/19347e9ceb94c7e94244522419f36567a606e7e9/telegram_rss_bot_enhanced.py#L398) использует seen_entries и GUID/link либо хеш заголовка с датой. Это пример базовой идентичности записей; он не решает повтор одной новости на разных языках. В новом проекте нужны история событий, evidence и отдельная проверка обновлений.

### RSS с базой данных

На коммите `490b841820e67fc07dabef68dd453fc51e7d8592` [models.py](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/blob/490b841820e67fc07dabef68dd453fc51e7d8592/src/db/models.py#L101) хранит entry_hashes, etag и last_modified. [feed.py](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/blob/490b841820e67fc07dabef68dd453fc51e7d8592/src/web/feed.py#L64) обрабатывает 304. Эти идеи подходят для экономного опроса; хеши записей не заменяют смысловые события. Дерево содержит миграции PostgreSQL и SQLite, что полезно как пример управления схемой.

### Расписание OpenCode

На коммите `cd0b62364792f53e8687db53bc2c2c0261c9cf17` [index.ts](https://github.com/different-ai/opencode-scheduler/blob/cd0b62364792f53e8687db53bc2c2c0261c9cf17/src/index.ts#L236) формирует старую объектную переменную OPENCODE_PERMISSION, а [Windows установка](https://github.com/different-ai/opencode-scheduler/blob/cd0b62364792f53e8687db53bc2c2c0261c9cf17/src/index.ts#L1254) использует schtasks. README отдельно оговаривает отсутствие одинаковых supervisor гарантий Windows. Совместимость с локальным V2 не проверялась. В нашем проекте планировщик и блокировки находятся внутри приложения; ОС отвечает только за старт сервиса.

## Лицензии и выбор зависимостей

GitHub metadata и деревья в снимке показывают MIT у двух клиентов MAX и scheduler, AGPL-3.0 у RSS-to-Telegram-Bot. В двух остальных деревьях LICENSE не обнаружен и metadata license=null. Это основание не копировать их исходники до получения разрешения и уточнения лицензии. Конкретная зависимость принимается по её версии, LICENSE и условиям поставки; metadata GitHub не заменяет чтение текста лицензии.

На этапе документов приняты архитектурные наблюдения. Готовые deploy скрипты, секретные настройки и весь код аналога в новый проект не переносились. Выбранная архитектура и её собственные требования описаны в [ARCHITECTURE.md](ARCHITECTURE.md).
