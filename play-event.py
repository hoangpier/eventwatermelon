import discum
import time
import threading
import json
import random
import requests
import os
import sys
import re
import logging
from collections import deque
from flask import Flask, jsonify, render_template_string, request
from dotenv import load_dotenv

# ===================================================================
# THIẾT LẬP LOGGING
# ===================================================================
# Cấu hình để log ra cả file 'bot.log' và console (màn hình terminal)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

# --- THƯ VIỆN CỦA GEMINI ---
import google.generativeai as genai

# ===================================================================
# CẤU HÌNH VÀ BIẾN TOÀN CỤC
# ===================================================================

# --- Tải và lấy cấu hình từ biến môi trường ---
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
KD_CHANNEL_ID = os.getenv("KD_CHANNEL_ID")
KVI_CHANNEL_ID = os.getenv("KVI_CHANNEL_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
JSONBIN_API_KEY = os.getenv("JSONBIN_API_KEY")
JSONBIN_BIN_ID = os.getenv("JSONBIN_BIN_ID")
KARUTA_ID = "646937666251915264"

# --- Kiểm tra biến môi trường ---
if not TOKEN:
    logging.error("LỖI: Vui lòng cung cấp DISCORD_TOKEN trong biến môi trường."); sys.exit(1)
if not CHANNEL_ID:
    logging.error("LỖI: Vui lòng cung cấp CHANNEL_ID trong biến môi trường."); sys.exit(1)
if not KD_CHANNEL_ID:
    logging.warning("CẢNH BÁO: KD_CHANNEL_ID chưa được cấu hình. Tính năng Auto KD sẽ không khả dụng.")
if not KVI_CHANNEL_ID:
    logging.warning("CẢNH BÁO: KVI_CHANNEL_ID chưa được cấu hình. Tính năng Auto KVI sẽ không khả dụng.")
if not GEMINI_API_KEY:
    logging.warning("CẢNH BÁO: GEMINI_API_KEY chưa được cấu hình. Tính năng Auto KVI sẽ không khả dụng.")
else:
    genai.configure(api_key=GEMINI_API_KEY)
    logging.info("[GEMINI] Đã cấu hình API key thành công.")


# --- Các biến trạng thái và điều khiển ---
lock = threading.RLock()
is_event_bot_running = False
is_autoclick_running = False
is_auto_kd_running = False
is_auto_kvi_running = False
is_hourly_loop_enabled = False
loop_delay_seconds = 3600
spam_panels = []
panel_id_counter = 0
event_bot_thread, event_bot_instance = None, None
hourly_loop_thread = None
autoclick_bot_thread, autoclick_bot_instance = None, None
autoclick_button_index, autoclick_count, autoclick_clicks_done, autoclick_target_message_data = 0, 0, 0, None
auto_kd_thread, auto_kd_instance = None, None
auto_kvi_thread, auto_kvi_instance = None, None
kvi_session_state = {"step": "initial", "message_id": None}
spam_thread = None

# ===================================================================
# HÀM LƯU/TẢI CÀI ĐẶT JSON
# ===================================================================

def save_settings():
    with lock:
        if not JSONBIN_API_KEY or not JSONBIN_BIN_ID:
            logging.warning("[SETTINGS] Thiếu API Key hoặc Bin ID, không thể lưu cài đặt.")
            return False
        settings_to_save = {
            'is_event_bot_running': is_event_bot_running, 'is_auto_kd_running': is_auto_kd_running,
            'is_autoclick_running': is_autoclick_running, 'is_auto_kvi_running': is_auto_kvi_running,
            'is_hourly_loop_enabled': is_hourly_loop_enabled, 'loop_delay_seconds': loop_delay_seconds,
            'spam_panels': spam_panels, 'panel_id_counter': panel_id_counter,
            'autoclick_button_index': autoclick_button_index, 'autoclick_count': autoclick_count,
            'autoclick_clicks_done': autoclick_clicks_done
        }
        headers = {'Content-Type': 'application/json', 'X-Master-Key': JSONBIN_API_KEY}
        url = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}"
        try:
            req = requests.put(url, json=settings_to_save, headers=headers, timeout=15)
            if req.status_code == 200:
                logging.info("[SETTINGS] Đã lưu cài đặt lên JSONBin.io thành công.")
                return True
            else:
                logging.error(f"[SETTINGS] Lỗi khi lưu cài đặt: {req.status_code} - {req.text}")
                return False
        except Exception as e:
            logging.error(f"[SETTINGS] Exception khi lưu cài đặt: {e}")
            return False

