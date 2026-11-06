# Google Sheets MCP

[![Check](https://github.com/heist1337/sheets-mcp/actions/workflows/check.yml/badge.svg)](https://github.com/heist1337/sheets-mcp/actions/workflows/check.yml)
[![FastMCP](https://img.shields.io/badge/FastMCP-4.1.6-blue)](https://gofastmcp.com/)
[![MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.12%2B-blue)

Пять инструментов для чтения и редактирования Google Sheets.
Небольшой собственный MCP на **FastMCP** и **официальном Google SDK**.
Удаления, очистка и уменьшение сетки блокируются до обращения к Google.

## Быстрый старт

Установить [uv](https://docs.astral.sh/uv/getting-started/installation/), затем:

```bash
git clone https://github.com/heist1337/sheets-mcp.git
cd sheets-mcp
cp .env.example .env
# Указать путь к Google credentials в .env.
uv run --locked --env-file .env google-sheets-mcp
```

По умолчанию используется **stdio**: обычно эту команду запускает MCP-клиент.
Python и зависимости устанавливает uv.

## Подключение к агенту

Скопировать [mcp.example.json](mcp.example.json) в настройки MCP-клиента,
заменив путь к checkout и приватному env-файлу. Запуск — одна команда;
постоянно работающий сервис не требуется.

| Инструмент | Действие |
| --- | --- |
| `sheets_get` | Метаданные, листы, форматы и свойства |
| `sheets_read` | Явный A1-диапазон; формулы по умолчанию |
| `sheets_create` | Создание таблицы при наличии соответствующих прав Google |
| `sheets_write` | Запись в согласованный диапазон; RAW по умолчанию |
| `sheets_batch_update` | Форматирование и разрешённые структурные операции |

Обычное редактирование может заменить содержимое. Сначала прочитать цель;
после таймаута записи проверить результат, прежде чем повторять запрос.
Автоматических повторов записи и HTTP redirects нет.

## Авторизация

`GOOGLE_APPLICATION_CREDENTIALS` — путь к service-account JSON либо стандартные
Google Application Default Credentials. Таблицы должны быть доступны этому
аккаунту; его права могут отличаться от прав пользователя.

Для пользовательского доступа задать `GOOGLE_OAUTH_TOKEN_FILE`. Первичный вход
использует штатный Google OAuth Desktop flow:

```bash
uv run google-sheets-mcp --authorize --client-secrets /private/client.json --token-file /private/oauth-token.json
```

JSON с `type=service_account` — другой тип credentials, не OAuth Desktop client.
Создание новых файлов ограничивается правами и storage quota Google-аккаунта.
Секреты хранить вне Git с правами 0600; каталог — 0700.

## HTTP и Docker

Для общего endpoint задать `MCP_TOKEN` длиной от 32 символов:

```bash
uv run --locked --env-file .env google-sheets-mcp --transport http --port 18091
```

URL: `http://127.0.0.1:18091/mcp/`, заголовок `Authorization: Bearer <MCP_TOKEN>`.
По умолчанию сервер слушает loopback. Для доступа извне нужен приватный транспорт/HTTPS.

```bash
docker build -t google-sheets-mcp .
docker run --rm -i --env-file .env \
  -v /private/credentials.json:/run/secrets/google.json:ro \
  -e GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/google.json google-sheets-mcp
```

Контейнер работает непривилегированным UID 1000; смонтированный файл должен быть
доступен этому UID. Docker Desktop не требуется.

## Перенос и разработка

Перенести checkout, приватный env-файл и Google credentials; обновить пути.
Нет зависимости от Personal Context, Windmill, PostgreSQL или другого MCP.

```bash
uv sync --locked
uv run ruff check src tests
uv run python -m unittest discover -b -s tests
uv build
```

Это самостоятельный адаптер на официальном Google SDK.

[Передача коллегам и проверка](SHARING.md) · [MIT](LICENSE)
