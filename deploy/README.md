# Развёртывание ATLAS Mobile Bridge 24/7 на VPS

Лёгкий режим работы на обычном CPU VPS (без локального GPU / vLLM): бот работает через внешние API (`Google Gemini`, `DeepSeek`) и при необходимости обращается к внешнему ComfyUI на RunPod.

## 1. Подготовка сервера (Ubuntu / Debian)
```bash
sudo apt update && sudo apt install -y git python3 python3-venv ffmpeg
sudo useradd -r -m -d /opt/atlas -s /bin/bash atlas || true
sudo -u atlas git clone https://github.com/graffgrey87/Project-ATLAS.git /opt/atlas
cd /opt/atlas
sudo -u atlas python3 -m venv .venv
sudo -u atlas .venv/bin/pip install --upgrade pip
sudo -u atlas .venv/bin/pip install -r deploy/requirements-vps.txt
```

## 2. Настройка `.env`
```bash
sudo -u atlas cp .env.example .env
sudo chmod 600 .env
sudo -u atlas nano .env
```
Заполните как минимум:
- `TELEGRAM_BOT_TOKEN` и `ALLOWED_TELEGRAM_ID`
- `GEMINI_API_KEY` и/или `DEEPSEEK_API_KEY`
- Опционально: `YOUTUBE_API_KEY`, `COMFYUI_API_URL`, `GITHUB_TOKEN`

## 3. Запуск через `systemd` (24/7)
```bash
sudo cp /opt/atlas/deploy/atlas-bot.service /etc/systemd/system/atlas-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now atlas-bot
sudo systemctl status atlas-bot
```
Просмотр логов в реальном времени:
```bash
sudo journalctl -u atlas-bot -f
```

## 4. Обновление бота с GitHub
```bash
cd /opt/atlas
sudo -u atlas git pull origin main
sudo -u atlas .venv/bin/pip install -r deploy/requirements-vps.txt
sudo systemctl restart atlas-bot
```

## 5. Опционально: Docker Compose (для GPU-сервера / RunPod)
Если требуется полный контейнер с GPU (vLLM + Android SDK + Blender):
```bash
docker compose up -d
```
Конфигурация описана в корневом [docker-compose.yml](../docker-compose.yml).