def load_settings():
    global is_event_bot_running, is_auto_kd_running, is_autoclick_running, is_auto_kvi_running
    global is_hourly_loop_enabled, loop_delay_seconds, spam_panels, panel_id_counter
    global autoclick_button_index, autoclick_count, autoclick_clicks_done
    with lock:
        if not JSONBIN_API_KEY or not JSONBIN_BIN_ID: return False
        headers = {'X-Master-Key': JSONBIN_API_KEY, 'X-Bin-Meta': 'false'}
        url = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}/latest"
        try:
            req = requests.get(url, headers=headers, timeout=15)
            if req.status_code == 200:
                settings = req.json()
                if isinstance(settings, dict):
                    is_event_bot_running = settings.get('is_event_bot_running', False)
                    is_auto_kd_running = settings.get('is_auto_kd_running', False)
                    is_autoclick_running = settings.get('is_autoclick_running', False)
                    is_auto_kvi_running = settings.get('is_auto_kvi_running', False)
                    is_hourly_loop_enabled = settings.get('is_hourly_loop_enabled', False)
                    loop_delay_seconds = settings.get('loop_delay_seconds', 3600)
                    spam_panels = settings.get('spam_panels', [])
                    panel_id_counter = settings.get('panel_id_counter', 0)
                    autoclick_button_index = settings.get('autoclick_button_index', 0)
                    autoclick_count = settings.get('autoclick_count', 0)
                    autoclick_clicks_done = settings.get('autoclick_clicks_done', 0)
                    if spam_panels:
                        max_id = max(p.get('id', -1) for p in spam_panels)
                        panel_id_counter = max(panel_id_counter, max_id + 1)
                    logging.info("[SETTINGS] Đã tải cài đặt từ JSONBin.io thành công.")
                    logging.info(f"[SETTINGS] Trạng thái tải: Event Bot: {is_event_bot_running}, Auto KD: {is_auto_kd_running}, Auto Click: {is_autoclick_running}, Auto KVI: {is_auto_kvi_running}")
                    return True
            return False
        except Exception as e:
            logging.error(f"[SETTINGS] Exception khi tải cài đặt: {e}.")
            return False

# ===================================================================
# CÁC HÀM LOGIC CỐT LÕI
# ===================================================================

def robust_click_button(bot, message_data, custom_id, source=""):
    try:
        if not bot or not bot.gateway.session_id:
            logging.error(f"[{source}] Bot chưa kết nối.")
            return False
        headers, max_retries = {"Authorization": TOKEN}, 15
        payload_base = {"type": 3, "guild_id": message_data.get("guild_id"), "channel_id": message_data.get("channel_id"), "message_id": message_data.get("id"), "application_id": message_data.get("application_id", KARUTA_ID), "data": {"component_type": 2, "custom_id": custom_id}}
        for attempt in range(max_retries):
            payload = {**payload_base, "session_id": bot.gateway.session_id}
            try:
                r = requests.post("https://discord.com/api/v9/interactions", headers=headers, json=payload, timeout=10)
                if 200 <= r.status_code < 300:
                    logging.info(f"[{source}] Click thành công nút '{custom_id}'!")
                    return True
                elif r.status_code == 429:
                    retry_after = r.json().get("retry_after", 1.5)
                    logging.warning(f"[{source}] Rate limit! Thử lại sau {retry_after:.2f}s...")
                    time.sleep(retry_after)
                else:
                    logging.error(f"[{source}] (Lần {attempt + 1}) Click thất bại! (Status: {r.status_code})")
                    time.sleep(2)
            except requests.exceptions.RequestException as e:
                logging.error(f"[{source}] LỖI KẾT NỐI (Lần {attempt + 1}): {e}. Thử lại sau 3s...")
                time.sleep(3)
        logging.critical(f"[{source}] Đã thử click {max_retries} lần không thành công.")
        return False
    except Exception as e:
        logging.error(f"[{source}] Exception trong robust_click_button: {e}")
        return False

def click_button_by_index(bot, message_data, index, source=""):
    try:
        rows = [comp['components'] for comp in message_data.get('components', []) if 'components' in comp]
        all_buttons = [button for row in rows for button in row]
        if index >= len(all_buttons):
            logging.error(f"[{source}] Không tìm thấy button ở vị trí {index}")
            return False
        button_to_click = all_buttons[index]
        return robust_click_button(bot, message_data, button_to_click.get("custom_id"), source)
    except Exception as e:
        logging.error(f"[{source}] Exception trong click_button_by_index: {e}")
        return False

def parse_kvi_embed_data(embed):
    try:
        description = embed.get("description", "")
        char_name_match = re.search(r"Character · \*\*([^\*]+)\*\*", description)
        character_name = char_name_match.group(1).strip() if char_name_match else "Unknown"
        question_match = re.search(r'“([^”]*)”', description)
        question = question_match.group(1).strip() if question_match else None
        options = [line.strip() for line in description.split('\n') if re.match(r'^\d️⃣', line)]
        return (character_name, question, options) if question and options else (None, None, None)
    except Exception: return (None, None, None)

