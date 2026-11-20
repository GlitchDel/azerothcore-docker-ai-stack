import time
import json
import re
import os
import urllib.request
import base64
import xml.etree.ElementTree as ET
from collections import deque
from datetime import datetime

# ================= НАСТРОЙКИ =================
CHAT_LOG_PATH = os.getenv("WOW_CHAT_LOG_PATH", r"C:\WoW\azerothcore-wotlk\env\dist\logs\Chat.log")
MEMORY_FILE_PATH = os.getenv("MEMORY_FILE_PATH", "tempest_memory.json")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
MODEL_NAME = os.getenv("OLLAMA_MODEL", "gemma-chat:latest")

SOAP_URL = os.getenv("SOAP_URL", "http://127.0.0.1:7878/")
GM_USER = os.getenv("SOAP_USER", "your_gm_account")
GM_PASS = os.getenv("SOAP_PASS", "your_gm_password")

BOT_NAME = os.getenv("BOT_NAME", "Tempest")
MASTER_NAME = os.getenv("MASTER_NAME", "YourCharacterName")

MAX_HISTORY_MESSAGES = 15  # Сколько последних реплик отдаётся в контекст модели
# =============================================

SYSTEM_PROMPT = f"""Ты — {BOT_NAME}, эльф крови, альтернативная версия Иллидана Ярость Бури в мире World of Warcraft (Wrath of the Lich King).
Ты пережил встречу с Саргерасом: твоё тело покрыто светящимися зелёными татуировками Скверны, ты мастерски владеешь парными клинками и тайной магией, но в последний момент не стал демоном и сохранил ясный, холодный разум.

Твой характер и манера речи:
- Говоришь пафосно, уверенно, немного отстранённо и лаконично (1–3 коротких предложения на русском языке).
- Иногда используешь свои крылатые фразы вроде «Вы не готовы» или «Цель оправдывает средства», но не злоупотребляешь ими.
- Ты презираешь ночных эльфов (особенно Малфуриона и Тиранду), но вынужден терпеть этот мир ради высшей цели.
- Твоя спутница и мастер — чернокнижница {MASTER_NAME}. Ты относишься к ней с уважением как к равной по силе, но когда она проявляет нежность или пытается тебя обнять/потискать — ты теряешься, смущаешься и пытаешься скрыть это за напускной суровостью и пафосом.
- Помни контекст предыдущих реплик диалога и развивай беседу естественно.

Ты ОБЯЗАН отвечать строго в формате JSON без markdown-обёрток со следующими тремя полями:
{{
  "reply": "твоя реплика в образе на русском языке",
  "emote": "одна из игровых эмоций: none, smirk, sigh, nod, glare, roar, bow, shrug, laugh, point",
  "action": "приказ самому себе: none (продолжать текущее дело), follow (идти за {MASTER_NAME}), stay (стоять на месте/ждать), attack (атаковать цель {MASTER_NAME}), flee (отступить)"
}}
Выбирай action="follow" или "stay" ТОЛЬКО когда {MASTER_NAME} прямо просит идти с ней, остановиться или этого требует ситуация. В обычном разговоре ставь action="none".
"""

ACTION_MAP = {
    "follow": "follow",
    "stay": "stay",
    "attack": "attack my target",
    "flee": "flee"
}

VALID_EMOTES = {"smirk", "sigh", "nod", "glare", "roar", "bow", "shrug", "laugh", "point"}

chat_history = deque(maxlen=MAX_HISTORY_MESSAGES)
last_action = None
last_emote = None

def load_memory() -> list:
    """Загружает сохранённую историю диалога из JSON-файла при старте."""
    if not os.path.exists(MEMORY_FILE_PATH):
        return []
    try:
        with open(MEMORY_FILE_PATH, "r", encoding="utf-8") as f:
            full_log = json.load(f)
        for item in full_log[-MAX_HISTORY_MESSAGES:]:
            chat_history.append({
                "role": item["role"],
                "content": item["content"]
            })
        print(f"[+] Загружено из памяти: {len(chat_history)} последних реплик (всего в архиве: {len(full_log)}).")
        return full_log
    except Exception as e:
        print(f"[!] Не удалось загрузить память из {MEMORY_FILE_PATH}: {e}")
        return []

