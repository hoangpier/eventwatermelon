import discum
import time
import threading
import json
import random
import requests
import os
import sys
from collections import deque
from flask import Flask, jsonify, render_template_string, request

# ===================================================================
# CẤU HÌNH VÀ BIẾN TOÀN CỤC
# ===================================================================

# --- Lấy cấu hình từ biến môi trường ---
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
KARUTA_ID = "646937666251915264"

# --- Kiểm tra biến môi trường ---
if not TOKEN or not CHANNEL_ID:
    print("LỖI: Vui lòng cung cấp DISCORD_TOKEN và CHANNEL_ID trong biến môi trường.", flush=True)
    sys.exit(1)

# --- Các biến trạng thái và điều khiển ---
lock = threading.RLock()

# Bot Event
event_bot_thread = None
event_bot_instance = None
is_event_bot_running = False

# Vòng lặp tự động
hourly_loop_thread = None
is_hourly_loop_enabled = False
loop_delay_seconds = 3600

# Auto Click
autoclick_bot_thread = None
autoclick_bot_instance = None
is_autoclick_running = False
autoclick_button_index = 0
autoclick_count = 0
autoclick_clicks_done = 0
autoclick_target_message_data = None

# Spam
spam_panels = []
panel_id_counter = 0
spam_thread = None


# ===================================================================
# HÀM CLICK BUTTON (DÙNG CHUNG)
# ===================================================================

def click_button_by_index(bot, message_data, index, source=""):
    """
    Hàm chung để click vào một button trên tin nhắn dựa vào vị trí (index).
    FIX: Đã khôi phục vòng lặp thử lại 40 lần.
    """
    try:
        if not bot or not bot.gateway.session_id:
            print(f"[{source}] LỖI: Bot chưa kết nối hoặc không có session_id. Không thể click.", flush=True)
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
        
        # FIX: Khôi phục vòng lặp thử lại 40 lần
        max_retries = 40
        for attempt in range(max_retries):
            session_id = bot.gateway.session_id
            payload = {
                "type": 3, "guild_id": message_data.get("guild_id"),
                "channel_id": message_data.get("channel_id"), "message_id": message_data.get("id"),
                "application_id": application_id,
                "session_id": session_id,
                "data": {"component_type": 2, "custom_id": custom_id}
            }

            emoji_name = button_to_click.get('emoji', {}).get('name', 'Không có')
            print(f"[{source}] INFO (Lần {attempt + 1}/{max_retries}): Chuẩn bị click button ở vị trí {index} (Emoji: {emoji_name})", flush=True)

            try:
                r = requests.post("https://discord.com/api/v9/interactions", headers=headers, json=payload, timeout=10)
                if 200 <= r.status_code < 300:
                    print(f"[{source}] INFO: Click thành công! (Status: {r.status_code})", flush=True)
                    time.sleep(random.uniform(2.5, 3.5))
                    return True # Thoát khỏi hàm nếu thành công
                elif r.status_code == 429:
                    retry_after = r.json().get("retry_after", 1.5)
                    print(f"[{source}] WARN: Bị rate limit! Sẽ thử lại sau {retry_after:.2f} giây...", flush=True)
                    time.sleep(retry_after)
                else:
                    print(f"[{source}] LỖI: Click thất bại! (Status: {r.status_code}, Response: {r.text})", flush=True)
                    # Không thoát ngay, để vòng lặp thử lại
                    time.sleep(2) # Chờ 1 chút trước khi thử lại
            except requests.exceptions.RequestException as e:
                print(f"[{source}] LỖI KẾT NỐI: {e}. Sẽ thử lại sau 3 giây...", flush=True)
                time.sleep(3)
        
        print(f"[{source}] LỖI: Đã thử click {max_retries} lần mà không thành công.", flush=True)
        return False # Trả về False sau khi hết số lần thử
        
    except Exception as e:
        print(f"[{source}] LỖI NGOẠI LỆ trong hàm click_button_by_index: {e}", flush=True)
        return False

