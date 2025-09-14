import discum
import time
import threading
import json
import random
import requests
import os
import sys
import re
from collections import deque
from flask import Flask, jsonify, render_template_string, request
from dotenv import load_dotenv

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
    print("LỖI: Vui lòng cung cấp DISCORD_TOKEN trong biến môi trường.", flush=True)
    sys.exit(1)
if not CHANNEL_ID:
    print("LỖI: Vui lòng cung cấp CHANNEL_ID trong biến môi trường.", flush=True)
    sys.exit(1)
if not KD_CHANNEL_ID:
    print("CẢNH BÁO: KD_CHANNEL_ID chưa được cấu hình. Tính năng Auto KD sẽ không khả dụng.", flush=True)
if not KVI_CHANNEL_ID:
    print("CẢNH BÁO: KVI_CHANNEL_ID chưa được cấu hình. Tính năng Auto KVI sẽ không khả dụng.", flush=True)
if not GEMINI_API_KEY:
    print("CẢNH BÁO: GEMINI_API_KEY chưa được cấu hình. Tính năng Auto KVI sẽ không khả dụng.", flush=True)


# --- Các biến trạng thái và điều khiển ---
lock = threading.RLock()

# Các biến trạng thái chạy (sẽ được load từ JSON)
is_event_bot_running = False
is_autoclick_running = False
is_auto_kd_running = False
is_auto_kvi_running = False

# Các biến cài đặt (sẽ được load từ JSON)
is_hourly_loop_enabled = False
loop_delay_seconds = 3600
spam_panels = []
panel_id_counter = 0
next_kvi_allowed_time = 0 

# Các biến runtime khác
event_bot_thread, event_bot_instance = None, None
hourly_loop_thread = None
autoclick_bot_thread, autoclick_bot_instance = None, None
autoclick_button_index, autoclick_count, autoclick_clicks_done, autoclick_target_message_data = 0, 0, 0, None
auto_kd_thread, auto_kd_instance = None, None
auto_kvi_thread, auto_kvi_instance = None, None
spam_thread = None

# ===================================================================
# HÀM LƯU/TẢI CÀI ĐẶT JSON
# ===================================================================

def save_settings():
    """Lưu tất cả cài đặt và trạng thái lên JSONBin.io"""
    with lock:
        if not JSONBIN_API_KEY or not JSONBIN_BIN_ID:
            print("[SETTINGS] WARN: Thiếu API Key hoặc Bin ID, không thể lưu cài đặt.", flush=True)
            return False

        settings_to_save = {
            'is_event_bot_running': is_event_bot_running,
            'is_auto_kd_running': is_auto_kd_running,
            'is_auto_kvi_running': is_auto_kvi_running,
            'is_autoclick_running': is_autoclick_running,
            'is_hourly_loop_enabled': is_hourly_loop_enabled,
            'loop_delay_seconds': loop_delay_seconds,
            'spam_panels': spam_panels,
            'panel_id_counter': panel_id_counter,
            'autoclick_button_index': autoclick_button_index,
            'autoclick_count': autoclick_count,
            'autoclick_clicks_done': autoclick_clicks_done,
            'next_kvi_allowed_time': next_kvi_allowed_time
        }
        
        headers = {
            'Content-Type': 'application/json',
            'X-Master-Key': JSONBIN_API_KEY
        }
        url = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}"
        
        try:
            req = requests.put(url, json=settings_to_save, headers=headers, timeout=15)
            if req.status_code == 200:
                print("[SETTINGS] INFO: Đã lưu cài đặt lên JSONBin.io thành công.", flush=True)
                return True
            else:
                print(f"[SETTINGS] LỖI: Lỗi khi lưu cài đặt: {req.status_code} - {req.text}", flush=True)
                return False
        except Exception as e:
            print(f"[SETTINGS] LỖI NGOẠI LỆ: Exception khi lưu cài đặt: {e}", flush=True)
            return False

def load_settings():
    """Tải cài đặt từ JSONBin.io khi khởi động"""
    global is_event_bot_running, is_auto_kd_running, is_autoclick_running, is_auto_kvi_running
    global is_hourly_loop_enabled, loop_delay_seconds, spam_panels, panel_id_counter
    global autoclick_button_index, autoclick_count, autoclick_clicks_done
    global next_kvi_allowed_time
    
    with lock:
        if not JSONBIN_API_KEY or not JSONBIN_BIN_ID:
            print("[SETTINGS] INFO: Thiếu API Key hoặc Bin ID, sử dụng cài đặt mặc định.", flush=True)
            return False

        headers = {'X-Master-Key': JSONBIN_API_KEY, 'X-Bin-Meta': 'false'}
        url = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}/latest"

        try:
            req = requests.get(url, headers=headers, timeout=15)
            if req.status_code == 200:
                settings = req.json()
                if settings and isinstance(settings, dict):
                    is_event_bot_running = settings.get('is_event_bot_running', False)
                    is_auto_kd_running = settings.get('is_auto_kd_running', False)
                    is_auto_kvi_running = settings.get('is_auto_kvi_running', False)
                    is_autoclick_running = settings.get('is_autoclick_running', False)
                    is_hourly_loop_enabled = settings.get('is_hourly_loop_enabled', False)
                    loop_delay_seconds = settings.get('loop_delay_seconds', 3600)
                    spam_panels = settings.get('spam_panels', [])
                    panel_id_counter = settings.get('panel_id_counter', 0)
                    autoclick_button_index = settings.get('autoclick_button_index', 0)
                    autoclick_count = settings.get('autoclick_count', 0)
                    autoclick_clicks_done = settings.get('autoclick_clicks_done', 0)
                    next_kvi_allowed_time = settings.get('next_kvi_allowed_time', 0)
                    
                    if spam_panels:
                        max_id = max(p.get('id', -1) for p in spam_panels)
                        panel_id_counter = max(panel_id_counter, max_id + 1)

                    print("[SETTINGS] INFO: Đã tải cài đặt từ JSONBin.io thành công.", flush=True)
                    print(f"[SETTINGS] INFO: Event Bot: {is_event_bot_running}, Auto KD: {is_auto_kd_running}, Auto KVI: {is_auto_kvi_running}, Auto Click: {is_autoclick_running}", flush=True)
                    return True
                else:
                    print("[SETTINGS] INFO: Bin rỗng hoặc không hợp lệ, bắt đầu với cài đặt mặc định.", flush=True)
                    return False
            else:
                print(f"[SETTINGS] LỖI: Lỗi khi tải cài đặt: {req.status_code} - {req.text}.", flush=True)
                return False
        except Exception as e:
            print(f"[SETTINGS] LỖI NGOẠI LỆ: Exception khi tải cài đặt: {e}.", flush=True)
            return False

# ===================================================================
# CÁC HÀM LOGIC CỐT LÕI
# ===================================================================

