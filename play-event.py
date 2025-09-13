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
            'is_autoclick_running': is_autoclick_running,
            'is_auto_kvi_running': is_auto_kvi_running,
            'is_hourly_loop_enabled': is_hourly_loop_enabled,
            'loop_delay_seconds': loop_delay_seconds,
            'spam_panels': spam_panels,
            'panel_id_counter': panel_id_counter,
            'autoclick_button_index': autoclick_button_index,
            'autoclick_count': autoclick_count,
            'autoclick_clicks_done': autoclick_clicks_done
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

                    print("[SETTINGS] INFO: Đã tải cài đặt từ JSONBin.io thành công.", flush=True)
                    print(f"[SETTINGS] INFO: Event Bot: {is_event_bot_running}, Auto KD: {is_auto_kd_running}, Auto Click: {is_autoclick_running}, Auto KVI: {is_auto_kvi_running}", flush=True)
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
        max_retries = 40
        for attempt in range(max_retries):
            session_id = bot.gateway.session_id
            payload = { "type": 3, "guild_id": message_data.get("guild_id"), "channel_id": message_data.get("channel_id"), "message_id": message_data.get("id"), "application_id": application_id, "session_id": session_id, "data": {"component_type": 2, "custom_id": custom_id} }
            emoji_name = button_to_click.get('emoji', {}).get('name', 'Không có')
            print(f"[{source}] INFO (Lần {attempt + 1}/{max_retries}): Chuẩn bị click button {index} (Emoji: {emoji_name})", flush=True)
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

def send_interaction(bot, message_data, custom_id, source=""):
    try:
        if not bot or not bot.gateway.session_id:
            print(f"[{source}] LỖI: Bot chưa kết nối hoặc không có session_id.", flush=True)
            return False
        
        application_id = message_data.get("application_id", KARUTA_ID)
        headers = {"Authorization": TOKEN}
        max_retries = 10
        
        for attempt in range(max_retries):
            session_id = bot.gateway.session_id
            payload = { "type": 3, "guild_id": message_data.get("guild_id"), "channel_id": message_data.get("channel_id"), "message_id": message_data.get("id"), "application_id": application_id, "session_id": session_id, "data": {"component_type": 2, "custom_id": custom_id} }
            
            print(f"[{source}] INFO (Lần {attempt + 1}/{max_retries}): Chuẩn bị click button (ID: {custom_id})", flush=True)
            
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
        print(f"[{source}] LỖI NGOẠI LỆ trong hàm send_interaction: {e}", flush=True)
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