# ===================================================================
# LOGIC BOT EVENT (CHẾ ĐỘ 1)
# ===================================================================
def run_event_bot_thread():
    """Chạy bot tự động chơi event phức tạp."""
    global is_event_bot_running, event_bot_instance
    
    active_message_id = None
    action_queue = deque()
    bot = discum.Client(token=TOKEN, log=False)
    
    with lock:
        event_bot_instance = bot

    def perform_final_confirmation(message_data):
        print("[EVENT BOT] ACTION: Chờ 2 giây để nút xác nhận cuối cùng load...", flush=True)
        time.sleep(2)
        click_button_by_index(bot, message_data, 2, "EVENT BOT")
        print("[EVENT BOT] INFO: Đã hoàn thành lượt. Chờ game tự động cập nhật để bắt đầu lượt mới...", flush=True)

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
                print(f"\n[EVENT BOT] INFO: Đã phát hiện game mới. Chuyển sang tin nhắn ID: {active_message_id}", flush=True)

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
                    print("[EVENT BOT] INFO: NGẮT QUÃNG - Phát hiện nước đi có kết quả. Xác nhận ngay.", flush=True)
                    action_queue.clear()
                    action_queue.append(0)
                elif not action_queue:
                    print("[EVENT BOT] INFO: Bắt đầu lượt mới. Tạo chuỗi hành động...", flush=True)
                    fixed_sequence = [1, 1, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 1, 1, 1, 1, 2, 2, 3, 3]
                    action_queue.extend(fixed_sequence)
                    random_sequence = [random.choice([1,2,3,4]) for _ in range(random.randint(4, 12))]
                    action_queue.extend(random_sequence)
                    action_queue.append(0)
                    print(f"[EVENT BOT] INFO: Chuỗi hành động mới có tổng cộng {len(action_queue)} bước.", flush=True)

                if action_queue:
                    next_action_index = action_queue.popleft()
                    threading.Thread(target=click_button_by_index, args=(bot, m, next_action_index, "EVENT BOT")).start()

    @bot.gateway.command
    def on_ready(resp):
        if resp.event.ready_supplemental:
            print("[EVENT BOT] Gateway đã sẵn sàng. Gửi lệnh 'kevent' đầu tiên...", flush=True)
            bot.sendMessage(CHANNEL_ID, "kevent")

    print("[EVENT BOT] Luồng bot sự kiện đã khởi động, đang kết nối gateway...", flush=True)
    bot.gateway.run(auto_reconnect=True)
    with lock:
        is_event_bot_running = False
    print("[EVENT BOT] Luồng bot sự kiện đã dừng.", flush=True)