def click_button_by_index(bot, message_data, index, source=""):
    try:
        if not bot or not bot.gateway.session_id:
            print(f"[{source}] LỖI: Bot chưa kết nối hoặc không có session_id.", flush=True)
            return False
        application_id = message_data.get("application_id", KARUTA_ID)
        rows = [comp['components'] for comp in message_data.get('components', []) if 'components' in comp]
        all_buttons = [button for row in rows for button in row]
        if index >= len(all_buttons):
            print(f"[{source}] LỖI: Không tìm thấy button ở vị trí {index}", flush=True)
            return False
        button_to_click = all_buttons[index]
        custom_id = button_to_click.get("custom_id")
        if not custom_id: return False
        headers = {"Authorization": TOKEN}
        max_retries = 10
        for attempt in range(max_retries):
            session_id = bot.gateway.session_id
            payload = { "type": 3, "guild_id": message_data.get("guild_id"), "channel_id": message_data.get("channel_id"), "message_id": message_data.get("id"), "application_id": application_id, "session_id": session_id, "data": {"component_type": 2, "custom_id": custom_id} }
            emoji_name = button_to_click.get('emoji', {}).get('name', 'Không có')
            label_name = button_to_click.get('label', 'Không có')
            print(f"[{source}] INFO (Lần {attempt + 1}/{max_retries}): Chuẩn bị click button {index} (Label: {label_name}, Emoji: {emoji_name})", flush=True)
            try:
                r = requests.post("https://discord.com/api/v9/interactions", headers=headers, json=payload, timeout=10)
                if 200 <= r.status_code < 300:
                    print(f"[{source}] INFO: Click thành công!", flush=True)
                    time.sleep(random.uniform(2.5, 3.5))
                    return True
                elif r.status_code == 429:
                    retry_after = r.json().get("retry_after", 1.5)
                    print(f"[{source}] WARN: Bị rate limit! Thử lại sau {retry_after:.2f}s...", flush=True)
                    time.sleep(retry_after)
                else:
                    print(f"[{source}] LỖI: Click thất bại! (Status: {r.status_code}, Response: {r.text})", flush=True)
                    time.sleep(2)
            except requests.exceptions.RequestException as e:
                print(f"[{source}] LỖI KẾT NỐI: {e}. Thử lại sau 3s...", flush=True)
                time.sleep(3)
        print(f"[{source}] LỖI: Đã thử click {max_retries} lần không thành công.", flush=True)
        return False
    except Exception as e:
        print(f"[{source}] LỖI NGOẠI LỆ trong hàm click: {e}", flush=True)
        return False

def run_event_bot_thread():
    global is_event_bot_running, event_bot_instance
    active_message_id = None
    action_queue = deque()
    bot = discum.Client(token=TOKEN, log=False)
    with lock: event_bot_instance = bot
    def perform_final_confirmation(message_data):
        print("[EVENT BOT] ACTION: Chờ 2s cho nút cuối...", flush=True)
        time.sleep(2)
        click_button_by_index(bot, message_data, 2, "EVENT BOT")
        print("[EVENT BOT] INFO: Hoàn thành lượt.", flush=True)
    @bot.gateway.command
    def on_message(resp):
        nonlocal active_message_id, action_queue
        with lock:
            if not is_event_bot_running:
                bot.gateway.close()
                return
        if not (resp.event.message or resp.event.message_updated): return
        m = resp.parsed.auto()
        if not (m.get("author", {}).get("id") == KARUTA_ID and m.get("channel_id") == CHANNEL_ID): return
        with lock:
            if resp.event.message and "Takumi's Solisfair Stand" in m.get("embeds", [{}])[0].get("title", ""):
                active_message_id = m.get("id")
                action_queue.clear()
                print(f"\n[EVENT BOT] INFO: Phát hiện game mới. ID: {active_message_id}", flush=True)
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
                    print("[EVENT BOT] INFO: NGẮT QUÃNG - Phát hiện nước đi tốt.", flush=True)
                    action_queue.clear()
                    action_queue.append(0)
                elif not action_queue:
                    print("[EVENT BOT] INFO: Tạo chuỗi hành động...", flush=True)
                    action_queue.extend([1, 1, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 1, 1, 1, 1, 2, 2, 3, 3])
                    action_queue.extend([random.choice([1,2,3,4]) for _ in range(random.randint(4, 12))])
                    action_queue.append(0)
                if action_queue:
                    next_action_index = action_queue.popleft()
                    threading.Thread(target=click_button_by_index, args=(bot, m, next_action_index, "EVENT BOT")).start()
    @bot.gateway.command
    def on_ready(resp):
        if resp.event.ready_supplemental:
            print("[EVENT BOT] Gateway sẵn sàng. Gửi 'kevent'...", flush=True)
            bot.sendMessage(CHANNEL_ID, "kevent")
    print("[EVENT BOT] Luồng bot sự kiện đã khởi động...", flush=True)
    try:
        bot.gateway.run(auto_reconnect=True)
    except Exception as e:
        print(f"[EVENT BOT] LỖI: Gateway bị lỗi: {e}", flush=True)
    finally:
        with lock: 
            is_event_bot_running = False
            save_settings()
        print("[EVENT BOT] Luồng bot sự kiện đã dừng.", flush=True)

def run_autoclick_bot_thread():
    global is_autoclick_running, autoclick_bot_instance, autoclick_clicks_done, autoclick_target_message_data
    bot = discum.Client(token=TOKEN, log=False)
    with lock: autoclick_bot_instance = bot
    @bot.gateway.command
    def on_message(resp):
        global autoclick_target_message_data
        with lock:
            if not is_autoclick_running:
                bot.gateway.close()
                return
        if resp.event.message or resp.event.message_updated:
            m = resp.parsed.auto()
            if (m.get("author", {}).get("id") == KARUTA_ID and m.get("channel_id") == CHANNEL_ID and "Takumi's Solisfair Stand" in m.get("embeds", [{}])[0].get("title", "")):
                with lock: autoclick_target_message_data = m
                print(f"[AUTO CLICK] INFO: Đã cập nhật tin nhắn game. ID: {m.get('id')}", flush=True)
    @bot.gateway.command
    def on_ready(resp):
        if resp.event.ready:
            print("[AUTO CLICK] Gateway sẵn sàng. Đang chờ 'kevent'...", flush=True)
    threading.Thread(target=bot.gateway.run, daemon=True, name="AutoClickGatewayThread").start()
    print("[AUTO CLICK] Luồng auto click đã khởi động.", flush=True)
    try:
        while True:
            with lock:
                if not is_autoclick_running: break
                if autoclick_count > 0 and autoclick_clicks_done >= autoclick_count:
                    print("[AUTO CLICK] INFO: Đã hoàn thành.", flush=True)
                    break
                target_data = autoclick_target_message_data
            if target_data:
                if click_button_by_index(bot, target_data, autoclick_button_index, "AUTO CLICK"):
                    with lock: 
                        autoclick_clicks_done += 1
                        save_settings()
                else:
                    print("[AUTO CLICK] LỖI NGHIÊM TRỌNG: Không thể click. Dừng.", flush=True)
                    break
            else:
                print("[AUTO CLICK] WARN: Chưa có tin nhắn event.", flush=True)
                time.sleep(5)
    except Exception as e:
        print(f"[AUTO CLICK] LỖI: Exception trong loop: {e}", flush=True)
    finally:
        with lock:
            is_autoclick_running = False
            autoclick_bot_instance = None
            save_settings()
        print("[AUTO CLICK] Luồng auto click đã dừng.", flush=True)