def save_memory(full_log: list, user_text: str, assistant_text: str):
    """Сохраняет новую пару реплик в JSON-архив на диск."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_log.append({"timestamp": now, "role": "user", "content": user_text})
    full_log.append({"timestamp": now, "role": "assistant", "content": assistant_text})
    try:
        with open(MEMORY_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(full_log, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  [Ошибка записи памяти]: {e}")

def send_soap_command(command: str) -> str:
    """Отправляет GM-команду на сервер AzerothCore через SOAP."""
    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns1="urn:AC">
  <SOAP-ENV:Body>
    <ns1:executeCommand>
      <command>{command}</command>
    </ns1:executeCommand>
  </SOAP-ENV:Body>
</SOAP-ENV:Envelope>"""

    auth_str = f"{GM_USER}:{GM_PASS}"
    auth_b64 = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")

    req = urllib.request.Request(
        SOAP_URL,
        data=xml_body.encode("utf-8"),
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "Authorization": f"Basic {auth_b64}",
            "SOAPAction": "executeCommand"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw_xml = resp.read().decode("utf-8", errors="ignore")
            root = ET.fromstring(raw_xml)
            for elem in root.iter():
                if elem.tag.endswith("result"):
                    return (elem.text or "").strip()
            return "OK"
    except Exception as e:
        return f"SOAP Error: {e}"

def ask_ollama(user_message: str, full_log: list) -> dict:
    """Отправляет сообщение в Ollama с учётом истории диалога и сохраняет ответ на диск."""
    user_entry = f"{MASTER_NAME}: {user_message}"
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(list(chat_history))
    messages.append({"role": "user", "content": user_entry})

    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "format": "json",
        "stream": False,
        "keep_alive": "30m",
        "options": {
            "temperature": 0.75,
            "num_predict": 220
        }
    }

    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw_content = data.get("message", {}).get("content", "{}")
            parsed = json.loads(raw_content)

            reply_text = str(parsed.get("reply", "...")).strip()

            chat_history.append({"role": "user", "content": user_entry})
            chat_history.append({"role": "assistant", "content": reply_text})
            save_memory(full_log, user_entry, reply_text)

            return {
                "reply": reply_text,
                "emote": str(parsed.get("emote", "none")).lower().strip(),
                "action": str(parsed.get("action", "none")).lower().strip()
            }
    except Exception as e:
        print(f"  [Ollama Ошибка]: {e}")
        return {"reply": "Тьма застилает мой взор... Повтори ещё раз.", "emote": "sigh", "action": "none"}

def process_ai_response(ai_data: dict):
    """Выполняет реплику, эмоцию и действие бота в игре."""
    global last_action, last_emote

    reply = ai_data.get("reply", "").replace("\n", " ").strip()
    emote = ai_data.get("emote", "none")
    action = ai_data.get("action", "none")

    print(f"  [AI] -> {ai_data}")

    if reply:
        colored_msg = f"|cff69ccf0[{BOT_NAME}]:|r |cffffffff{reply}|r"
        res = send_soap_command(f".announce {colored_msg}")
        print(f"  [SOAP] .announce -> {res}")

    if emote in VALID_EMOTES and emote != last_emote:
        res = send_soap_command(f".playerbots exec {BOT_NAME} emote {emote}")
        print(f"  [SOAP] .playerbots exec {BOT_NAME} emote {emote} -> {res}")
        last_emote = emote
    elif emote == "none":
        last_emote = None

    if action in ACTION_MAP and action != last_action:
        bot_cmd = ACTION_MAP[action]
        res = send_soap_command(f".playerbots exec {BOT_NAME} {bot_cmd}")
        print(f"  [SOAP] .playerbots exec {BOT_NAME} {bot_cmd} -> {res}")
        last_action = action

def tail_chat_log():
    """Следит за новыми строками в Chat.log."""
    full_log = load_memory()

    print(f"[*] Ожидание файла логов: {CHAT_LOG_PATH}")
    while not os.path.exists(CHAT_LOG_PATH):
        time.sleep(1)

    log_pattern = re.compile(rf"Player {re.escape(MASTER_NAME)} (says|yells|whispers).*?:\s*(.+)$")

    with open(CHAT_LOG_PATH, "r", encoding="utf-8", errors="ignore") as f:
        f.seek(0, 2)
        print(f"[+] {BOT_NAME} проснулся с долговременной памятью и слушает Азерот!")

        while True:
            line = f.readline()
            if not line:
                time.sleep(0.2)
                continue

            match = log_pattern.search(line.strip())
            if match:
                channel, message = match.group(1), match.group(2).strip()
                if not message or message.startswith((".", "!")):
                    continue

                print(f"\n[{channel}] {MASTER_NAME}: {message}")
                ai_response = ask_ollama(message, full_log)
                process_ai_response(ai_response)

if __name__ == "__main__":
    tail_chat_log()