# ===================================================================
# LOGIC AUTO CLICK (CHẾ ĐỘ 2)
# ===================================================================
def run_autoclick_bot_thread():
    """Chạy bot chỉ để auto click, tách biệt hoàn toàn."""
    global is_autoclick_running, autoclick_bot_instance, autoclick_clicks_done, autoclick_target_message_data

    bot = discum.Client(token=TOKEN, log=False)
    with lock:
        autoclick_bot_instance = bot

    @bot.gateway.command
    def on_message(resp):
        """Lắng nghe và LƯU TRỮ toàn bộ dữ liệu tin nhắn game mới."""
        global autoclick_target_message_data
        with lock:
            if not is_autoclick_running:
                bot.gateway.close()
                return

        if resp.event.message or resp.event.message_updated:
            m = resp.parsed.auto()
            if (m.get("author", {}).get("id") == KARUTA_ID and
                m.get("channel_id") == CHANNEL_ID and
                "Takumi's Solisfair Stand" in m.get("embeds", [{}])[0].get("title", "")):
                with lock:
                    autoclick_target_message_data = m
                print(f"[AUTO CLICK] INFO: Đã phát hiện/cập nhật tin nhắn game. Mục tiêu mới: {m.get('id')}", flush=True)

    @bot.gateway.command
    def on_ready(resp):
        if resp.event.ready:
            print("[AUTO CLICK] Gateway đã sẵn sàng. Đang chờ bạn gõ 'kevent'...", flush=True)

    threading.Thread(target=bot.gateway.run, daemon=True, name="AutoClickGatewayThread").start()
    print("[AUTO CLICK] Luồng auto click đã khởi động.", flush=True)
    
    while True:
        with lock:
            if not is_autoclick_running: break
            if autoclick_count > 0 and autoclick_clicks_done >= autoclick_count:
                print("[AUTO CLICK] INFO: Đã hoàn thành số lần click được yêu cầu.", flush=True)
                break
            
            target_data = autoclick_target_message_data

        if target_data:
            # Không cần try/except ở đây vì hàm click đã xử lý rồi
            if click_button_by_index(bot, target_data, autoclick_button_index, "AUTO CLICK"):
                with lock:
                    autoclick_clicks_done += 1
            else:
                # Nếu hàm click trả về False sau 40 lần thử, có thể dừng hoặc báo lỗi
                print("[AUTO CLICK] LỖI NGHIÊM TRỌNG: Không thể click sau nhiều lần thử. Dừng auto click.", flush=True)
                break # Thoát khỏi vòng lặp while
        else:
            print("[AUTO CLICK] WARN: Chưa có tin nhắn event nào được phát hiện. Đang chờ...", flush=True)
            time.sleep(5)

    with lock:
        is_autoclick_running = False
        autoclick_bot_instance = None
    print("[AUTO CLICK] Luồng auto click đã dừng.", flush=True)


# ===================================================================
# CÁC LUỒNG PHỤ (VÒNG LẶP, SPAM)
# ===================================================================
def run_hourly_loop_thread():
    """Hàm chứa vòng lặp gửi kevent, chạy trong một luồng riêng."""
    global is_hourly_loop_enabled, loop_delay_seconds
    print("[HOURLY LOOP] Luồng vòng lặp đã khởi động.", flush=True)
    while True:
        with lock:
            if not is_hourly_loop_enabled: break
        
        for _ in range(loop_delay_seconds):
            if not is_hourly_loop_enabled: break
            time.sleep(1)
        
        with lock:
            if is_hourly_loop_enabled and event_bot_instance and is_event_bot_running:
                print(f"\n[HOURLY LOOP] Hết {loop_delay_seconds} giây. Tự động gửi lại lệnh 'kevent'...", flush=True)
                event_bot_instance.sendMessage(CHANNEL_ID, "kevent")
            elif not is_event_bot_running:
                print("[HOURLY LOOP] Bot sự kiện không chạy, không gửi kevent.", flush=True)
                break

    print("[HOURLY LOOP] Luồng vòng lặp đã dừng.", flush=True)

def spam_loop():
    """Vòng lặp vô tận kiểm tra và gửi tin nhắn spam."""
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
                    if time.time() - panel['last_spam_time'] >= panel['delay']:
                        try:
                            bot.sendMessage(str(panel['channel_id']), str(panel['message']))
                            with lock:
                                for p in spam_panels:
                                    if p['id'] == panel['id']: p['last_spam_time'] = time.time(); break
                        except Exception as e:
                            print(f"LỖI SPAM: Không thể gửi tin nhắn tới kênh {panel['channel_id']}. Lỗi: {e}", flush=True)
            time.sleep(1)
        except Exception as e:
            print(f"LỖI NGOẠI LỆ trong vòng lặp spam: {e}", flush=True)
            time.sleep(5)

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
    </style>
