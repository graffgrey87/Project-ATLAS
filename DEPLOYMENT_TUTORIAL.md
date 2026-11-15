# Пошаговое руководство по развёртыванию и запуску ATLAS

> [!NOTE]
> Это руководство описывает полный цикл ввода системы ATLAS в эксплуатацию: подготовку учётных данных, аренду инстанса на RunPod, подключение через Cursor IDE и автономную работу со смартфона через Telegram.

---

## Чек-лист готовности к запуску

- [ ] Получен токен Telegram-бота у `@BotFather` (`TELEGRAM_BOT_TOKEN`)
- [ ] Получен числовой ID пользователя у `@userinfobot` (`ALLOWED_TELEGRAM_ID`)
- [ ] Сгенерирован GitHub Personal Access Token (`GITHUB_TOKEN`)
- [ ] Собран и опубликован Docker-образ `ghcr.io/graffgrey87/project-atlas:latest` (видимость: Public)
- [ ] Создан аккаунт на [RunPod.io](https://www.runpod.io/) с балансом для аренды GPU (от 48 ГБ VRAM)
- [ ] *(Опционально)* Подготовлен файл лицензии Unity `.ulf`

---

## Этап 1. Подготовка учётных данных

### 1.1. Telegram-бот
1. Откройте в Telegram бота [@BotFather](https://t.me/BotFather).
2. Выполните команду `/newbot`.
3. Укажите имя: `ATLAS Vibe Coding`.
4. Укажите username: `atlas_<ваш_логин>_bot` (должен оканчиваться на `bot`).
5. Скопируйте токен вида `123456789:AA...` → это **`TELEGRAM_BOT_TOKEN`**.

### 1.2. Числовой Telegram ID
> [!IMPORTANT]
> Для защиты от GHSA-mj5r-hh7j-4gxf (identity rebinding при смене username) авторизация в ATLAS работает строго по неизменяемому целочисленному идентификатору.

1. Откройте бота [@userinfobot](https://t.me/userinfobot) и нажмите `/start`.
2. Скопируйте число из строки `Id:` (например, `987654321`) → это **`ALLOWED_TELEGRAM_ID`**.

### 1.3. GitHub Personal Access Token (PAT)
1. Откройте [GitHub Tokens Settings](https://github.com/settings/tokens).
2. Нажмите **Generate new token (classic)**.
3. Отметьте scopes: `repo`, `read:packages`, `write:packages`, `workflow`.
4. Скопируйте ключ `ghp_...` → это **`GITHUB_TOKEN`**.

### 1.4. Проверка Docker-образа
1. Перейдите в [GitHub Actions репозитория](https://github.com/graffgrey87/Project-ATLAS/actions).
2. Убедитесь, что workflow `Build & Push ATLAS Image` завершился успешно.
3. В настройках пакета ([Package Settings](https://github.com/users/graffgrey87/packages/container/package/project-atlas)) проверьте, что видимость установлена как **Public**.

---

## Этап 2. Развёртывание на RunPod

### 2.1. Выбор GPU и тарифной сетки
В [консоли RunPod](https://www.runpod.io/console/pods) выберите видеокарту с суммарным объёмом VRAM **от 48 ГБ**:
- **Community Cloud (максимальная экономия бюджета)**:
  - `2× RTX 3090 (2× 24 ГБ = 48 ГБ)` — от ~$0.44/час (AWQ 4-bit через Tensor Parallelism);
  - `1× A40 (48 ГБ)` — от ~$0.40–0.50/час (AWQ 4-bit);
  - `2× RTX 4090 (2× 24 ГБ = 48 ГБ)` — от ~$0.68/час (FP8 + fp8 KV-Cache).
- **Secure Cloud (высокая надежность)**:
  - `1× NVIDIA L40S (48 ГБ)` или `RTX 6000 Ada (48 ГБ)` — оптимально для FP8.

> [!WARNING]
> Одиночные видеокарты на 24 ГБ (1× RTX 3090 / 1× RTX 4090) блокируются на уровне `entrypoint.sh` с уведомлением в Telegram, так как модель MoE 35B не поместится в 24 ГБ VRAM.

---

### 2.2. Создание постоянного шаблона (Manage → Templates)
Рекомендуется один раз создать шаблон в **Manage → Templates → New Template**, чтобы в дальнейшем запускать ATLAS в один клик:

1. **Basic Info**:
   - **Template Name**: `ATLAS Vibe-Coding`
   - **Container Image**: `ghcr.io/graffgrey87/project-atlas:latest`
2. **Сетевые порты (Network)**:
   - **Expose HTTP Ports**: `8000, 8080` (8000 — vLLM API, 8080 — раздача APK)
   - **Expose TCP Ports**: `22` (SSH для Cursor IDE)
3. **Выбор сценария хранения (Storage)**:

   | Параметр | Сценарий 1: Community Cloud (Экономия $0/мес) | Сценарий 2: Secure Cloud (Постоянный кэш) |
   |---|---|---|
   | **Container Disk** | **`75–80 GB`** (эфемерный диск, плата только во время работы) | **`40 GB`** |
   | **Volume Disk** | **`0 GB`** (отключён, хранение бесплатно) | **`80 GB`** (монтируется в `/workspace`) |
   | **Синхронизация кода** | Авто-клон из GitHub при старте, авто-пуш и `/save` | Код и кэш модели сохраняются на томе |

4. **Environment Variables**:

   | Переменная | Значение | Пояснение |
   |---|---|---|
   | `PROJECT_REPO_URL` | `https://github.com/graffgrey87/Project-ATLAS.git` | Репозиторий для авто-клонирования в `/workspace` |
   | `GITHUB_TOKEN` | `ghp_...` | Токен из шага 1.3 с правами `repo` |
   | `TELEGRAM_BOT_TOKEN` | `123456789:ABC...` | Токен бота от `@BotFather` |
   | `ALLOWED_TELEGRAM_ID` | `987654321` | Числовой ID от `@userinfobot` |
   | `GITHUB_REPOSITORY` | `graffgrey87/Project-ATLAS` | Имя целевого репозитория |
   | `HF_HOME` | `/workspace/hf_cache` | Путь к кэшу весов модели |
   | `HF_HUB_ENABLE_HF_TRANSFER` | `1` | Максимальная скорость скачивания с Hugging Face |
   | `ARTIFACT_SERVER_PORT` | `8080` | Порт сервера раздачи мобильных APK |
   | `UNITY_LICENSE` | `<?xml ...` | *(Опционально)* Содержимое лицензии `.ulf` |

5. Нажмите **Save Template**.

---

### 2.3. Запуск инстанса (Deploy Pod)
1. Перейдите в **Pods → Deploy+**.
2. Выберите подходящий GPU (от 48 ГБ VRAM).
3. Во вкладке **My Templates** выберите `ATLAS Vibe-Coding`.
4. Нажмите **Deploy On-Demand**.

---

## Этап 3. Контроль запуска и сервисов

1. Откройте созданный Pod и перейдите во вкладку **Logs** или **Web Terminal**.
2. Скрипт `entrypoint.sh` выполнит:
   - Активацию лицензии Unity (если передан `UNITY_LICENSE`);
   - Автоматическое клонирование проекта из `PROJECT_REPO_URL` в `/workspace` (код, память и сессии восстанавливаются на чистом диске);
   - Анализ видеокарт через PyTorch (FP8 для Ada/Hopper/Blackwell, AWQ для Ampere);
   - Контроль диска: если модели нет и свободно < 40 ГБ — очистку старых моделей; если места всё ещё < 40 ГБ — отправку алерта в Telegram и остановку;
   - Быструю загрузку модели через `hf_transfer` и старт `supervisord` (PID 1).
3. Проверьте статус сервисов в терминале:
   ```bash
   supervisorctl status
   ```
   Ожидаемый вывод:
   ```text
   vllm             RUNNING
   mobile_bridge    RUNNING
   ```
4. По завершении загрузки весов эндпоинт `http://localhost:8000/health` вернёт `200 OK`.

---

## Этап 4. Подключение через Cursor IDE

1. Нажмите кнопку **Connect** в карточке Pod в RunPod и скопируйте строку подключения SSH.
2. В локальном файле `~/.ssh/config` на вашем ПК добавьте запись:
   ```ssh-config
   Host atlas-runpod
       HostName <IP_ИЛИ_DNS_ХОСТ>
       Port <SSH_ПОРТ>
       User root
       IdentityFile ~/.ssh/id_ed25519
       ServerAliveInterval 60
   ```
3. В Cursor IDE нажмите `Ctrl+Shift+P` → `Remote-SSH: Connect to Host...` → выберите `atlas-runpod`.
4. Откройте директорию `/workspace`.
5. Ролевые промпты из `.cursor/rules/` (`context-management.mdc`, `unity-senior.mdc`, `android-expert.mdc`) активируются автоматически при работе с кодом.
6. В разделе **Settings → Features → MCP** проверьте доступность серверов GitHub, Playwright и Blender Lab.

---

## Этап 5. Управление со смартфона (Telegram Bridge)

1. Откройте чат с созданным ботом в Telegram со смартфона Android и нажмите `/start`.
2. **Постановка задач**:
   Отправьте текстом задачу:
   > *"В проекте /workspace/projects/todo_app реализуй экран списка задач на Jetpack Compose и добавь кнопку добавления."*
   Бот прочитает файлы, внесёт изменения, создаст Git-коммит и ответит отчётом.
3. **Визуальный контроль (Vision)**:
   Прикрепите скриншот экрана мобильного приложения или макета и напишите:
   > *"Элемент наезжает на верхний статус-бар. Исправь отступ в Composable."*
   Модель распознает дефект и скорректирует верстку.
4. **Сборка и установка APK**:
   Отправьте сообщение:
   > *"Собери debug APK"*
   - Бот вызовет `skills/compile_android.py`.
   - Если файл ≤ 50 МБ — он поступит в чат как документ, который можно сразу установить на телефон.
   - Если файл > 50 МБ — бот предоставит прямую ссылку на скачивание через RunPod Proxy (`https://<POD_ID>-8080.proxy.runpod.net/artifacts/...`).
5. **Завершение сессии и сохранение в GitHub (Community Cloud)**:
   Перед выключением или удалением пода отправьте команду:
   > `/save` (или `/push`)
   Бот закоммитит все файлы, выполнит `git push origin main` и вернёт подтверждение с SHA коммита. После этого инстанс можно безопасно удалять (**Terminate**) без риска потери данных.

---

## Этап 6. Решение типовых проблем

| Ситуация | Причина | Действие |
|---|---|---|
| **Контейнер падает сразу после старта** | Суммарная VRAM ниже 44 ГБ (FP8) или 28 ГБ (AWQ) | Арендовать Pod с 48 ГБ VRAM (L40S, A40, RTX 6000 Ada или 2× RTX 4090) |
| **Бот молчит в Telegram** | Не совпадает `ALLOWED_TELEGRAM_ID` | Проверить числовой ID в `@userinfobot` и переменные Pod |
| **Ошибка 409 Conflict в логе бота** | Предыдущий процесс не освободил соединение | Скрипт `mobile_bridge.py` автоматически переподключится через 5 секунд |
| **Сборка Unity возвращает ошибку лицензии** | Не активирован headless-режим | Добавить контент `.ulf` в переменную `UNITY_LICENSE` в RunPod |