def run_auto_kd_thread():
    global is_auto_kd_running, auto_kd_instance
    if not KD_CHANNEL_ID:
        print("[AUTO KD] LỖI: Chưa cấu hình KD_CHANNEL_ID.", flush=True)
        with lock: 
            is_auto_kd_running = False
            save_settings()
        return
    bot = discum.Client(token=TOKEN, log=False)
    with lock: auto_kd_instance = bot
    @bot.gateway.command
    def on_message(resp):
        with lock:
            if not is_auto_kd_running:
                bot.gateway.close()
                return
        if not resp.event.message: return
        m = resp.parsed.auto()
        if (m.get("author", {}).get("id") == KARUTA_ID and m.get("channel_id") == KD_CHANNEL_ID):
            message_content = m.get("content", "").lower()
            embed_description = ""
            embeds = m.get("embeds", [])
            if embeds: embed_description = embeds[0].get("description", "").lower()
            if ("blessing has activated!" in message_content or "blessing has activated!" in embed_description):
                print("[AUTO KD] INFO: Phát hiện blessing activated!", flush=True)
                delay = random.uniform(1.5, 3.0)
                time.sleep(delay)
                try:
                    bot.sendMessage(KD_CHANNEL_ID, "kd")
                    print(f"[AUTO KD] SUCCESS: Đã gửi kd.", flush=True)
                except Exception as e:
                    print(f"[AUTO KD] LỖI: Không thể gửi kd. {e}", flush=True)
    @bot.gateway.command
    def on_ready(resp):
        if resp.event.ready:
            print(f"[AUTO KD] Gateway sẵn sàng. Đang theo dõi kênh {KD_CHANNEL_ID}...", flush=True)
    print("[AUTO KD] Luồng Auto KD đã khởi động...", flush=True)
    try:
        bot.gateway.run(auto_reconnect=True)
    except Exception as e:
        print(f"[AUTO KD] LỖI: Gateway bị lỗi: {e}", flush=True)
    finally:
        with lock:
            is_auto_kd_running = False
            auto_kd_instance = None
            save_settings()
        print("[AUTO KD] Luồng Auto KD đã dừng.", flush=True)