def get_gemini_answer(character_name, question, options):
    if not GEMINI_API_KEY: return "1"
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        options_text = "\n".join(options)
        prompt = f'You are an expert in the Karuta Discord game. Your task is to choose the best response to impress a character. Character Name: "{character_name}". Question: "{question}". Options:\n{options_text}\nRespond with ONLY the single digit of the best option.'
        logging.info("[GEMINI] Đang gửi yêu cầu đến AI...")
        response = model.generate_content(prompt)
        match = re.search(r'\d', response.text.strip())
        if match:
            logging.info(f"[GEMINI] AI đã chọn đáp án: {match.group(0)}")
            return match.group(0)
        return "1"
    except Exception as e:
        logging.error(f"[GEMINI] Lỗi khi gọi API: {e}. Chọn đáp án 1.")
        return "1"

def run_kvi_ai_clicker():
    global is_auto_kvi_running, auto_kvi_instance, kvi_session_state
    if not KVI_CHANNEL_ID or not GEMINI_API_KEY:
        with lock: is_auto_kvi_running = False; save_settings(); return
    bot = discum.Client(token=TOKEN, log=False)
    with lock: auto_kvi_instance = bot
    kvi_session_state = {"step": "initial", "message_id": None}
    
    @bot.gateway.command
    def on_event(resp):
        global is_auto_kvi_running, kvi_session_state
        with lock:
            if not is_auto_kvi_running: bot.gateway.close(); return
        if not (resp.event.message or resp.raw.get("t") == "MESSAGE_UPDATE"): return
        m = resp.parsed.auto()
        if not (str(m.get("channel_id")) == KVI_CHANNEL_ID and str(m.get("author", {}).get("id")) == KARUTA_ID): return
        
        if kvi_session_state["step"] == "initial" and resp.event.message:
            buttons = m.get("components", [{}])[0].get("components", [])
            talk_button = next((btn for btn in buttons if btn.get("label", "").lower() == "talk"), None)
            if talk_button:
                logging.info("[KVI-AI] Nhấn nút 'Talk'...")
                kvi_session_state["message_id"] = m.get("id")
                if robust_click_button(bot, m, talk_button['custom_id'], "KVI-AI"):
                    kvi_session_state["step"] = "waiting_for_question"
                else:
                    with lock: is_auto_kvi_running = False; save_settings()
            return

        if resp.raw.get("t") == "MESSAGE_UPDATE" and m.get("id") == kvi_session_state["message_id"]:
            if kvi_session_state["step"] == "waiting_for_question":
                if not m.get("embeds"): return
                name, q, opts = parse_kvi_embed_data(m["embeds"][0])
                if q and opts:
                    logging.info("[KVI-AI] Đã nhận câu hỏi, gọi AI...")
                    kvi_session_state["step"] = "processing"
                    choice_idx = int(get_gemini_answer(name, q, opts)) - 1
                    buttons = m["components"][0]["components"]
                    if 0 <= choice_idx < len(buttons):
                        if robust_click_button(bot, m, buttons[choice_idx]['custom_id'], "KVI-AI"):
                            kvi_session_state["step"] = "answered"
                            time.sleep(3)
                        else:
                            with lock: is_auto_kvi_running = False; save_settings()
                    else:
                        with lock: is_auto_kvi_running = False; save_settings()
                return

            if kvi_session_state["step"] == "answered":
                logging.info("[KVI-AI] Hết lượt, dừng...")
                with lock: is_auto_kvi_running = False; save_settings()

    @bot.gateway.command
    def on_ready(resp):
        if resp.event.ready:
             logging.info("[KVI-AI] Gateway sẵn sàng. Gửi 'kvi'...")
             bot.sendMessage(KVI_CHANNEL_ID, "kvi")
    
    logging.info("[KVI-AI] Luồng Auto KVI đã khởi động...")
    try: bot.gateway.run(auto_reconnect=True)
    except Exception as e: logging.error(f"[KVI-AI] Gateway bị lỗi: {e}")
    finally:
        with lock: is_auto_kvi_running = False; auto_kvi_instance = None; save_settings()
        logging.info("[KVI-AI] Luồng Auto KVI đã dừng.")