def run_auto_kvi_thread():
    global is_auto_kvi_running, auto_kvi_instance
    
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
    KVI_COOLDOWN_SECONDS = 5
    KVI_TIMEOUT_SECONDS = 7200
    
    def answer_question_with_gemini(bot_instance, message_data, question, options):
        print(f"[AUTO KVI] GEMINI: Nhận được câu hỏi: '{question}'", flush=True)
        
        try:
            prompt = f"""You are an expert in the Discord game Karuta's KVI (Karuta Visit Interaction). Your goal is to choose the best, most positive, or most logical answer to continue a friendly conversation.
Based on the following question, choose the best answer from the options provided.

Question: "{question}"

Options:
{chr(10).join([f"{i+1}. {opt}" for i, opt in enumerate(options)])}

Please respond with ONLY the number of the best option. For example: 3"""

            payload = { "contents": [{"parts": [{"text": prompt}]}] }
            api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
            
            response = requests.post(api_url, headers={'Content-Type': 'application/json'}, json=payload, timeout=20)
            response.raise_for_status()
            
            result = response.json()
            api_text = result['candidates'][0]['content']['parts'][0]['text']
            
            match = re.search(r'\d+', api_text)
            if match:
                selected_option = int(match.group(0))
                if not (1 <= selected_option <= len(options)):
                    print(f"[AUTO KVI] LỖI: Gemini trả về số không hợp lệ: {selected_option}", flush=True)
                    return
                
                print(f"[AUTO KVI] GEMINI: Gemini đã chọn câu trả lời số {selected_option}: '{options[selected_option-1]}'", flush=True)
                
                button_index_to_click = selected_option - 1
                
                print(f"[AUTO KVI] INFO: Sẽ bấm vào nút ở vị trí index {button_index_to_click}", flush=True)
                time.sleep(2)
                
                click_button_by_index(bot_instance, message_data, button_index_to_click, "AUTO KVI")
            else:
                print(f"[AUTO KVI] LỖI: Không tìm thấy số trong câu trả lời của Gemini: '{api_text}'", flush=True)

        except requests.exceptions.RequestException as e:
            print(f"[AUTO KVI] LỖI YÊU CẦU API: {e}", flush=True)
        except Exception as e:
            print(f"[AUTO KVI] LỖI NGOẠI LỆ: Exception khi gọi Gemini: {e}", flush=True)

    # =================== BẮT ĐẦU KHỐI CODE ĐÃ SỬA ===================
    @bot.gateway.command
    def on_message(resp):
        nonlocal last_action_time, last_api_call_time

        with lock:
            if not is_auto_kvi_running: return
        
        if not (resp.event.message or resp.event.message_updated): return
        
        m = resp.parsed.auto()
        if not (m.get("author", {}).get("id") == KARUTA_ID and m.get("channel_id") == KVI_CHANNEL_ID): return

        current_time = time.time()
        
        # Cập nhật thời gian hoạt động tổng thể (dùng cho timeout 7200s)
        last_action_time = time.time()
        
        embeds = m.get("embeds", [])
        action_taken = False
        if embeds:
            embed = embeds[0]
            desc = embed.get("description", "")
            
            # --- XỬ LÝ KHI CÓ CÂU HỎI ---
            question_match = re.search(r'["“](.+?)["”]', desc)
            if question_match:
                # Di chuyển kiểm tra cooldown vào đây
                if current_time - last_api_call_time < KVI_COOLDOWN_SECONDS:
                    return # Bỏ qua nếu đang trong thời gian chờ để tránh spam API

                question = question_match.group(1)
                options = []
                options_part = desc.split(question_match.group(0))[-1]
                for line in options_part.split('\n'):
                    cleaned_line = re.sub(r'^\s*[^a-zA-Z]+', '', line).strip()
                    if cleaned_line and "Choose the response" not in cleaned_line:
                        options.append(cleaned_line)

                if question and options:
                    last_api_call_time = time.time() # Đặt lại thời gian chờ NGAY TRƯỚC KHI gọi AI
                    action_taken = True
                    threading.Thread(target=answer_question_with_gemini, args=(bot, m, question, options)).start()
                    return

            # Xử lý dạng câu hỏi thứ hai (ít gặp hơn)
            fields = embed.get("fields", [])
            if not action_taken and desc.startswith('"') and fields:
                if current_time - last_api_call_time < KVI_COOLDOWN_SECONDS:
                    return

                question = desc.strip('"')
                options = [f.get("value", "") for f in fields if f.get("name", "").isdigit()]
                if question and options:
                    last_api_call_time = time.time()
                    action_taken = True
                    threading.Thread(target=answer_question_with_gemini, args=(bot, m, question, options)).start()
                    return

        # --- XỬ LÝ KHI KHÔNG CÓ CÂU HỎI (Bấm nút mặc định như "Talk") ---
        if not action_taken:
            # Thêm kiểm tra cooldown ở đây để tránh click liên tục nếu bị kẹt
            if current_time - last_api_call_time < KVI_COOLDOWN_SECONDS:
                return

            components = m.get("components", [])
            all_buttons = [button for row in components for button in row.get("components", [])]
            button_priority_order = ["Talk", "Actions", "Date", "Propose", "Continue"]
            
            for label in button_priority_order:
                target_button = next((btn for btn in all_buttons if btn.get("label") == label), None)
                if target_button and target_button.get("custom_id") and not target_button.get("disabled"):
                    last_api_call_time = time.time() # Đặt lại thời gian chờ khi bấm nút "Talk"
                    threading.Thread(target=send_interaction, args=(bot, m, target_button.get("custom_id"), "AUTO KVI")).start()
                    return
    # =================== KẾT THÚC KHỐI CODE ĐÃ SỬA ===================

    def periodic_kvi_sender():
        nonlocal last_action_time
        time.sleep(10)
        bot.sendMessage(KVI_CHANNEL_ID, "kvi")
        last_action_time = time.time()
        
        while True:
            with lock:
                if not is_auto_kvi_running: break
            
            if time.time() - last_action_time > KVI_TIMEOUT_SECONDS:
                 bot.sendMessage(KVI_CHANNEL_ID, "kvi")
                 last_action_time = time.time()
            
            time.sleep(60)

    @bot.gateway.command
    def on_ready(resp):
        if resp.event.ready_supplemental:
             print("[AUTO KVI] Gateway sẵn sàng.", flush=True)
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