# ===================================================================
# CHỨC NĂNG AUTO KVI (ĐÃ SỬA LỖI LOGIC)
# ===================================================================
def run_auto_kvi_thread():
    global is_auto_kvi_running, auto_kvi_instance, next_kvi_allowed_time
    
    if not KVI_CHANNEL_ID:
        print("[AUTO KVI] LỖI: Chưa cấu hình KVI_CHANNEL_ID.", flush=True)
        with lock: is_auto_kvi_running = False; save_settings()
        return
    if not GEMINI_API_KEY:
        print("[AUTO KVI] LỖI: Gemini API Key chưa được cấu hình.", flush=True)
        with lock: is_auto_kvi_running = False; save_settings()
        return

    bot = discum.Client(token=TOKEN, log=False)
    with lock: auto_kvi_instance = bot
    
    last_action_time = time.time()
    last_api_call_time = 0
    last_kvi_send_time = 0
    last_session_end_time = 0
    KVI_COOLDOWN_SECONDS = 3
    KVI_TIMEOUT_SECONDS = 3605

    def answer_question_with_gemini(bot_instance, message_data, question, options):
        nonlocal last_api_call_time
        print(f"[AUTO KVI] GEMINI: Nhận được câu hỏi: '{question}'", flush=True)
        
        try:
            embeds = message_data.get("embeds", [])
            embed = embeds[0] if embeds else {}
            desc = embed.get("description", "")
            
            character_name = "Unknown"
            embed_title = embed.get("title", "")
            if "Character:" in desc:
                char_match = re.search(r'Character:\s*([^(]+)', desc)
                if char_match:
                    character_name = char_match.group(1).strip()
            elif embed_title:
                character_name = embed_title.replace("Visit Character", "").strip()
            
            prompt = f"""You are playing Karuta's KVI (Visit Character) system. You are interacting with the character: {character_name}. Your goal is to choose the BEST response to build affection and have a positive interaction with {character_name}.

IMPORTANT RULES:
1. Choose responses that show interest, care, or positive engagement with {character_name}.
2. Consider the character's personality if you know it.
3. Avoid negative, dismissive, or rude responses.
4. Pick answers that would naturally continue the conversation.
5. Prefer romantic or friendly options over neutral ones.
6. Choose responses that would make {character_name} happy or interested.

Question from {character_name}: "{question}"

Available response options:
{chr(10).join([f"{i+1}. {opt}" for i, opt in enumerate(options)])}

Respond with ONLY the number (1, 2, 3, etc.) of the BEST option to increase affection with {character_name}."""

            payload = { "contents": [{"parts": [{"text": prompt}]}] }
            api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
            
            response = requests.post(api_url, headers={'Content-Type': 'application/json'}, json=payload, timeout=15)
            response.raise_for_status()
            
            result = response.json()
            api_text = result['candidates'][0]['content']['parts'][0]['text'].strip()
            
            match = re.search(r'(\d+)', api_text)
            if match:
                selected_option = int(match.group(1))
                if 1 <= selected_option <= len(options):
                    print(f"[AUTO KVI] GEMINI: Chọn đáp án {selected_option}: '{options[selected_option-1]}'", flush=True)
                    time.sleep(random.uniform(1.5, 2.5))
                    if click_button_by_index(bot_instance, message_data, selected_option - 1, "AUTO KVI"):
                        last_api_call_time = time.time()
                else:
                    print(f"[AUTO KVI] LỖI: Gemini chọn số không hợp lệ: {selected_option}. Chọn đáp án đầu tiên.", flush=True)
                    click_button_by_index(bot_instance, message_data, 0, "AUTO KVI")
            else:
                print(f"[AUTO KVI] LỖI: Không tìm thấy số trong phản hồi: '{api_text}'. Chọn đáp án đầu tiên.", flush=True)
                click_button_by_index(bot_instance, message_data, 0, "AUTO KVI")

        except requests.exceptions.RequestException as e:
            print(f"[AUTO KVI] LỖI API: {e}. Chọn đáp án đầu tiên.", flush=True)
            click_button_by_index(bot_instance, message_data, 0, "AUTO KVI")
        except Exception as e:
            print(f"[AUTO KVI] LỖI NGOẠI LỆ: {e}. Chọn đáp án đầu tiên.", flush=True)
            click_button_by_index(bot_instance, message_data, 0, "AUTO KVI")

    def smart_button_click(bot_instance, message_data):
        nonlocal last_api_call_time
        components = message_data.get("components", [])
        all_buttons = [button for row in components for button in row.get("components", [])]
        
        if all_buttons:
            target_index = 0
            button_label = all_buttons[target_index].get("label", "Không rõ")
            print(f"[AUTO KVI] INFO: Nhấn vào nút ở vị trí đầu tiên (Index 0, Label: {button_label}).", flush=True)
            time.sleep(random.uniform(1.0, 2.0))
            if click_button_by_index(bot_instance, message_data, target_index, "AUTO KVI"):
                last_api_call_time = time.time()
        else:
            print("[AUTO KVI] WARN: Không tìm thấy nút nào để bấm.", flush=True)

    @bot.gateway.command
    def on_message(resp):
        nonlocal last_action_time, last_api_call_time, last_session_end_time
        global next_kvi_allowed_time
        
        with lock:
            if not is_auto_kvi_running:
                bot.gateway.close()
                return
        
        if not (resp.event.message or resp.event.message_updated): return
        m = resp.parsed.auto()
        if not (m.get("author", {}).get("id") == KARUTA_ID and m.get("channel_id") == KVI_CHANNEL_ID): return

        current_time = time.time()
        last_action_time = current_time

        if current_time - last_api_call_time < KVI_COOLDOWN_SECONDS:
            return

        # <<< THAY ĐỔI BẮT ĐẦU: Logic mới để xác định kết thúc phiên >>>
        # Lấy thông tin các nút bấm từ tin nhắn
        components = m.get("components", [])
        action_row = components[0] if components and components[0].get("type") == 1 else {}
        all_buttons = action_row.get("components", [])

        # Kiểm tra nếu có nút và nút đầu tiên bị vô hiệu hóa (disabled)
        if all_buttons and all_buttons[0].get("disabled", False):
            # Dùng debounce để tránh ghi nhận kết thúc phiên nhiều lần
            if time.time() - last_session_end_time > 60:
                last_session_end_time = time.time()
                with lock:
                    # Đặt cooldown 30 phút cho lần KVI tiếp theo
                    next_kvi_allowed_time = time.time() + 1800 
                    print(f"[AUTO KVI] INFO: Nút 'Talk' đã bị vô hiệu hóa. Phiên KVI kết thúc.", flush=True)
                    print(f"[AUTO KVI] INFO: KVI tiếp theo được phép sau {time.strftime('%H:%M:%S', time.localtime(next_kvi_allowed_time))}", flush=True)
                    save_settings()
            return # Dừng xử lý thêm vì phiên đã kết thúc

        # <<< THAY ĐỔI KẾT THÚC >>>

        embeds = m.get("embeds", [])
        if not embeds: return
        embed = embeds[0]
        desc = embed.get("description", "")
        
        # Logic cũ vẫn giữ nguyên: Nếu có câu hỏi thì dùng AI
        if '1️⃣' in desc:
            print("[AUTO KVI] INFO: Phát hiện câu hỏi có emoji 1️⃣. Dùng AI...", flush=True)
            question_patterns = [r'["“](.+?)["”]', r'"([^"]+)"']
            question_found = False
            for pattern in question_patterns:
                question_match = re.search(pattern, desc, re.DOTALL)
                if question_match:
                    question = question_match.group(1).strip()
                    options = []
                    lines = desc.split('\n')
                    for line in lines:
                        match = re.search(r'^\s*(?:\d{1,2}[\.\)]|:keycap_(\d{1,2}):|(\d{1,2})️⃣)\s*(.+)', line)
                        if match:
                            option_text = match.groups()[-1].strip()
                            if option_text:
                                options.append(option_text)
                    
                    if question and len(options) >= 2:
                        question_found = True
                        threading.Thread(target=answer_question_with_gemini, args=(bot, m, question, options), daemon=True).start()
                        break
            
            if not question_found:
                 print("[AUTO KVI] WARN: Có emoji 1️⃣ nhưng không thể phân tích câu hỏi. Chuyển sang hành động mặc định.", flush=True)
                 threading.Thread(target=smart_button_click, args=(bot, m), daemon=True).start()
        # Nếu không có câu hỏi và phiên chưa kết thúc, thực hiện hành động mặc định
        else:
            print("[AUTO KVI] INFO: Không có câu hỏi. Thực hiện hành động mặc định (bấm nút đầu tiên).", flush=True)
            threading.Thread(target=smart_button_click, args=(bot, m), daemon=True).start()

    def periodic_kvi_sender():
        nonlocal last_action_time, last_kvi_send_time
        global next_kvi_allowed_time
        
        time.sleep(10)

        with lock:
            if time.time() < next_kvi_allowed_time:
                wait_time = next_kvi_allowed_time - time.time()
                print(f"[AUTO KVI] INFO: Đang trong thời gian chờ. Sẽ không gửi kvi khởi tạo. Chờ thêm {wait_time:.0f} giây.", flush=True)
            else:
                try:
                    bot.sendMessage(KVI_CHANNEL_ID, "kvi")
                    last_kvi_send_time = time.time()
                    last_action_time = time.time()
                    print("[AUTO KVI] INFO: Gửi lệnh kvi khởi tạo", flush=True)
                except Exception as e:
                    print(f"[AUTO KVI] LỖI: Không thể gửi kvi khởi tạo: {e}", flush=True)
        
        while True:
            with lock:
                if not is_auto_kvi_running: break
            
            current_time = time.time()
            if current_time - last_action_time > KVI_TIMEOUT_SECONDS:
                if current_time - last_kvi_send_time > 300:
                    try:
                        bot.sendMessage(KVI_CHANNEL_ID, "kvi")
                        last_action_time = current_time
                        last_kvi_send_time = current_time
                        print("[AUTO KVI] INFO: Timeout - gửi kvi để khởi động lại", flush=True)
                    except Exception as e:
                        print(f"[AUTO KVI] LỖI: Không thể gửi kvi timeout: {e}", flush=True)
            time.sleep(60)

    @bot.gateway.command
    def on_ready(resp):
        if resp.event.ready_supplemental:
            print(f"[AUTO KVI] Gateway sẵn sàng. Theo dõi kênh {KVI_CHANNEL_ID}...", flush=True)
            threading.Thread(target=periodic_kvi_sender, daemon=True).start()

    print("[AUTO KVI] Luồng Auto KVI đã khởi động...", flush=True)
    try:
        bot.gateway.run(auto_reconnect=True)
    except Exception as e:
        print(f"[AUTO KVI] LỖI: Gateway bị lỗi: {e}", flush=True)
    finally:
        with lock: 
            is_auto_kvi_running = False
            auto_kvi_instance = None
            save_settings()
        print("[AUTO KVI] Luồng Auto KVI đã dừng.", flush=True)