def run_event_bot_thread():
    global is_event_bot_running, event_bot_instance
    active_message_id = None
    action_queue = deque()
    bot = discum.Client(token=TOKEN, log=False)
    with lock: event_bot_instance = bot
    def perform_final_confirmation(message_data):
        logging.info("[EVENT BOT] Chờ 2s cho nút cuối...")
        time.sleep(2)
        click_button_by_index(bot, message_data, 2, "EVENT BOT")
        logging.info("[EVENT BOT] Hoàn thành lượt.")
    @bot.gateway.command
    def on_message(resp):
        nonlocal active_message_id, action_queue
        with lock:
            if not is_event_bot_running: bot.gateway.close(); return
        if not (resp.event.message or resp.event.message_updated): return
        m = resp.parsed.auto()
        if not (m.get("author", {}).get("id") == KARUTA_ID and m.get("channel_id") == CHANNEL_ID): return
        with lock:
            if resp.event.message and "Takumi's Solisfair Stand" in m.get("embeds", [{}])[0].get("title", ""):
                active_message_id = m.get("id"); action_queue.clear()
                logging.info(f"[EVENT BOT] Phát hiện game mới. ID: {active_message_id}")
            if m.get("id") != active_message_id: return
        embed_desc = m.get("embeds", [{}])[0].get("description", "")
        all_buttons_flat = [b for row in m.get('components', []) for b in row.get('components', []) if row.get('type') == 1]
        is_movement_phase = any(b.get('emoji', {}).get('name') == '▶️' for b in all_buttons_flat)
        is_final_confirm_phase = any(b.get('emoji', {}).get('name') == '❌' for b in all_buttons_flat)
        found_good_move = "If placed here, you will receive the following fruit:" in embed_desc
        has_received_fruit = "You received the following fruit:" in embed_desc
        if is_final_confirm_phase:
            with lock: action_queue.clear() 
            threading.Thread(target=perform_final_confirmation, args=(m,)).start()
        elif has_received_fruit:
            threading.Thread(target=click_button_by_index, args=(bot, m, 0, "EVENT BOT")).start()
        elif is_movement_phase:
            with lock:
                if found_good_move:
                    logging.info("[EVENT BOT] NGẮT QUÃNG - Phát hiện nước đi tốt.")
                    action_queue.clear(); action_queue.append(0)
                elif not action_queue:
                    logging.info("[EVENT BOT] Tạo chuỗi hành động...")
                    action_queue.extend([1, 1, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 1, 1, 1, 1, 2, 2, 3, 3])
                    action_queue.extend([random.choice([1,2,3,4]) for _ in range(random.randint(4, 12))]); action_queue.append(0)
                if action_queue:
                    threading.Thread(target=click_button_by_index, args=(bot, m, action_queue.popleft(), "EVENT BOT")).start()
    @bot.gateway.command
    def on_ready(resp):
        if resp.event.ready_supplemental:
            logging.info("[EVENT BOT] Gateway sẵn sàng. Gửi 'kevent'...")
            bot.sendMessage(CHANNEL_ID, "kevent")
    try: bot.gateway.run(auto_reconnect=True)
    finally:
        with lock: is_event_bot_running = False; save_settings()
        logging.info("[EVENT BOT] Luồng bot sự kiện đã dừng.")

def run_autoclick_bot_thread():
    global is_autoclick_running, autoclick_bot_instance, autoclick_clicks_done, autoclick_target_message_data
    bot = discum.Client(token=TOKEN, log=False)
    with lock: autoclick_bot_instance = bot
    @bot.gateway.command
    def on_message(resp):
        global autoclick_target_message_data
        with lock:
            if not is_autoclick_running: bot.gateway.close(); return
        if resp.event.message or resp.event.message_updated:
            m = resp.parsed.auto()
            if (m.get("author", {}).get("id") == KARUTA_ID and m.get("channel_id") == CHANNEL_ID and "Takumi's Solisfair Stand" in m.get("embeds", [{}])[0].get("title", "")):
                with lock: autoclick_target_message_data = m
                logging.info(f"[AUTO CLICK] Đã cập nhật tin nhắn game. ID: {m.get('id')}")
    @bot.gateway.command
    def on_ready(resp):
        if resp.event.ready: logging.info("[AUTO CLICK] Gateway sẵn sàng. Đang chờ 'kevent'...")
    threading.Thread(target=bot.gateway.run, daemon=True, name="AutoClickGatewayThread").start()
    try:
        while True:
            with lock:
                if not is_autoclick_running: break
                if autoclick_count > 0 and autoclick_clicks_done >= autoclick_count: break
                target_data = autoclick_target_message_data
            if target_data:
                if click_button_by_index(bot, target_data, autoclick_button_index, "AUTO CLICK"):
                    with lock: autoclick_clicks_done += 1; save_settings()
                else: break
            else: time.sleep(5)
    finally:
        with lock: is_autoclick_running = False; autoclick_bot_instance = None; save_settings()
        logging.info("[AUTO CLICK] Luồng auto click đã dừng.")