def spam_loop():
    bot = discum.Client(token=TOKEN, log=False)
    @bot.gateway.command
    def on_ready(resp):
        if resp.event.ready: print("[SPAM BOT] Gateway đã kết nối.", flush=True)
    threading.Thread(target=bot.gateway.run, daemon=True).start()
    time.sleep(5) 
    while True:
        try:
            with lock: panels_to_process = list(spam_panels)
            for panel in panels_to_process:
                if panel['is_active'] and panel['channel_id'] and panel['message']:
                    if time.time() - panel.get('last_spam_time', 0) >= panel['delay']:
                        try:
                            bot.sendMessage(str(panel['channel_id']), str(panel['message']))
                            with lock:
                                for p in spam_panels:
                                    if p['id'] == panel['id']: 
                                        p['last_spam_time'] = time.time()
                                        break
                                save_settings()
                        except Exception as e:
                            print(f"LỖI SPAM: Không thể gửi tin. {e}", flush=True)
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
    
    if is_autoclick_running:
        print("[RESTORE] Khôi phục Auto Click...", flush=True)
        autoclick_bot_thread = threading.Thread(target=run_autoclick_bot_thread, daemon=True)
        autoclick_bot_thread.start()

    if is_auto_kvi_running and KVI_CHANNEL_ID and GEMINI_API_KEY:
        print("[RESTORE] Khôi phục Auto KVI...", flush=True)
        auto_kvi_thread = threading.Thread(target=run_auto_kvi_thread, daemon=True)
        auto_kvi_thread.start()
    
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
    </style>
</head>
<body>
    <div id="saveStatus" class="save-status"></div>
    <h1>Karuta Bot Control</h1>
    <p>Chọn một chế độ để chạy. Các chế độ chính (Auto Play, Auto Click, Auto KVI) không thể chạy cùng lúc.</p>

    <div class="panel" style="max-width: 840px; text-align: left; background-color: #2a2a2a; padding: 25px; margin-bottom: 20px;">
        <h2 style="text-align: center; margin-top: 0;">🛒 <strong>BUYING PRICE LIST</strong> 🛒</h2>
        <pre style="font-family: Consolas, 'Courier New', monospace; color: #e0e0e0; font-size: 1.1em; white-space: pre-wrap; line-height: 1.6;">
══════════════════════════
<strong>MATERIALS</strong>
▸ Buying <strong>Gems</strong> 💎 | 17 Gems = 1 Ticket 🎟️
▸ Buying <strong>Gold</strong> 💰 | 3300 Gold = 1 Ticket 🎟️
▸ Buying <strong>Bits</strong> ✨ | 2500 Bits = 1 Ticket 🎟️