def run_hourly_loop_thread():
    global is_hourly_loop_enabled, loop_delay_seconds
    print("[HOURLY LOOP] Luồng vòng lặp đã khởi động.", flush=True)
    try:
        while True:
            with lock:
                if not is_hourly_loop_enabled: break
            for _ in range(loop_delay_seconds):
                if not is_hourly_loop_enabled: break
                time.sleep(1)
            with lock:
                if is_hourly_loop_enabled and event_bot_instance and is_event_bot_running:
                    print(f"\n[HOURLY LOOP] Hết {loop_delay_seconds} giây. Gửi 'kevent'...", flush=True)
                    event_bot_instance.sendMessage(CHANNEL_ID, "kevent")
                elif not is_event_bot_running:
                    break
    except Exception as e:
        print(f"[HOURLY LOOP] LỖI: Exception trong loop: {e}", flush=True)
    finally:
        with lock:
            save_settings()
        print("[HOURLY LOOP] Luồng vòng lặp đã dừng.", flush=True)

def get_new_random_delay(panel):
    """Calculates the next spam delay based on the panel's selected mode."""
    mode = panel.get('delay_mode', 'minutes') # Default to minutes for safety

    if mode == 'seconds':
        min_seconds = panel.get('delay_min_seconds', 240)
        max_seconds = panel.get('delay_max_seconds', 300)
        if min_seconds > max_seconds:
            min_seconds, max_seconds = max_seconds, min_seconds
        return random.uniform(min_seconds, max_seconds)
    else: # Default to minutes mode
        min_minutes = panel.get('delay_min_minutes', 4)
        max_minutes = panel.get('delay_max_minutes', 5)
        if min_minutes > max_minutes:
            min_minutes, max_minutes = max_minutes, min_minutes
        
        chosen_minutes = random.randint(min_minutes, max_minutes)
        humanizer_seconds = random.randint(1, 15)
        return (chosen_minutes * 60) + humanizer_seconds

def spam_loop():
    bot = discum.Client(token=TOKEN, log=False)
    @bot.gateway.command
    def on_ready(resp):
        if resp.event.ready: print("[SPAM BOT] Gateway đã kết nối.", flush=True)
    
    threading.Thread(target=bot.gateway.run, daemon=True, name="SpamGatewayThread").start()
    
    while not bot.gateway.session_id:
        time.sleep(1)

    while True:
        try:
            with lock:
                panels_to_process = list(spam_panels)
            
            for panel in panels_to_process:
                if panel.get('is_active') and panel.get('channel_id') and panel.get('message') and time.time() >= panel.get('next_spam_time', 0):
                    try:
                        bot.sendMessage(str(panel['channel_id']), str(panel['message']))
                        print(f"[SPAM BOT] Gửi tin nhắn tới kênh {panel['channel_id']}", flush=True)
                        
                        with lock:
                            for p in spam_panels:
                                if p['id'] == panel['id']:
                                    next_delay = get_new_random_delay(p)
                                    p['next_spam_time'] = time.time() + next_delay
                                    print(f"[SPAM BOT] Panel {p['id']} (Mode: {p.get('delay_mode', 'minutes')}) hẹn giờ tiếp theo sau {next_delay:.2f} giây.", flush=True)
                                    break
                            save_settings()
                            
                    except Exception as e:
                        print(f"[SPAM BOT] LỖI: Không thể gửi tin nhắn. {e}", flush=True)
                        with lock:
                            for p in spam_panels:
                                if p['id'] == panel['id']:
                                    p['next_spam_time'] = time.time() + 60
                                    break
            time.sleep(1)
        except Exception as e:
            print(f"LỖI NGOẠI LỆ trong vòng lặp spam: {e}", flush=True)
            time.sleep(5)