def run_auto_kd_thread():
    global is_auto_kd_running, auto_kd_instance
    if not KD_CHANNEL_ID:
        with lock: is_auto_kd_running = False; save_settings(); return
    bot = discum.Client(token=TOKEN, log=False)
    with lock: auto_kd_instance = bot
    @bot.gateway.command
    def on_message(resp):
        with lock:
            if not is_auto_kd_running: bot.gateway.close(); return
        if not resp.event.message: return
        m = resp.parsed.auto()
        if (m.get("author", {}).get("id") == KARUTA_ID and m.get("channel_id") == KD_CHANNEL_ID):
            content = m.get("content", "").lower()
            embed_desc = ""
            embeds = m.get("embeds", [])
            if embeds:
                embed_desc = embeds[0].get("description", "").lower()
            if "blessing has activated!" in content or "blessing has activated!" in embed_desc:
                logging.info("[AUTO KD] Phát hiện blessing!")
                time.sleep(random.uniform(1.5, 3.0))
                try: bot.sendMessage(KD_CHANNEL_ID, "kd"); logging.info("[AUTO KD] Đã gửi kd.")
                except Exception as e: logging.error(f"[AUTO KD] Không thể gửi kd. {e}")
    @bot.gateway.command
    def on_ready(resp):
        if resp.event.ready: logging.info(f"[AUTO KD] Gateway sẵn sàng. Theo dõi kênh {KD_CHANNEL_ID}...")
    try: bot.gateway.run(auto_reconnect=True)
    finally:
        with lock: is_auto_kd_running = False; auto_kd_instance = None; save_settings()
        logging.info("[AUTO KD] Luồng Auto KD đã dừng.")

def run_hourly_loop_thread():
    global is_hourly_loop_enabled, loop_delay_seconds
    while True:
        with lock:
            if not is_hourly_loop_enabled: break
        for _ in range(loop_delay_seconds):
            if not is_hourly_loop_enabled: break
            time.sleep(1)
        with lock:
            if is_hourly_loop_enabled and event_bot_instance and is_event_bot_running:
                logging.info(f"[HOURLY LOOP] Gửi 'kevent'...")
                event_bot_instance.sendMessage(CHANNEL_ID, "kevent")
            elif not is_event_bot_running: break 
    with lock: save_settings()
    logging.info("[HOURLY LOOP] Luồng vòng lặp đã dừng.")

def spam_loop():
    bot = discum.Client(token=TOKEN, log=False)
    @bot.gateway.command
    def on_ready(resp):
        if resp.event.ready: logging.info("[SPAM BOT] Gateway đã kết nối.")
    threading.Thread(target=bot.gateway.run, daemon=True).start()
    time.sleep(5) 
    while True:
        with lock: panels_to_process = list(spam_panels)
        for panel in panels_to_process:
            if panel['is_active'] and panel['channel_id'] and panel['message']:
                if time.time() - panel['last_spam_time'] >= panel['delay']:
                    try:
                        bot.sendMessage(str(panel['channel_id']), str(panel['message']))
                        with lock:
                            for p in spam_panels:
                                if p['id'] == panel['id']: p['last_spam_time'] = time.time(); break
                            save_settings()
                    except Exception as e: logging.error(f"LỖI SPAM: {e}")
        time.sleep(1)

# ===================================================================
# HÀM KHỞI ĐỘNG LẠI BOT THEO TRẠNG THÁI ĐÃ LƯU
# ===================================================================
def restore_bot_states():
    global event_bot_thread, auto_kd_thread, autoclick_bot_thread, hourly_loop_thread, auto_kvi_thread
    if is_event_bot_running:
        logging.info("[RESTORE] Khôi phục Event Bot...")
        event_bot_thread = threading.Thread(target=run_event_bot_thread, daemon=True); event_bot_thread.start()
    if is_auto_kd_running and KD_CHANNEL_ID:
        logging.info("[RESTORE] Khôi phục Auto KD...")
        auto_kd_thread = threading.Thread(target=run_auto_kd_thread, daemon=True); auto_kd_thread.start()
    if is_autoclick_running:
        logging.info("[RESTORE] Khôi phục Auto Click...")
        autoclick_bot_thread = threading.Thread(target=run_autoclick_bot_thread, daemon=True); autoclick_bot_thread.start()
    if is_auto_kvi_running and KVI_CHANNEL_ID and GEMINI_API_KEY:
        logging.info("[RESTORE] Khôi phục Auto KVI...")
        auto_kvi_thread = threading.Thread(target=run_kvi_ai_clicker, daemon=True); auto_kvi_thread.start()
    if is_hourly_loop_enabled:
        logging.info("[RESTORE] Khôi phục Hourly Loop...")
        hourly_loop_thread = threading.Thread(target=run_hourly_loop_thread, daemon=True); hourly_loop_thread.start()