<strong>ORBS</strong>
▸ Buying <strong>Swap Orb</strong> 🔮 | 3 Tickets 🎟️ = 1 Orb 
▸ Buying <strong>Upgrade Orb</strong> 🔮 | 2 Tickets 🎟️ = 1 Orb
══════════════════════════
<strong>Ping or DM me if you're selling!</strong></pre>
    </div>

    <div class="container">
        <div class="panel" id="event-bot-panel">
            <h2>Chế độ 1: Auto Play Event</h2>
            <p style="font-size:0.9em; color:#aaa;">Tự động chơi event với logic phức tạp (di chuyển, tìm quả, xác nhận).</p>
            <div id="event-bot-status" class="status">Trạng thái: ĐÃ DỪNG</div>
            <button id="toggleEventBotBtn">Bật Auto Play</button>
        </div>
        <div class="panel" id="autoclick-panel">
            <h2>Chế độ 2: Auto Click</h2>
            <p style="font-size:0.9em; color:#aaa;">Chỉ click liên tục vào một nút. Bạn phải tự gõ 'kevent' để bot nhận diện.</p>
            <div id="autoclick-status" class="status">Trạng thái: ĐÃ DỪNG</div>
            <div class="input-group">
                <label for="autoclick-button-index">Button Index</label>
                <input type="number" id="autoclick-button-index" value="0" min="0">
            </div>
            <div class="input-group">
                <label for="autoclick-count">Số lần click</label>
                <input type="number" id="autoclick-count" value="10" min="0">
            </div>
            <p style="font-size:0.8em; color:#888; margin:0;">Nhập 0 để click vô hạn</p>
            <button id="toggleAutoclickBtn">Bật Auto Click</button>
        </div>
        <div class="panel" id="auto-kvi-panel">
            <h2>Chế độ 3: Auto KVI</h2>
            <p style="font-size:0.9em; color:#aaa;">Tự động nói chuyện với nhân vật (kvi) bằng AI (Gemini).</p>
            <div id="auto-kvi-status" class="status">Trạng thái: ĐÃ DỪNG</div>
            <div style="font-size:0.8em; color:#666; margin:10px 0;">
                KVI Channel: <span id="kvi-channel-display">Đang tải...</span>
            </div>
            <button id="toggleAutoKviBtn">Bật Auto KVI</button>
        </div>
        <div class="panel" id="auto-kd-panel">
            <h2>Tiện ích: Auto KD</h2>
            <p style="font-size:0.9em; color:#aaa;">Tự động gửi 'kd' khi phát hiện "blessing has activated!" trong kênh KD.</p>
            <div id="auto-kd-status" class="status">Trạng thái: ĐÃ DỪNG</div>
            <div style="font-size:0.8em; color:#666; margin:10px 0;">
                KD Channel: <span id="kd-channel-display">Đang tải...</span>
            </div>
            <button id="toggleAutoKdBtn">Bật Auto KD</button>
        </div>
        <div class="panel">
            <h2>Tiện ích: Vòng lặp</h2>
            <p style="font-size:0.9em; color:#aaa;">Tự động gửi 'kevent' theo chu kỳ. Chỉ hoạt động khi "Chế độ 1" đang chạy.</p>
            <div id="loop-status" class="status">Trạng thái: ĐÃ DỪNG</div>
            <div class="input-group">
                <label for="delay-input">Delay (giây)</label>
                <input type="number" id="delay-input" value="3600">
            </div>
            <button id="toggleLoopBtn">Bật Vòng lặp</button>
        </div>
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
                const result = await response.json();
                if (response.status !== 200 && result.message) {
                     showSaveStatus(result.message, false);
                } else if (result.save_status !== undefined) {
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
            if (data.error) { 
                document.getElementById('event-bot-status').textContent = 'Lỗi kết nối server.'; 
                return; 
            }
            
            const eventBotStatusDiv = document.getElementById('event-bot-status'), toggleEventBotBtn = document.getElementById('toggleEventBotBtn');
            eventBotStatusDiv.textContent = data.is_event_bot_running ? 'Trạng thái: ĐANG CHẠY' : 'Trạng thái: ĐÃ DỪNG';
            eventBotStatusDiv.className = data.is_event_bot_running ? 'status status-on' : 'status status-off';
            toggleEventBotBtn.textContent = data.is_event_bot_running ? 'Dừng Auto Play' : 'Bật Auto Play';
            toggleEventBotBtn.disabled = data.is_autoclick_running || data.is_auto_kvi_running;
            document.getElementById('event-bot-panel').classList.toggle('active-mode', data.is_event_bot_running);

            const autoclickStatusDiv = document.getElementById('autoclick-status'), toggleAutoclickBtn = document.getElementById('toggleAutoclickBtn');
            const countText = data.autoclick_count > 0 ? `${data.autoclick_clicks_done}/${data.autoclick_count}` : `${data.autoclick_clicks_done}/∞`;
            autoclickStatusDiv.textContent = data.is_autoclick_running ? `Trạng thái: ĐANG CHẠY (${countText})` : 'Trạng thái: ĐÃ DỪNG';
            autoclickStatusDiv.className = data.is_autoclick_running ? 'status status-on' : 'status status-off';
            toggleAutoclickBtn.textContent = data.is_autoclick_running ? 'Dừng Auto Click' : 'Bật Auto Click';
            document.getElementById('autoclick-button-index').disabled = data.is_autoclick_running;
            document.getElementById('autoclick-count').disabled = data.is_autoclick_running;
            toggleAutoclickBtn.disabled = data.is_event_bot_running || data.is_auto_kvi_running;
            document.getElementById('autoclick-panel').classList.toggle('active-mode', data.is_autoclick_running);

            const autoKviStatusDiv = document.getElementById('auto-kvi-status'), toggleAutoKviBtn = document.getElementById('toggleAutoKviBtn');
            autoKviStatusDiv.textContent = data.is_auto_kvi_running ? 'Trạng thái: ĐANG CHẠY' : 'Trạng thái: ĐÃ DỪNG';
            autoKviStatusDiv.className = data.is_auto_kvi_running ? 'status status-on' : 'status status-off';
            toggleAutoKviBtn.textContent = data.is_auto_kvi_running ? 'Dừng Auto KVI' : 'Bật Auto KVI';
            toggleAutoKviBtn.disabled = data.is_event_bot_running || data.is_autoclick_running;
            document.getElementById('auto-kvi-panel').classList.toggle('active-mode', data.is_auto_kvi_running);
            document.getElementById('kvi-channel-display').textContent = data.kvi_channel_id;

            document.getElementById('auto-kd-status').textContent = data.is_auto_kd_running ? 'Trạng thái: ĐANG CHẠY' : 'Trạng thái: ĐÃ DỪNG';
            document.getElementById('auto-kd-status').className = data.is_auto_kd_running ? 'status status-on' : 'status status-off';
            document.getElementById('toggleAutoKdBtn').textContent = data.is_auto_kd_running ? 'Dừng Auto KD' : 'Bật Auto KD';
            document.getElementById('auto-kd-panel').classList.toggle('active-mode', data.is_auto_kd_running);
            document.getElementById('kd-channel-display').textContent = data.kd_channel_id;

            const loopStatusDiv = document.getElementById('loop-status'), toggleLoopBtn = document.getElementById('toggleLoopBtn');
            loopStatusDiv.textContent = data.is_hourly_loop_enabled ? 'Trạng thái: ĐANG CHẠY' : 'Trạng thái: ĐÃ DỪNG';
            loopStatusDiv.className = data.is_hourly_loop_enabled ? 'status status-on' : 'status status-off';
            toggleLoopBtn.textContent = data.is_hourly_loop_enabled ? 'TẮT VÒNG LẶP' : 'BẬT VÒNG LẶP';
            toggleLoopBtn.disabled = !data.is_event_bot_running && !data.is_hourly_loop_enabled;
            document.getElementById('delay-input').value = data.loop_delay_seconds;
        }
        
        document.getElementById('toggleEventBotBtn').addEventListener('click', () => apiCall('/api/toggle_event_bot').then(fetchStatus));
        document.getElementById('toggleAutoclickBtn').addEventListener('click', () => {
            apiCall('/api/toggle_autoclick', 'POST', { 
                button_index: parseInt(document.getElementById('autoclick-button-index').value, 10), 
                count: parseInt(document.getElementById('autoclick-count').value, 10) 
            }).then(fetchStatus);
        });
        document.getElementById('toggleAutoKviBtn').addEventListener('click', () => apiCall('/api/toggle_auto_kvi').then(fetchStatus));
        document.getElementById('toggleAutoKdBtn').addEventListener('click', () => apiCall('/api/toggle_auto_kd').then(fetchStatus));
        document.getElementById('toggleLoopBtn').addEventListener('click', () => {
            const isEnabled = !document.getElementById('loop-status').textContent.includes('ĐANG CHẠY');
            apiCall('/api/toggle_hourly_loop', 'POST', { 
                enabled: isEnabled, 
                delay: parseInt(document.getElementById('delay-input').value, 10) 
            }).then(fetchStatus);
        });
        
        function createPanelElement(panel) {
            const div = document.createElement('div');
            div.className = `spam-panel ${panel.is_active ? 'active' : ''}`; 
            div.dataset.id = panel.id;
            let countdown = panel.is_active && panel.last_spam_time ? panel.delay - (Date.now() / 1000 - panel.last_spam_time) : panel.delay;
            countdown = Math.max(0, Math.ceil(countdown));
            div.innerHTML = `
                <textarea class="message-input" placeholder="Nội dung spam...">${panel.message}</textarea>
                <input type="text" class="channel-input" placeholder="ID Kênh..." value="${panel.channel_id}">
                <input type="number" class="delay-input" placeholder="Delay (giây)..." value="${panel.delay}">
                <div class="spam-panel-controls">
                    <button class="toggle-btn">${panel.is_active ? 'TẮT' : 'BẬT'}</button>
                    <button class="delete-btn">XÓA</button>
                </div>
                <div class="timer">Hẹn giờ: ${countdown}s</div>
            `;
            
            const getPanelData = () => ({ 
                ...panel, 
                message: div.querySelector('.message-input').value, 
                channel_id: div.querySelector('.channel-input').value, 
                delay: parseInt(div.querySelector('.delay-input').value, 10) || 60 
            });
            
            div.querySelector('.toggle-btn').addEventListener('click', () => 
                apiCall('/api/panel/update', 'POST', { ...getPanelData(), is_active: !panel.is_active }).then(fetchPanels)
            );
            div.querySelector('.delete-btn').addEventListener('click', () => { 
                if (confirm('Xóa bảng này?')) 
                    apiCall('/api/panel/delete', 'POST', { id: panel.id }).then(fetchPanels); 
            });
            ['.message-input', '.channel-input', '.delay-input'].forEach(selector => {
                div.querySelector(selector).addEventListener('change', () => 
                    apiCall('/api/panel/update', 'POST', getPanelData())
                );
            });
            
            return div;
        }
        
        async function fetchPanels() {
            const focusedEl = document.activeElement;
            if (focusedEl && focusedEl.closest('.spam-panel')) return;
            const data = await apiCall('/api/panels', 'GET');
            const container = document.getElementById('panel-container'); 
            container.innerHTML = '';
            if (data.panels) data.panels.forEach(panel => container.appendChild(createPanelElement(panel)));
        }
        
        async function addPanel() { 
            await apiCall('/api/panel/add'); 
            fetchPanels(); 
        }
        
        document.addEventListener('DOMContentLoaded', () => {
            fetchStatus(); fetchPanels();
            setInterval(fetchStatus, 2000); setInterval(fetchPanels, 2000);
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
    global event_bot_thread, is_event_bot_running
    with lock:
        if is_autoclick_running or is_auto_kvi_running:
            return jsonify({"status": "error", "message": "Chế độ khác đang chạy. Dừng nó trước."}), 400
        
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
    global autoclick_bot_thread, is_autoclick_running
    global autoclick_button_index, autoclick_count, autoclick_clicks_done, autoclick_target_message_data
    data = request.get_json()
    with lock:
        if is_event_bot_running or is_auto_kvi_running:
            return jsonify({"status": "error", "message": "Chế độ khác đang chạy. Dừng nó trước."}), 400
            
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
        if is_event_bot_running or is_autoclick_running:
            return jsonify({"status": "error", "message": "Chế độ khác đang chạy. Dừng nó trước."}), 400
        
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
        new_panel = { "id": panel_id_counter, "message": "", "channel_id": "", "delay": 60, "is_active": False, "last_spam_time": 0 }
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
                if data.get('is_active') and not panel.get('is_active'):
                    data['last_spam_time'] = 0
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