# ===================================================================
# HÀM KHỞI ĐỘNG LẠI BOT THEO TRẠNG THÁI ĐÃ LƯU
# ===================================================================
def restore_bot_states():
    """Khởi động lại các bot theo trạng thái đã được lưu"""
    global event_bot_thread, auto_kd_thread, autoclick_bot_thread, hourly_loop_thread, auto_kvi_thread
    
    if is_event_bot_running:
        print("[RESTORE] Khôi phục Event Bot...", flush=True)
        event_bot_thread = threading.Thread(target=run_event_bot_thread, daemon=True)
        event_bot_thread.start()
    
    if is_auto_kd_running and KD_CHANNEL_ID:
        print("[RESTORE] Khôi phục Auto KD...", flush=True)
        auto_kd_thread = threading.Thread(target=run_auto_kd_thread, daemon=True)
        auto_kd_thread.start()
    
    if is_auto_kvi_running and KVI_CHANNEL_ID and GEMINI_API_KEY:
        print("[RESTORE] Khôi phục Auto KVI...", flush=True)
        auto_kvi_thread = threading.Thread(target=run_auto_kvi_thread, daemon=True)
        auto_kvi_thread.start()

    if is_autoclick_running:
        print("[RESTORE] Khôi phục Auto Click...", flush=True)
        autoclick_bot_thread = threading.Thread(target=run_autoclick_bot_thread, daemon=True)
        autoclick_bot_thread.start()
    
    if is_hourly_loop_enabled:
        print("[RESTORE] Khôi phục Hourly Loop...", flush=True)
        hourly_loop_thread = threading.Thread(target=run_hourly_loop_thread, daemon=True)
        hourly_loop_thread.start()

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
        .input-group { display: flex; flex-direction: column; gap: 5px; } .input-group label { text-align: left; font-size: 0.9em; color: #aaa; }
        .input-group-row { display: flex; } .input-group-row label { white-space: nowrap; padding: 10px; background-color: #333; border-radius: 5px 0 0 5px; }
        .input-group-row input { width:100%; border: 1px solid #333; background-color: #222; color: #eee; padding: 10px; border-radius: 0 5px 5px 0; }
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
        .channel-display {font-size:0.8em; color:#666; margin:10px 0;}
        .delay-range-group { display: flex; align-items: center; gap: 5px; }
        .delay-range-group input { text-align: center; }
        .delay-range-group span { color: #888; }
        .mode-selector { display: flex; gap: 10px; background-color: #333; padding: 5px; border-radius: 5px; }
        .mode-selector label { cursor: pointer; padding: 5px 10px; border-radius: 5px; transition: background-color 0.3s; user-select: none;}
        .mode-selector input { display: none; }
        .mode-selector input:checked + label { background-color: #bb86fc; color: #121212; }
        .delay-inputs { display: none; }
        .delay-inputs.visible { display: flex; flex-direction: column; gap: 5px; }
    </style>
</head>
<body>
    <div id="saveStatus" class="save-status"></div>
    <h1>Karuta Bot Control</h1>
    <p>Chọn một chế độ để chạy. Các chế độ Event và AutoClick không thể chạy cùng lúc.</p>
    <div class="container">
        <div class="panel" id="event-bot-panel"><h2>Chế độ 1: Auto Play Event</h2><p style="font-size:0.9em; color:#aaa;">Tự động chơi event với logic phức tạp (di chuyển, tìm quả, xác nhận).</p><div id="event-bot-status" class="status">Trạng thái: ĐÃ DỪNG</div><button id="toggleEventBotBtn">Bật Auto Play</button></div>
        <div class="panel" id="autoclick-panel"><h2>Chế độ 2: Auto Click</h2><p style="font-size:0.9em; color:#aaa;">Chỉ click liên tục vào một nút. Bạn phải tự gõ 'kevent' để bot nhận diện.</p><div id="autoclick-status" class="status">Trạng thái: ĐÃ DỪNG</div><div class="input-group"><label for="autoclick-button-index">Button Index</label><input type="number" id="autoclick-button-index" value="0" min="0"></div><div class="input-group"><label for="autoclick-count">Số lần click (0 = ∞)</label><input type="number" id="autoclick-count" value="10" min="0"></div><button id="toggleAutoclickBtn">Bật Auto Click</button></div>
        <div class="panel" id="auto-kd-panel"><h2>Auto KD</h2><p style="font-size:0.9em; color:#aaa;">Tự động gửi 'kd' khi phát hiện "blessing has activated!" trong kênh KD.</p><div id="auto-kd-status" class="status">Trạng thái: ĐÃ DỪNG</div><div class="channel-display">KD Channel: <span id="kd-channel-display"></span></div><button id="toggleAutoKdBtn">Bật Auto KD</button></div>
        <div class="panel" id="auto-kvi-panel"><h2>Auto KVI (dùng Gemini AI)</h2><p style="font-size:0.9em; color:#aaa;">Tự động tương tác KVI. Dùng AI để chọn câu trả lời tốt nhất.</p><div id="auto-kvi-status" class="status">Trạng thái: ĐÃ DỪNG</div><div class="channel-display">KVI Channel: <span id="kvi-channel-display"></span></div><button id="toggleAutoKviBtn">Bật Auto KVI</button></div>
        <div class="panel"><h2>Tiện ích: Vòng lặp Event</h2><p style="font-size:0.9em; color:#aaa;">Tự động gửi 'kevent' theo chu kỳ. Chỉ hoạt động khi "Chế độ 1" đang chạy.</p><div id="loop-status" class="status">Trạng thái: ĐÃ DỪNG</div><div class="input-group-row"><label for="delay-input">Delay (giây)</label><input type="number" id="delay-input" value="3600"></div><button id="toggleLoopBtn">Bật Vòng lặp</button></div>
    </div>
    <div class="spam-controls">
        <h2>Tiện ích: Spam Tin Nhắn</h2>
        <div id="panel-container"></div>
        <button class="add-panel-btn" onclick="addPanel()">+ Thêm Bảng Spam</button>
    </div>
    <script>
        function showSaveStatus(message, isSuccess) {
            const status = document.getElementById('saveStatus');
            status.textContent = message;
            status.className = 'save-status ' + (isSuccess ? 'save-success' : 'save-error');
            status.style.display = 'block';
            setTimeout(() => status.style.display = 'none', 3000);
        }
        
        async function apiCall(endpoint, method = 'POST', body = null) {
            const options = { method, headers: {'Content-Type': 'application/json'} };
            if (body) options.body = JSON.stringify(body);
            try {
                const response = await fetch(endpoint, options);
                if (!response.ok) {
                    const errorResult = await response.json();
                    showSaveStatus(`Lỗi: ${errorResult.message || 'Unknown error'}`, false);
                    return { error: errorResult.message || 'API call failed' };
                }
                const result = await response.json();
                if (result.save_status !== undefined) {
                    showSaveStatus(result.save_status ? 'Đã lưu thành công' : 'Lỗi khi lưu', result.save_status);
                }
                return result;
            } catch (error) { 
                console.error('API call failed:', error); 
                showSaveStatus('Lỗi kết nối', false);
                return { error: 'API call failed' }; 
            }
        }
        
        async function fetchStatus() {
            const data = await apiCall('/api/status', 'GET');
            if (data.error) { document.getElementById('event-bot-status').textContent = 'Lỗi kết nối server.'; return; }
            const updateStatus = (elemId, text, className, btnId, btnText, panelId, active) => {
                document.getElementById(elemId).textContent = text;
                document.getElementById(elemId).className = className;
                if(btnId) document.getElementById(btnId).textContent = btnText;
                if(panelId) document.getElementById(panelId).classList.toggle('active-mode', active);
            };
            updateStatus('event-bot-status', data.is_event_bot_running ? 'Trạng thái: ĐANG CHẠY' : 'Trạng thái: ĐÃ DỪNG', data.is_event_bot_running ? 'status status-on' : 'status status-off', 'toggleEventBotBtn', data.is_event_bot_running ? 'Dừng Auto Play' : 'Bật Auto Play', 'event-bot-panel', data.is_event_bot_running);
            document.getElementById('toggleEventBotBtn').disabled = data.is_autoclick_running;
            const countText = data.autoclick_count > 0 ? `${data.autoclick_clicks_done}/${data.autoclick_count}` : `${data.autoclick_clicks_done}/∞`;
            updateStatus('autoclick-status', data.is_autoclick_running ? `Trạng thái: ĐANG CHẠY (${countText})` : 'Trạng thái: ĐÃ DỪNG', data.is_autoclick_running ? 'status status-on' : 'status status-off', 'toggleAutoclickBtn', data.is_autoclick_running ? 'Dừng Auto Click' : 'Bật Auto Click', 'autoclick-panel', data.is_autoclick_running);
            document.getElementById('autoclick-button-index').disabled = data.is_autoclick_running; document.getElementById('autoclick-count').disabled = data.is_autoclick_running; document.getElementById('toggleAutoclickBtn').disabled = data.is_event_bot_running;
            updateStatus('auto-kd-status', data.is_auto_kd_running ? 'Trạng thái: ĐANG CHẠY' : 'Trạng thái: ĐÃ DỪNG', data.is_auto_kd_running ? 'status status-on' : 'status status-off', 'toggleAutoKdBtn', data.is_auto_kd_running ? 'Dừng Auto KD' : 'Bật Auto KD', 'auto-kd-panel', data.is_auto_kd_running);
            document.getElementById('kd-channel-display').textContent = data.kd_channel_id;
            updateStatus('auto-kvi-status', data.is_auto_kvi_running ? 'Trạng thái: ĐANG CHẠY' : 'Trạng thái: ĐÃ DỪNG', data.is_auto_kvi_running ? 'status status-on' : 'status status-off', 'toggleAutoKviBtn', data.is_auto_kvi_running ? 'Dừng Auto KVI' : 'Bật Auto KVI', 'auto-kvi-panel', data.is_auto_kvi_running);
            document.getElementById('kvi-channel-display').textContent = data.kvi_channel_id;
            updateStatus('loop-status', data.is_hourly_loop_enabled ? 'Trạng thái: ĐANG CHẠY' : 'Trạng thái: ĐÃ DỪNG', data.is_hourly_loop_enabled ? 'status status-on' : 'status status-off', 'toggleLoopBtn', data.is_hourly_loop_enabled ? 'TẮT VÒNG LẶP' : 'BẬT VÒNG LẶP');
            document.getElementById('toggleLoopBtn').disabled = !data.is_event_bot_running && !data.is_hourly_loop_enabled; document.getElementById('delay-input').value = data.loop_delay_seconds;
        }
        
        document.getElementById('toggleEventBotBtn').addEventListener('click', () => apiCall('/api/toggle_event_bot').then(fetchStatus));
        document.getElementById('toggleAutoclickBtn').addEventListener('click', () => apiCall('/api/toggle_autoclick', 'POST', { button_index: parseInt(document.getElementById('autoclick-button-index').value, 10), count: parseInt(document.getElementById('autoclick-count').value, 10) }).then(fetchStatus));
        document.getElementById('toggleAutoKdBtn').addEventListener('click', () => apiCall('/api/toggle_auto_kd').then(fetchStatus));
        document.getElementById('toggleAutoKviBtn').addEventListener('click', () => apiCall('/api/toggle_auto_kvi').then(fetchStatus));
        document.getElementById('toggleLoopBtn').addEventListener('click', () => apiCall('/api/toggle_hourly_loop', 'POST', { enabled: !document.getElementById('loop-status').textContent.includes('ĐANG CHẠY'), delay: parseInt(document.getElementById('delay-input').value, 10) }).then(fetchStatus));
        
        function createPanelElement(panel) {
            const div = document.createElement('div');
            div.className = `spam-panel ${panel.is_active ? 'active' : ''}`; 
            div.dataset.id = panel.id;
            const isMinutesMode = panel.delay_mode !== 'seconds';
            let countdown = (panel.is_active && panel.next_spam_time) ? Math.max(0, Math.ceil(panel.next_spam_time - (Date.now() / 1000))) : 0;

            div.innerHTML = `
                <div class="input-group"><label>Nội dung spam</label><textarea class="message-input">${panel.message}</textarea></div>
                <div class="input-group"><label>ID Kênh</label><input type="text" class="channel-input" value="${panel.channel_id}"></div>
                
                <div class="input-group">
                    <label>Chế độ Delay</label>
                    <div class="mode-selector">
                        <input type="radio" id="mode-seconds-${panel.id}" name="mode-${panel.id}" value="seconds" ${!isMinutesMode ? 'checked' : ''}><label for="mode-seconds-${panel.id}">Theo Giây</label>
                        <input type="radio" id="mode-minutes-${panel.id}" name="mode-${panel.id}" value="minutes" ${isMinutesMode ? 'checked' : ''}><label for="mode-minutes-${panel.id}">Theo Phút</label>
                    </div>
                </div>

                <div class="delay-inputs delay-inputs-seconds ${!isMinutesMode ? 'visible' : ''}">
                    <label>Delay ngẫu nhiên (giây)</label>
                    <div class="delay-range-group">
                        <input type="number" class="delay-input-min-seconds" value="${panel.delay_min_seconds || 240}"><span>-</span><input type="number" class="delay-input-max-seconds" value="${panel.delay_max_seconds || 300}">
                    </div>
                </div>
                <div class="delay-inputs delay-inputs-minutes ${isMinutesMode ? 'visible' : ''}">
                    <label>Delay ngẫu nhiên (phút)</label>
                    <div class="delay-range-group">
                         <input type="number" class="delay-input-min-minutes" value="${panel.delay_min_minutes || 4}"><span>-</span><input type="number" class="delay-input-max-minutes" value="${panel.delay_max_minutes || 5}">
                    </div>
                </div>

                <div class="spam-panel-controls">
                    <button class="toggle-btn">${panel.is_active ? 'DỪNG' : 'CHẠY'}</button>
                    <button class="delete-btn">XÓA</button>
                </div>
                <div class="timer">Tiếp theo trong: ${panel.is_active ? countdown + 's' : '...'}</div>
            `;
            
            const getPanelData = () => {
                let min_s = parseInt(div.querySelector('.delay-input-min-seconds').value, 10) || 240; let max_s = parseInt(div.querySelector('.delay-input-max-seconds').value, 10) || 300;
                if (min_s > max_s) [min_s, max_s] = [max_s, min_s];
                let min_m = parseInt(div.querySelector('.delay-input-min-minutes').value, 10) || 4; let max_m = parseInt(div.querySelector('.delay-input-max-minutes').value, 10) || 5;
                if (min_m > max_m) [min_m, max_m] = [max_m, min_m];
                return { 
                    ...panel, 
                    message: div.querySelector('.message-input').value, channel_id: div.querySelector('.channel-input').value, 
                    delay_mode: div.querySelector('input[name="mode-' + panel.id + '"]:checked').value,
                    delay_min_seconds: min_s, delay_max_seconds: max_s,
                    delay_min_minutes: min_m, delay_max_minutes: max_m
                }
            };
            
            div.querySelector('.toggle-btn').addEventListener('click', () => apiCall('/api/panel/update', 'POST', { ...getPanelData(), is_active: !panel.is_active }).then(fetchPanels));
            div.querySelector('.delete-btn').addEventListener('click', () => { if (confirm('Bạn có chắc muốn xóa bảng spam này?')) apiCall('/api/panel/delete', 'POST', { id: panel.id }).then(fetchPanels); });
            
            ['message-input', 'channel-input', 'delay-input-min-seconds', 'delay-input-max-seconds', 'delay-input-min-minutes', 'delay-input-max-minutes'].forEach(cls => {
                div.querySelector('.' + cls).addEventListener('change', () => apiCall('/api/panel/update', 'POST', getPanelData()));
            });

            div.querySelectorAll('input[name="mode-' + panel.id + '"]').forEach(radio => {
                radio.addEventListener('change', (e) => {
                    div.querySelector('.delay-inputs-seconds').classList.toggle('visible', e.target.value === 'seconds');
                    div.querySelector('.delay-inputs-minutes').classList.toggle('visible', e.target.value === 'minutes');
                    apiCall('/api/panel/update', 'POST', getPanelData());
                });
            });
            
            return div;
        }
        
        async function fetchPanels() {
            if (document.activeElement && ['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) return;
            const data = await apiCall('/api/panels', 'GET');
            const container = document.getElementById('panel-container'); 
            container.innerHTML = '';
            if (data.panels) data.panels.forEach(panel => container.appendChild(createPanelElement(panel)));
        }
        
        async function addPanel() { await apiCall('/api/panel/add'); fetchPanels(); }
        
        document.addEventListener('DOMContentLoaded', () => {
            fetchStatus(); fetchPanels();
            setInterval(fetchStatus, 5000); setInterval(fetchPanels, 1000);
        });
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route("/api/status", methods=['GET'])
def status():
    with lock:
        return jsonify({
            "is_event_bot_running": is_event_bot_running,
            "is_hourly_loop_enabled": is_hourly_loop_enabled,
            "loop_delay_seconds": loop_delay_seconds,
            "is_autoclick_running": is_autoclick_running,
            "autoclick_button_index": autoclick_button_index,
            "autoclick_count": autoclick_count,
            "autoclick_clicks_done": autoclick_clicks_done,
            "is_auto_kd_running": is_auto_kd_running,
            "kd_channel_id": KD_CHANNEL_ID or "Chưa cấu hình",
            "is_auto_kvi_running": is_auto_kvi_running,
            "kvi_channel_id": KVI_CHANNEL_ID or "Chưa cấu hình"
        })

@app.route("/api/toggle_event_bot", methods=['POST'])
def toggle_event_bot():
    global event_bot_thread, is_event_bot_running, is_autoclick_running
    with lock:
        if is_autoclick_running:
            return jsonify({"status": "error", "message": "Auto Click is running. Stop it first."}), 400
        
        if is_event_bot_running:
            is_event_bot_running = False
            print("[CONTROL] Nhận lệnh DỪNG Bot Event.", flush=True)
        else:
            is_event_bot_running = True
            print("[CONTROL] Nhận lệnh BẬT Bot Event.", flush=True)
            event_bot_thread = threading.Thread(target=run_event_bot_thread, daemon=True)
            event_bot_thread.start()
        
        save_result = save_settings()
    return jsonify({"status": "ok", "save_status": save_result})

@app.route("/api/toggle_autoclick", methods=['POST'])
def toggle_autoclick():
    global autoclick_bot_thread, is_autoclick_running, is_event_bot_running
    global autoclick_button_index, autoclick_count, autoclick_clicks_done, autoclick_target_message_data
    data = request.get_json()
    with lock:
        if is_event_bot_running:
            return jsonify({"status": "error", "message": "Event Bot is running. Stop it first."}), 400
            
        if is_autoclick_running:
            is_autoclick_running = False
            print("[CONTROL] Nhận lệnh DỪNG Auto Click.", flush=True)
        else:
            is_autoclick_running = True
            autoclick_button_index = int(data.get('button_index', 0))
            autoclick_count = int(data.get('count', 1))
            autoclick_clicks_done = 0
            autoclick_target_message_data = None
            print(f"[CONTROL] Nhận lệnh BẬT Auto Click: {autoclick_count or 'vô hạn'} lần vào button {autoclick_button_index}.", flush=True)
            autoclick_bot_thread = threading.Thread(target=run_autoclick_bot_thread, daemon=True)
            autoclick_bot_thread.start()
        
        save_result = save_settings()
    return jsonify({"status": "ok", "save_status": save_result})

@app.route("/api/toggle_auto_kd", methods=['POST'])
def toggle_auto_kd():
    global auto_kd_thread, is_auto_kd_running
    with lock:
        if not KD_CHANNEL_ID:
            return jsonify({"status": "error", "message": "Chưa cấu hình KD_CHANNEL_ID."}), 400
        
        if is_auto_kd_running:
            is_auto_kd_running = False
            print("[CONTROL] Nhận lệnh DỪNG Auto KD.", flush=True)
        else:
            is_auto_kd_running = True
            print("[CONTROL] Nhận lệnh BẬT Auto KD.", flush=True)
            auto_kd_thread = threading.Thread(target=run_auto_kd_thread, daemon=True)
            auto_kd_thread.start()
        
        save_result = save_settings()
    return jsonify({"status": "ok", "save_status": save_result})

@app.route("/api/toggle_auto_kvi", methods=['POST'])
def toggle_auto_kvi():
    global auto_kvi_thread, is_auto_kvi_running
    with lock:
        if not KVI_CHANNEL_ID or not GEMINI_API_KEY:
            return jsonify({"status": "error", "message": "Chưa cấu hình KVI_CHANNEL_ID hoặc GEMINI_API_KEY."}), 400
        
        if is_auto_kvi_running:
            is_auto_kvi_running = False
            print("[CONTROL] Nhận lệnh DỪNG Auto KVI.", flush=True)
        else:
            is_auto_kvi_running = True
            print("[CONTROL] Nhận lệnh BẬT Auto KVI.", flush=True)
            auto_kvi_thread = threading.Thread(target=run_auto_kvi_thread, daemon=True)
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
        if is_hourly_loop_enabled:
            if hourly_loop_thread is None or not hourly_loop_thread.is_alive():
                hourly_loop_thread = threading.Thread(target=run_hourly_loop_thread, daemon=True)
                hourly_loop_thread.start()
            print(f"[CONTROL] Vòng lặp ĐÃ BẬT với delay {loop_delay_seconds} giây.", flush=True)
        else:
            print("[CONTROL] Vòng lặp ĐÃ TẮT.", flush=True)
        
        save_result = save_settings()
    return jsonify({"status": "ok", "save_status": save_result})

# ===================================================================
# API CHO SPAM PANEL
# ===================================================================
@app.route("/api/panels", methods=['GET'])
def get_panels():
    with lock:
        return jsonify({"panels": spam_panels})

@app.route("/api/panel/add", methods=['POST'])
def add_panel():
    global panel_id_counter
    with lock:
        new_panel = { 
            "id": panel_id_counter, 
            "message": "", 
            "channel_id": "", 
            "delay_mode": "minutes",
            "delay_min_minutes": 4, 
            "delay_max_minutes": 5,
            "delay_min_seconds": 240,
            "delay_max_seconds": 300,
            "is_active": False, 
            "next_spam_time": 0 
        }
        spam_panels.append(new_panel)
        panel_id_counter += 1
        save_result = save_settings()
    return jsonify({"status": "ok", "new_panel": new_panel, "save_status": save_result})

@app.route("/api/panel/update", methods=['POST'])
def update_panel():
    data = request.get_json()
    with lock:
        for panel in spam_panels:
            if panel['id'] == data['id']:
                is_activating = data.get('is_active') and not panel.get('is_active')
                if is_activating:
                    initial_delay = get_new_random_delay(data)
                    data['next_spam_time'] = time.time() + initial_delay
                    print(f"[SPAM CONTROL] Panel {panel['id']} đã kích hoạt, hẹn giờ sau {initial_delay:.2f} giây.", flush=True)
                
                panel.update(data)
                break
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
    load_settings()
    restore_bot_states()

    spam_thread = threading.Thread(target=spam_loop, daemon=True)
    spam_thread.start()
    
    port = int(os.environ.get("PORT", 10000))
    print(f"[SERVER] Khởi động Web Server tại http://0.0.0.0:{port}", flush=True)
    app.run(host="0.0.0.0", port=port, debug=False)