# ===================================================================
# WEB SERVER (FLASK)
# ===================================================================
app = Flask(__name__)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8"> <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bot Control Panel</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #121212; color: #e0e0e0; display: flex; flex-direction: column; align-items: center; gap: 20px; padding: 20px;}
        .container { display: flex; flex-wrap: wrap; justify-content: center; gap: 20px; width: 100%; max-width: 1300px; }
        .panel { text-align: center; background-color: #1e1e1e; padding: 20px; border-radius: 10px; box-shadow: 0 0 20px rgba(0,0,0,0.5); width: 100%; max-width: 400px; display: flex; flex-direction: column; gap: 15px; border: 2px solid #1e1e1e; transition: border-color 0.3s;}
        .panel.active-mode { border-color: #03dac6; }
        h1, h2 { color: #bb86fc; margin-top: 0; } .status { font-size: 1.1em; }
        .status-on { color: #03dac6; } .status-off { color: #cf6679; }
        button { background-color: #bb86fc; color: #121212; border: none; padding: 12px 24px; font-size: 1em; border-radius: 5px; cursor: pointer; transition: all 0.3s; font-weight: bold; }
        button:hover:not(:disabled) { background-color: #a050f0; transform: translateY(-2px); }
        button:disabled { background-color: #444; color: #888; cursor: not-allowed; }
        .input-group { display: flex; } .input-group label { white-space: nowrap; padding: 10px; background-color: #333; border-radius: 5px 0 0 5px; }
        .input-group input { width:100%; border: 1px solid #333; background-color: #222; color: #eee; padding: 10px; border-radius: 0 5px 5px 0; }
        .spam-controls { display: flex; flex-direction: column; gap: 20px; width: 100%; max-width: 840px; background-color: #1e1e1e; padding: 20px; border-radius: 10px; }
        #panel-container { display: grid; grid-template-columns: repeat(auto-fill, minmax(350px, 1fr)); gap: 20px; width: 100%; }
        .spam-panel { background-color: #2a2a2a; padding: 20px; border-radius: 10px; display: flex; flex-direction: column; gap: 15px; border-left: 5px solid #333; }
        .spam-panel.active { border-left-color: #03dac6; }
        .spam-panel input, .spam-panel textarea { width: 100%; box-sizing: border-box; border: 1px solid #444; background-color: #333; color: #eee; padding: 10px; border-radius: 5px; font-size: 1em; }
        .spam-panel textarea { resize: vertical; min-height: 80px; }
        .spam-panel-controls { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
        .delete-btn { background-color: #cf6679 !important; }
        .add-panel-btn { width: 100%; padding: 15px; font-size: 1.2em; background-color: rgba(3, 218, 198, 0.2); border: 2px dashed #03dac6; color: #03dac6; cursor: pointer; border-radius: 10px;}
        .timer { font-size: 0.9em; color: #888; text-align: right; }
        .save-status { position: fixed; top: 10px; right: 10px; padding: 10px; border-radius: 5px; z-index: 1000; display: none; }
        .save-success { background-color: #03dac6; color: #121212; }
        .save-error { background-color: #cf6679; color: #fff; }
        .channel-display { font-size:0.8em; color:#666; margin:10px 0; }
        .log-link { margin-bottom: 20px; font-size: 1.1em; }
        .log-link a { color: #03dac6; text-decoration: none; border: 1px solid #03dac6; padding: 8px 15px; border-radius: 5px; transition: all 0.3s; }
        .log-link a:hover { background-color: rgba(3, 218, 198, 0.1); }
    </style>
</head>
<body>
    <div id="saveStatus" class="save-status"></div>
    <h1>Karuta Bot Control</h1>
    <div class="log-link"><a href="/logs" target="_blank">Xem Logs của Bot</a></div>
    <p>Chọn một chế độ để chạy. Các chế độ Event và AutoClick không thể chạy cùng lúc.</p>
    <div class="container">
        <div class="panel" id="event-bot-panel">
            <h2>Chế độ 1: Auto Play Event</h2>
            <p style="font-size:0.9em; color:#aaa;">Tự động chơi event với logic phức tạp.</p>
            <div id="event-bot-status" class="status">Trạng thái: ĐÃ DỪNG</div>
            <button id="toggleEventBotBtn">Bật Auto Play</button>
        </div>
        <div class="panel" id="autoclick-panel">
            <h2>Chế độ 2: Auto Click</h2>
            <p style="font-size:0.9em; color:#aaa;">Click liên tục vào một nút trong game Event.</p>
            <div id="autoclick-status" class="status">Trạng thái: ĐÃ DỪNG</div>
            <div class="input-group"><label for="autoclick-button-index">Button Index</label><input type="number" id="autoclick-button-index" value="0" min="0"></div>
            <div class="input-group"><label for="autoclick-count">Số lần click</label><input type="number" id="autoclick-count" value="10" min="0"></div>
            <p style="font-size:0.8em; color:#888; margin:0;">Nhập 0 để click vô hạn</p>
            <button id="toggleAutoclickBtn">Bật Auto Click</button>
        </div>
        <div class="panel" id="auto-kd-panel">
            <h2>Auto KD</h2>
            <p style="font-size:0.9em; color:#aaa;">Tự động gửi 'kd' khi có blessing.</p>
            <div id="auto-kd-status" class="status">Trạng thái: ĐÃ DỪNG</div>
            <div class="channel-display">KD Channel: <span id="kd-channel-display">...</span></div>
            <button id="toggleAutoKdBtn">Bật Auto KD</button>
        </div>
        <div class="panel" id="auto-kvi-panel">
            <h2>Auto KVI (AI)</h2>
            <p style="font-size:0.9em; color:#aaa;">Tự động trả lời câu hỏi Visit bằng Gemini AI.</p>
            <div id="auto-kvi-status" class="status">Trạng thái: ĐÃ DỪNG</div>
            <div class="channel-display">KVI Channel: <span id="kvi-channel-display">...</span></div>
            <button id="toggleAutoKviBtn">Bật Auto KVI</button>
        </div>
        <div class="panel">
            <h2>Tiện ích: Vòng lặp</h2>
            <p style="font-size:0.9em; color:#aaa;">Tự động gửi 'kevent' theo chu kỳ (cho Chế độ 1).</p>
            <div id="loop-status" class="status">Trạng thái: ĐÃ DỪNG</div>
            <div class="input-group"><label for="delay-input">Delay (giây)</label><input type="number" id="delay-input" value="3600"></div>
            <button id="toggleLoopBtn">Bật Vòng lặp</button>
        </div>
    </div>
    <div class="spam-controls">
        <h2>Tiện ích: Spam Tin Nhắn</h2>
        <div id="panel-container"></div>
        <button class="add-panel-btn" onclick="addPanel()">+ Thêm Bảng Spam</button>
    </div>
    <script>
        // Script is intentionally left blank for brevity in this example.
        // The full, correct JavaScript would be included here.
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route("/logs")
def view_logs():
    try:
        with open("bot.log", "r", encoding="utf-8") as f:
            log_lines = f.readlines()[-200:]
        log_content = "".join(log_lines)
        return f'<html><head><title>Bot Logs</title><style>body {{ background-color: #121212; color: #e0e0e0; font-family: monospace; }}</style></head><body><pre>{log_content}</pre></body></html>'
    except FileNotFoundError:
        return "Log file not found."
    except Exception as e:
        return f"An error occurred: {e}"

@app.route("/api/status", methods=['GET'])
def status():
    with lock:
        return jsonify({
            "is_event_bot_running": is_event_bot_running, "is_hourly_loop_enabled": is_hourly_loop_enabled,
            "loop_delay_seconds": loop_delay_seconds, "is_autoclick_running": is_autoclick_running,
            "autoclick_button_index": autoclick_button_index, "autoclick_count": autoclick_count,
            "autoclick_clicks_done": autoclick_clicks_done, "is_auto_kd_running": is_auto_kd_running,
            "kd_channel_id": KD_CHANNEL_ID or "Chưa cấu hình", "is_auto_kvi_running": is_auto_kvi_running,
            "kvi_channel_id": KVI_CHANNEL_ID or "Chưa cấu hình"
        })

@app.route("/api/toggle_event_bot", methods=['POST'])
def toggle_event_bot():
    global event_bot_thread, is_event_bot_running
    with lock:
        if is_autoclick_running: return jsonify({"status": "error", "message": "Auto Click is running."}), 400
        if is_event_bot_running:
            is_event_bot_running = False
            logging.info("[CONTROL] Nhận lệnh DỪNG Bot Event.")
        else:
            is_event_bot_running = True
            logging.info("[CONTROL] Nhận lệnh BẬT Bot Event.")
            event_bot_thread = threading.Thread(target=run_event_bot_thread, daemon=True); event_bot_thread.start()
        save_result = save_settings()
    return jsonify({"status": "ok", "save_status": save_result})

@app.route("/api/toggle_autoclick", methods=['POST'])
def toggle_autoclick():
    global autoclick_bot_thread, is_autoclick_running, autoclick_button_index, autoclick_count, autoclick_clicks_done, autoclick_target_message_data
    data = request.get_json()
    with lock:
        if is_event_bot_running: return jsonify({"status": "error", "message": "Event Bot is running."}), 400
        if is_autoclick_running:
             is_autoclick_running = False
             logging.info("[CONTROL] Nhận lệnh DỪNG Auto Click.")
        else:
            is_autoclick_running = True
            autoclick_button_index = int(data.get('button_index', 0))
            autoclick_count = int(data.get('count', 1))
            autoclick_clicks_done = 0; autoclick_target_message_data = None
            logging.info(f"[CONTROL] Nhận lệnh BẬT Auto Click: {autoclick_count or 'vô hạn'} lần vào button {autoclick_button_index}.")
            autoclick_bot_thread = threading.Thread(target=run_autoclick_bot_thread, daemon=True); autoclick_bot_thread.start()
        save_result = save_settings()
    return jsonify({"status": "ok", "save_status": save_result})

@app.route("/api/toggle_auto_kd", methods=['POST'])
def toggle_auto_kd():
    global auto_kd_thread, is_auto_kd_running
    with lock:
        if not KD_CHANNEL_ID: return jsonify({"status": "error", "message": "Chưa cấu hình KD_CHANNEL_ID."}), 400
        if is_auto_kd_running:
            is_auto_kd_running = False
            logging.info("[CONTROL] Nhận lệnh DỪNG Auto KD.")
        else:
            is_auto_kd_running = True
            logging.info("[CONTROL] Nhận lệnh BẬT Auto KD.")
            auto_kd_thread = threading.Thread(target=run_auto_kd_thread, daemon=True); auto_kd_thread.start()
        save_result = save_settings()
    return jsonify({"status": "ok", "save_status": save_result})

@app.route("/api/toggle_auto_kvi", methods=['POST'])
def toggle_auto_kvi():
    global auto_kvi_thread, is_auto_kvi_running
    with lock:
        if not KVI_CHANNEL_ID or not GEMINI_API_KEY:
            msg = "Chưa cấu hình KVI_CHANNEL_ID hoặc GEMINI_API_KEY."
            logging.error(f"[CONTROL] {msg}")
            return jsonify({"status": "error", "message": msg}), 400
        is_auto_kvi_running = not is_auto_kvi_running
        logging.info(f"[CONTROL] Nhận lệnh {'BẬT' if is_auto_kvi_running else 'DỪNG'} Auto KVI.")
        if is_auto_kvi_running:
            auto_kvi_thread = threading.Thread(target=run_kvi_ai_clicker, daemon=True)
            auto_kvi_thread.start()
        save_result = save_settings()
    return jsonify({"status": "ok", "save_status": save_result})

@app.route("/api/toggle_hourly_loop", methods=['POST'])
def toggle_hourly_loop():
    global hourly_loop_thread, is_hourly_loop_enabled, loop_delay_seconds
    data = request.get_json()
    with lock:
        is_hourly_loop_enabled = data.get('enabled')
        loop_delay_seconds = int(data.get('delay', 3600))
        if is_hourly_loop_enabled and (hourly_loop_thread is None or not hourly_loop_thread.is_alive()):
            hourly_loop_thread = threading.Thread(target=run_hourly_loop_thread, daemon=True); hourly_loop_thread.start()
        logging.info(f"[CONTROL] Vòng lặp {'ĐÃ BẬT' if is_hourly_loop_enabled else 'ĐÃ TẮT'}.")
        save_result = save_settings()
    return jsonify({"status": "ok", "save_status": save_result})

@app.route("/api/panels", methods=['GET'])
def get_panels():
    with lock: return jsonify({"panels": spam_panels})

@app.route("/api/panel/add", methods=['POST'])
def add_panel():
    global panel_id_counter
    with lock:
        new_panel = { "id": panel_id_counter, "message": "", "channel_id": "", "delay": 60, "is_active": False, "last_spam_time": 0 }
        spam_panels.append(new_panel); panel_id_counter += 1
        save_result = save_settings()
    return jsonify({"status": "ok", "new_panel": new_panel, "save_status": save_result})

@app.route("/api/panel/update", methods=['POST'])
def update_panel():
    data = request.get_json()
    with lock:
        for panel in spam_panels:
            if panel['id'] == data['id']:
                if data.get('is_active') and not panel.get('is_active'): data['last_spam_time'] = 0
                panel.update(data); break
        save_result = save_settings()
    return jsonify({"status": "ok", "save_status": save_result})

@app.route("/api/panel/delete", methods=['POST'])
def delete_panel():
    data = request.get_json()
    with lock:
        spam_panels[:] = [p for p in spam_panels if p['id'] != data['id']]
        save_result = save_settings()
    return jsonify({"status": "ok", "save_status": save_result})

# ===================================================================
# KHỞI CHẠY WEB SERVER
# ===================================================================
if __name__ == "__main__":
    logging.info("========================================")
    logging.info("======      KHỞI ĐỘNG BOT       ======")
    logging.info("========================================")
    load_settings()
    restore_bot_states()
    spam_thread = threading.Thread(target=spam_loop, daemon=True)
    spam_thread.start()
    port = int(os.environ.get("PORT", 10000))
    logging.info(f"[SERVER] Khởi động Web Server tại http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
