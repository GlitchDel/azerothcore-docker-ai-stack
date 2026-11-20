# AzerothCore (WoW 3.3.5a) + Local LLM AI Companion (Ollama & SOAP)

Развёртывание контейнеризированного игрового сервера **World of Warcraft: Wrath of the Lich King (3.3.5a)** на базе **AzerothCore** с модулем `mod-playerbots` в среде Docker (Windows + WSL2) и интеграция игрового бота-компаньона с локальной языковой моделью (**Ollama / Gemma 3**).

Ядро AzerothCore было пересобрано в Docker с интеграцией C++ модуля `mod-playerbots`, а сам AI-мост (`Ollama + SOAP`) прикручен сверху как внешний микросервис без вмешательства в исходный код сервера.

## Архитектура решения

Взаимодействие между игровым сервером внутри Docker-контейнера и локальной нейросетью на хост-машине реализовано через событийно-ориентированный Python-мост:

```text
[WoW Client 3.3.5a]
       │ (сообщение игрока в /say)
       ▼
[ac-worldserver (Docker)] ──► пишет в Chat.log (ChatLog.Enable = 1)
       │
       ▼ (чтение tail в реальном времени)
[src/tempest_ai.py (Host)]
  ├── Контекст диалога (deque + tempest_memory.json)
  ├── Запрос в Ollama API (http://127.0.0.1:11434/api/chat)
  └── Структурированный JSON-ответ: {reply, emote, action}
       │
       ▼ (HTTP POST / XML SOAP API :7878)
[ac-worldserver (Docker)]
  ├── .announce -> реплика в чат игры
  ├── .playerbots exec <bot> emote <anim> -> анимация
  └── .playerbots exec <bot> <follow|stay|attack> -> ИИ-поведение