</head>
<body>
    <h1>Karuta Bot Control</h1>
    <p>Chọn một chế độ để chạy. Hai chế độ không thể chạy cùng lúc.</p>
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
        // --- SCRIPT CHUNG ---
        async function apiCall(endpoint, method = 'POST', body = null) {
            const options = { method, headers: {'Content-Type': 'application/json'} };
            if (body) options.body = JSON.stringify(body);
            try {
                const response = await fetch(endpoint, options);
                return response.json();
            } catch (error) {
                console.error('API call failed:', error);
                return { error: 'API call failed' };
            }
        }

        // --- DOM ELEMENTS ---
        const eventBotPanel = document.getElementById('event-bot-panel'),
              eventBotStatusDiv = document.getElementById('event-bot-status'), 
              toggleEventBotBtn = document.getElementById('toggleEventBotBtn');

        const autoclickPanel = document.getElementById('autoclick-panel'),
              autoclickStatusDiv = document.getElementById('autoclick-status'), 
              toggleAutoclickBtn = document.getElementById('toggleAutoclickBtn'), 
              buttonIndexInput = document.getElementById('autoclick-button-index'), 
              clickCountInput = document.getElementById('autoclick-count');
        
        const loopStatusDiv = document.getElementById('loop-status'), 
              toggleLoopBtn = document.getElementById('toggleLoopBtn'), 
              delayInput = document.getElementById('delay-input');

        // --- CẬP NHẬT TRẠNG THÁI ---
        async function fetchStatus() {
            const data = await apiCall('/api/status', 'GET');
            if (data.error) {
                eventBotStatusDiv.textContent = 'Lỗi kết nối đến server.';
                return;
            }

            // Chế độ 1: Event Bot
            eventBotStatusDiv.textContent = data.is_event_bot_running ? 'Trạng thái: ĐANG CHẠY' : 'Trạng thái: ĐÃ DỪNG';
            eventBotStatusDiv.className = data.is_event_bot_running ? 'status status-on' : 'status status-off';
            toggleEventBotBtn.textContent = data.is_event_bot_running ? 'Dừng Auto Play' : 'Bật Auto Play';
            toggleEventBotBtn.disabled = data.is_autoclick_running;
            eventBotPanel.classList.toggle('active-mode', data.is_event_bot_running);


            // Chế độ 2: Auto Click
            const countText = data.autoclick_count > 0 ? `${data.autoclick_clicks_done}/${data.autoclick_count}` : `${data.autoclick_clicks_done}/∞`;
            autoclickStatusDiv.textContent = data.is_autoclick_running ? `Trạng thái: ĐANG CHẠY (${countText})` : 'Trạng thái: ĐÃ DỪNG';
            autoclickStatusDiv.className = data.is_autoclick_running ? 'status status-on' : 'status status-off';
            toggleAutoclickBtn.textContent = data.is_autoclick_running ? 'Dừng Auto Click' : 'Bật Auto Click';
            buttonIndexInput.disabled = data.is_autoclick_running;
            clickCountInput.disabled = data.is_autoclick_running;
            toggleAutoclickBtn.disabled = data.is_event_bot_running;
            autoclickPanel.classList.toggle('active-mode', data.is_autoclick_running);

            // Vòng lặp
            loopStatusDiv.textContent = data.is_hourly_loop_enabled ? 'Trạng thái: ĐANG CHẠY' : 'Trạng thái: ĐÃ DỪNG';
            loopStatusDiv.className = data.is_hourly_loop_enabled ? 'status status-on' : 'status status-off';
            toggleLoopBtn.textContent = data.is_hourly_loop_enabled ? 'TẮT VÒNG LẶP' : 'BẬT VÒNG LẶP';
            toggleLoopBtn.disabled = !data.is_event_bot_running && !data.is_hourly_loop_enabled;
        }
        
        // --- EVENT LISTENERS ---
        toggleEventBotBtn.addEventListener('click', () => apiCall('/api/toggle_event_bot').then(fetchStatus));
        toggleAutoclickBtn.addEventListener('click', () => {
            const payload = {
                button_index: parseInt(buttonIndexInput.value, 10),
                count: parseInt(clickCountInput.value, 10)
            };
            apiCall('/api/toggle_autoclick', 'POST', payload).then(fetchStatus);
        });
        toggleLoopBtn.addEventListener('click', () => {
            const currentStatus = loopStatusDiv.textContent.includes('ĐANG CHẠY');
            apiCall('/api/toggle_hourly_loop', 'POST', { enabled: !currentStatus, delay: parseInt(delayInput.value, 10) }).then(fetchStatus);
        });

        // --- SCRIPT CHO SPAMMER ---
        function createPanelElement(panel) {
            const div = document.createElement('div');
            div.className = `spam-panel ${panel.is_active ? 'active' : ''}`;
            div.dataset.id = panel.id;
            let countdown = panel.is_active ? panel.delay - (Date.now() / 1000 - panel.last_spam_time) : panel.delay;
            countdown = Math.max(0, Math.ceil(countdown));
            div.innerHTML = `<textarea class="message-input" placeholder="Nội dung spam...">${panel.message}</textarea><input type="text" class="channel-input" placeholder="ID Kênh..." value="${panel.channel_id}"><input type="number" class="delay-input" placeholder="Delay (giây)..." value="${panel.delay}"><div class="spam-panel-controls"><button class="toggle-btn">${panel.is_active ? 'TẮT' : 'BẬT'}</button><button class="delete-btn">XÓA</button></div><div class="timer">Hẹn giờ: ${countdown}s</div>`;
            const updatePanelData = () => { const updatedPanel = { ...panel, message: div.querySelector('.message-input').value, channel_id: div.querySelector('.channel-input').value, delay: parseInt(div.querySelector('.delay-input').value, 10) || 60 }; apiCall('/api/panel/update', 'POST', updatedPanel); };
            div.querySelector('.toggle-btn').addEventListener('click', () => {
                const updatedPanel = { ...panel, message: div.querySelector('.message-input').value, channel_id: div.querySelector('.channel-input').value, delay: parseInt(div.querySelector('.delay-input').value, 10) || 60, is_active: !panel.is_active };
                apiCall('/api/panel/update', 'POST', updatedPanel).then(fetchPanels);
            });
            div.querySelector('.delete-btn').addEventListener('click', () => { if (confirm('Xóa bảng này?')) apiCall('/api/panel/delete', 'POST', { id: panel.id }).then(fetchPanels); });
            div.querySelector('.message-input').addEventListener('change', updatePanelData);
            div.querySelector('.channel-input').addEventListener('change', updatePanelData);
            div.querySelector('.delay-input').addEventListener('change', updatePanelData);
            return div;
        }
        async function fetchPanels() {
            const focusedElement = document.activeElement;
            if (focusedElement && (focusedElement.tagName === 'INPUT' || focusedElement.tagName === 'TEXTAREA') && focusedElement.closest('.spam-panel')) { return; }
            const data = await apiCall('/api/panels', 'GET');
            const container = document.getElementById('panel-container');
            container.innerHTML = '';
            if (data.panels) data.panels.forEach(panel => container.appendChild(createPanelElement(panel)));
        }
        async function addPanel() { await apiCall('/api/panel/add', 'POST'); fetchPanels(); }

        // --- KHỞI CHẠY ---
        document.addEventListener('DOMContentLoaded', () => {
            fetchStatus();
            fetchPanels();
            setInterval(fetchStatus, 2000);
            setInterval(fetchPanels, 2000);
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
            "autoclick_clicks_done": autoclick_clicks_done
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
    return jsonify({"status": "ok"})

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
    return jsonify({"status": "ok"})

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
    return jsonify({"status": "ok"})

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
    return jsonify({"status": "ok", "new_panel": new_panel})

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
    return jsonify({"status": "ok"})

@app.route("/api/panel/delete", methods=['POST'])
def delete_panel():
    data = request.get_json()
    with lock:
        spam_panels[:] = [p for p in spam_panels if p['id'] != data['id']]
    return jsonify({"status": "ok"})

# ===================================================================
# KHỞI CHẠY WEB SERVER
# ===================================================================
if __name__ == "__main__":
    spam_thread = threading.Thread(target=spam_loop, daemon=True)
    spam_thread.start()
    
    port = int(os.environ.get("PORT", 10000))
    print(f"[SERVER] Khởi động Web Server tại http://0.0.0.0:{port}", flush=True)
    app.run(host="0.0.0.0", port=port, debug=False)
