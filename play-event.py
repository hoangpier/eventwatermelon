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

# --- Các biến trạng thái để điều khiển qua web ---
bot_thread = None
hourly_loop_thread = None
bot_instance = None
is_bot_running = False
is_hourly_loop_enabled = False
loop_delay_seconds = 3600  # Mặc định 1 giờ
lock = threading.RLock()
spam_panels = []
panel_id_counter = 0
spam_thread = None
# ===================================================================
# LOGIC BOT
# ===================================================================
# Dán toàn bộ hàm này vào code của bạn
def spam_loop():
    """Vòng lặp vô tận kiểm tra và gửi tin nhắn spam cho các bảng đang hoạt động."""
    bot = discum.Client(token=TOKEN, log=False)

    @bot.gateway.command
    def on_ready(resp):
        if resp.event.ready:
            print("[SPAM BOT] Gateway đã kết nối. Luồng spam đã sẵn sàng.", flush=True)

    threading.Thread(target=bot.gateway.run, daemon=True).start()
    time.sleep(5) 

    while True:
        try:
            with lock:
                panels_to_process = list(spam_panels)

            for panel in panels_to_process:
                if panel['is_active'] and panel['channel_id'] and panel['message']:
                    current_time = time.time()
                    if current_time - panel['last_spam_time'] >= panel['delay']:
                        print(f"INFO: Gửi spam tới kênh {panel['channel_id']} (ID Bảng: {panel['id']})", flush=True)
                        try:
                            bot.sendMessage(str(panel['channel_id']), str(panel['message']))
                            with lock:
                                for p in spam_panels:
                                    if p['id'] == panel['id']:
                                        p['last_spam_time'] = current_time
                                        break
                        except Exception as e:
                            print(f"LỖI: Không thể gửi tin nhắn tới kênh {panel['channel_id']}. Lỗi: {e}", flush=True)
                            with lock:
                                for p in spam_panels:
                                    if p['id'] == panel['id']:
                                        p['is_active'] = False
                                        break
            time.sleep(1)
        except Exception as e:
            print(f"LỖI NGOẠI LỆ trong vòng lặp spam: {e}", flush=True)
            time.sleep(5)
            
def run_event_bot_thread():
    """Hàm này chứa toàn bộ logic bot, chạy trong một luồng riêng."""
    global is_bot_running, bot_instance

    active_message_id = None
    action_queue = deque()

    bot = discum.Client(token=TOKEN, log=False)
    with lock:
        bot_instance = bot

    def click_button_by_index(message_data, index):
        try:
            rows = [comp['components'] for comp in message_data.get('components', []) if 'components' in comp]
            all_buttons = [button for row in rows for button in row]
            if index >= len(all_buttons):
                print(f"LỖI: Không tìm thấy button ở vị trí {index}")
                return

            button_to_click = all_buttons[index]
            custom_id = button_to_click.get("custom_id")
            if not custom_id: return

            headers = {"Authorization": TOKEN}
            
            max_retries = 40
            for attempt in range(max_retries):
                session_id = bot.gateway.session_id 
                payload = {
                    "type": 3, "guild_id": message_data.get("guild_id"),
                    "channel_id": message_data.get("channel_id"), "message_id": message_data.get("id"),
                    "application_id": KARUTA_ID, "session_id": session_id,
                    "data": {"component_type": 2, "custom_id": custom_id}
                }
                
                emoji_name = button_to_click.get('emoji', {}).get('name', 'Không có')
                print(f"INFO (Lần {attempt + 1}): Chuẩn bị click button ở vị trí {index} (Emoji: {emoji_name})")
                
                try:
                    r = requests.post("https://discord.com/api/v9/interactions", headers=headers, json=payload, timeout=10)

                    if 200 <= r.status_code < 300:
                        print(f"INFO: Click thành công! (Status: {r.status_code})")
                        # Bạn có thể điều chỉnh thời gian chờ ở đây để tránh rate limit
                        time.sleep(2.5) 
                        return 
                    elif r.status_code == 429:
                        retry_after = r.json().get("retry_after", 1.5)
                        print(f"WARN: Bị rate limit! Sẽ thử lại sau {retry_after:.2f} giây...")
                        time.sleep(retry_after)
                    else:
                        print(f"LỖI: Click thất bại! (Status: {r.status_code}, Response: {r.text})")
                        return
                except requests.exceptions.RequestException as e:
                    print(f"LỖI KẾT NỐI: {e}. Sẽ thử lại sau 3 giây...")
                    time.sleep(3)
            print(f"LỖI: Đã thử click {max_retries} lần mà không thành công.")
        except Exception as e:
            print(f"LỖI NGOẠI LỆ trong hàm click_button_by_index: {e}")

    def perform_final_confirmation(message_data):
        print("ACTION: Chờ 2 giây để nút xác nhận cuối cùng load...")
        time.sleep(2)
        click_button_by_index(message_data, 2)
        print("INFO: Đã hoàn thành lượt. Chờ game tự động cập nhật để bắt đầu lượt mới...")

    @bot.gateway.command
    def on_message(resp):
        nonlocal active_message_id, action_queue
        if not is_bot_running:
            bot.gateway.close()
            return
        
        if not (resp.event.message or resp.event.message_updated): return
        m = resp.parsed.auto()
        if not (m.get("author", {}).get("id") == KARUTA_ID and m.get("channel_id") == CHANNEL_ID): return
        
        with lock:
            # FIX 3: Sửa lỗi logic không nhận game mới từ vòng lặp tự động.
            # Bot sẽ luôn ưu tiên game mới nhất được tạo ra.
            if resp.event.message and "Takumi's Solisfair Stand" in m.get("embeds", [{}])[0].get("title", ""):
                active_message_id = m.get("id")
                action_queue.clear()
                print(f"\nINFO: Đã phát hiện game mới. Chuyển sang tin nhắn ID: {active_message_id}")

            # Chỉ xử lý các sự kiện (như update button) trên tin nhắn game đang hoạt động
            if m.get("id") != active_message_id:
                return

        embed_desc = m.get("embeds", [{}])[0].get("description", "")
        all_buttons_flat = [b for row in m.get('components', []) for b in row.get('components', []) if row.get('type') == 1]
        is_movement_phase = any(b.get('emoji', {}).get('name') == '▶️' for b in all_buttons_flat)
        is_final_confirm_phase = any(b.get('emoji', {}).get('name') == '❌' for b in all_buttons_flat)
        found_good_move = "If placed here, you will receive the following fruit:" in embed_desc
        has_received_fruit = "You received the following fruit:" in embed_desc

        if is_final_confirm_phase:
            with lock:
                action_queue.clear() 
            threading.Thread(target=perform_final_confirmation, args=(m,)).start()
        elif has_received_fruit:
            threading.Thread(target=click_button_by_index, args=(m, 0)).start()
        elif is_movement_phase:
            with lock:
                if found_good_move:
                    print("INFO: NGẮT QUÃNG - Phát hiện nước đi có kết quả. Xóa hàng đợi và xác nhận ngay.", flush=True)
                    action_queue.clear()
                    action_queue.append(0)
                elif not action_queue:
                    print("INFO: Bắt đầu lượt mới. Tạo chuỗi hành động kết hợp...", flush=True)
                    
                    # --- BƯỚC 1: Thêm công thức cố định của bạn ---
                    fixed_sequence = [
                        1, 1,       # 2 lần nút 1 (Lên)
                        2, 2,       # 2 lần nút 2 (Trái)
                        3, 3, 3, 3, # 4 lần nút 3 (Xuống)
                        4, 4, 4, 4, # 4 lần nút 4 (Phải)
                        1, 1, 1, 1, # 4 lần nút 1 (Lên)
                        2, 2,       # 2 lần nút 2 (Trái)
                        3, 3        # 2 lần nút 3 (Xuống)
                    ]
                    action_queue.extend(fixed_sequence)
                    print(f"INFO: -> Đã thêm {len(fixed_sequence)} bước di chuyển theo công thức.", flush=True)

                    num_moves = random.randint(4, 12)
                    movement_indices = [1, 2, 3, 4]
                    random_sequence = [random.choice(movement_indices) for _ in range(num_moves)]
                    action_queue.extend(random_sequence)
                    print(f"INFO: -> Đã thêm {num_moves} bước di chuyển ngẫu nhiên.", flush=True)

                    # --- BƯỚC 3: Thêm hành động xác nhận cuối cùng ---
                    action_queue.append(0)
                    print(f"INFO: Chuỗi hành động mới có tổng cộng {len(action_queue)} bước.", flush=True)

                # Luôn thực hiện hành động tiếp theo trong hàng đợi
                if action_queue:
                    next_action_index = action_queue.popleft()
                    threading.Thread(target=click_button_by_index, args=(m, next_action_index)).start()

    initial_kevent_sent = False
    @bot.gateway.command
    def on_ready(resp):
        nonlocal initial_kevent_sent
        if resp.event.ready_supplemental and not initial_kevent_sent:
            print("[EVENT BOT] Gateway đã sẵn sàng. Gửi lệnh 'kevent' đầu tiên...", flush=True)
            bot.sendMessage(CHANNEL_ID, "kevent")
            initial_kevent_sent = True

    print("[EVENT BOT] Luồng bot đã khởi động, đang kết nối gateway...", flush=True)
    bot.gateway.run(auto_reconnect=True)
    print("[EVENT BOT] Luồng bot đã dừng.", flush=True)

# ===================================================================
# VÒNG LẶP TỰ ĐỘNG
# ===================================================================

def run_hourly_loop_thread():
    """Hàm chứa vòng lặp gửi kevent, chạy trong một luồng riêng."""
    global is_hourly_loop_enabled, loop_delay_seconds
    print("[HOURLY LOOP] Luồng vòng lặp đã khởi động.", flush=True)
    while is_hourly_loop_enabled:
        # Chờ theo từng giây để có thể dừng ngay lập tức
        for _ in range(loop_delay_seconds):
            if not is_hourly_loop_enabled:
                break
            # FIX 1: Thời gian chờ chính xác
            time.sleep(1)
        
        with lock:
            if is_hourly_loop_enabled and bot_instance and is_bot_running:
                print(f"\n[HOURLY LOOP] Hết {loop_delay_seconds} giây. Tự động gửi lại lệnh 'kevent'...", flush=True)
                bot_instance.sendMessage(CHANNEL_ID, "kevent")
            else:
                break
    print("[HOURLY LOOP] Luồng vòng lặp đã dừng.", flush=True)

# ===================================================================
# WEB SERVER (FLASK) ĐỂ ĐIỀU KHIỂN
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
        .container { display: flex; flex-wrap: wrap; justify-content: center; gap: 20px; width: 100%; }
        .panel { text-align: center; background-color: #1e1e1e; padding: 30px; border-radius: 10px; box-shadow: 0 0 20px rgba(0,0,0,0.5); width: 400px; }
        h1, h2 { color: #bb86fc; } .status { font-size: 1.1em; margin: 15px 0; }
        .status-on { color: #03dac6; } .status-off { color: #cf6679; }
        button { background-color: #bb86fc; color: #121212; border: none; padding: 12px 24px; font-size: 1em; border-radius: 5px; cursor: pointer; transition: background-color 0.3s; font-weight: bold; }
        button:hover { background-color: #a050f0; }
        .input-group { display: flex; margin-top: 15px; } .input-group label { padding: 10px; background-color: #333; border-radius: 5px 0 0 5px; }
        .input-group input { flex-grow: 1; border: 1px solid #333; background-color: #222; color: #eee; padding: 10px; border-radius: 0 5px 5px 0; }
        #panel-container { display: grid; grid-template-columns: repeat(auto-fill, minmax(350px, 1fr)); gap: 20px; margin-top: 20px; width: 100%; }
        .spam-panel { background-color: #2a2a2a; padding: 20px; border-radius: 10px; display: flex; flex-direction: column; gap: 15px; border-left: 5px solid #333; }
        .spam-panel.active { border-left-color: #03dac6; }
        .spam-panel input, .spam-panel textarea { width: 100%; box-sizing: border-box; border: 1px solid #444; background-color: #333; color: #eee; padding: 10px; border-radius: 5px; font-size: 1em; }
        .spam-panel textarea { resize: vertical; min-height: 80px; }
        .spam-panel-controls { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
        .spam-panel-controls button { flex-grow: 1; }
        .delete-btn { background-color: #cf6679 !important; }
        .add-panel-btn { width: 100%; max-width: 840px; padding: 20px; font-size: 1.5em; margin-top: 20px; background-color: rgba(3, 218, 198, 0.2); border: 2px dashed #03dac6; color: #03dac6; cursor: pointer; border-radius: 10px;}
        .timer { font-size: 0.9em; color: #888; text-align: right; }
    </style>
</head>
<body>
    <div class="container">
        <div class="panel">
            <h1>Bot Event Solis-Fair</h1>
            <div id="bot-status" class="status">Trạng thái: Đang tải...</div>
            <button id="toggleBotBtn">Bắt đầu</button>
        </div>
        <div class="panel">
            <h2>Vòng lặp tự động Event</h2>
            <div id="loop-status" class="status">Trạng thái: Đang tải...</div>
            <div class="input-group">
                <label for="delay-input">Delay (giây)</label>
                <input type="number" id="delay-input" value="3600">
            </div>
            <button id="toggleLoopBtn" style="margin-top: 15px;">Bắt đầu</button>
        </div>
    </div>
    <div class="panel" style="width: auto; max-width: 800px;">
        <h2>Bảng Điều Khiển Spam</h2>
        <div id="panel-container"></div>
        <button class="add-panel-btn" onclick="addPanel()">+</button>
    </div>
    <script>
        // --- SCRIPT CHUNG ---
        async function apiCall(endpoint, method = 'GET', body = null) {
            const options = { method, headers: {'Content-Type': 'application/json'} };
            if (body) options.body = JSON.stringify(body);
            const response = await fetch(endpoint, options);
            return response.json();
        }

        // --- SCRIPT CHO EVENT BOT ---
        const botStatusDiv = document.getElementById('bot-status'), toggleBotBtn = document.getElementById('toggleBotBtn');
        const loopStatusDiv = document.getElementById('loop-status'), toggleLoopBtn = document.getElementById('toggleLoopBtn'), delayInput = document.getElementById('delay-input');
        async function fetchStatus() {
            try {
                const r = await fetch('/api/status'), data = await r.json();
                botStatusDiv.textContent = data.is_bot_running ? 'Trạng thái: ĐANG CHẠY' : 'Trạng thái: ĐÃ DỪNG';
                botStatusDiv.className = data.is_bot_running ? 'status status-on' : 'status status-off';
                toggleBotBtn.textContent = data.is_bot_running ? 'DỪNG BOT' : 'BẬT BOT';
                loopStatusDiv.textContent = data.is_hourly_loop_enabled ? 'Trạng thái: ĐANG CHẠY' : 'Trạng thái: ĐÃ DỪNG';
                loopStatusDiv.className = data.is_hourly_loop_enabled ? 'status status-on' : 'status status-off';
                toggleLoopBtn.textContent = data.is_hourly_loop_enabled ? 'TẮT VÒNG LẶP' : 'BẬT VÒNG LẶP';
                if (document.activeElement !== delayInput) { delayInput.value = data.loop_delay_seconds; }
            } catch (e) { botStatusDiv.textContent = 'Lỗi kết nối đến server.'; botStatusDiv.className = 'status status-off'; }
        }
        toggleBotBtn.addEventListener('click', () => apiCall('/api/toggle_bot', 'POST').then(fetchStatus));
        toggleLoopBtn.addEventListener('click', () => {
            const currentStatus = loopStatusDiv.textContent.includes('ĐANG CHẠY');
            apiCall('/api/toggle_hourly_loop', 'POST', { enabled: !currentStatus, delay: parseInt(delayInput.value, 10) }).then(fetchStatus);
        });
        setInterval(fetchStatus, 5000);
        
        // --- SCRIPT CHO SPAMMER ---
        function createPanelElement(panel) {
            const div = document.createElement('div');
            div.className = `spam-panel ${panel.is_active ? 'active' : ''}`;
            div.dataset.id = panel.id;
            let countdown = panel.is_active ? panel.delay - (Date.now() / 1000 - panel.last_spam_time) : panel.delay;
            countdown = Math.max(0, Math.ceil(countdown));
            div.innerHTML = `<textarea class="message-input" placeholder="Nội dung spam...">${panel.message}</textarea><input type="text" class="channel-input" placeholder="ID Kênh..." value="${panel.channel_id}"><input type="number" class="delay-input" placeholder="Delay (giây)..." value="${panel.delay}"><div class="panel-controls"><button class="toggle-btn">${panel.is_active ? 'TẮT' : 'BẬT'}</button><button class="delete-btn">XÓA</button></div><div class="timer">Hẹn giờ: ${countdown}s</div>`;
            const updatePanelData = () => { const updatedPanel = { ...panel, message: div.querySelector('.message-input').value, channel_id: div.querySelector('.channel-input').value, delay: parseInt(div.querySelector('.delay-input').value, 10) || 60 }; apiCall('/api/panel/update', 'POST', updatedPanel); };
            div.querySelector('.toggle-btn').addEventListener('click', () => {
                // Đọc giá trị mới nhất từ các ô input trước khi gửi
                const updatedPanel = { 
                    ...panel, 
                    message: div.querySelector('.message-input').value,
                    channel_id: div.querySelector('.channel-input').value,
                    delay: parseInt(div.querySelector('.delay-input').value, 10) || 60,
                    is_active: !panel.is_active // Đảo ngược trạng thái bật/tắt
                };
                apiCall('/api/panel/update', 'POST', updatedPanel).then(fetchPanels);
            });
            div.querySelector('.delete-btn').addEventListener('click', () => { if (confirm('Xóa bảng này?')) apiCall('/api/panel/delete', 'POST', { id: panel.id }).then(fetchPanels); });
            div.querySelector('.message-input').addEventListener('change', updatePanelData);
            div.querySelector('.channel-input').addEventListener('change', updatePanelData);
            div.querySelector('.delay-input').addEventListener('change', updatePanelData);
            return div;
        }
        async function fetchPanels() {
            // KIỂM TRA XEM NGƯỜI DÙNG CÓ ĐANG GÕ CHỮ KHÔNG
            const focusedElement = document.activeElement;
            if (focusedElement && (focusedElement.tagName === 'INPUT' || focusedElement.tagName === 'TEXTAREA')) {
                const panel = focusedElement.closest('.spam-panel');
                if (panel) {
                    // Nếu đang focus vào một ô nhập liệu trong panel spam, thì không làm gì cả
                    return; 
                }
            }
        
            // Nếu không, tiếp tục cập nhật như bình thường
            const data = await apiCall('/api/panels');
            const container = document.getElementById('panel-container');
            container.innerHTML = '';
            data.panels.forEach(panel => container.appendChild(createPanelElement(panel)));
        }
        async function addPanel() { await apiCall('/api/panel/add', 'POST'); fetchPanels(); }
        setInterval(fetchPanels, 2000);

        // Chạy lần đầu khi load trang
        document.addEventListener('DOMContentLoaded', () => {
            fetchStatus();
            fetchPanels();
        });
    </script>
</body>
</html>
"""
@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route("/api/status")
def status():
    return jsonify({
        "is_bot_running": is_bot_running,
        "is_hourly_loop_enabled": is_hourly_loop_enabled,
        "loop_delay_seconds": loop_delay_seconds
    })

@app.route("/api/toggle_bot", methods=['POST'])
def toggle_bot():
    global bot_thread, is_bot_running
    with lock:
        if is_bot_running:
            is_bot_running = False
            print("[CONTROL] Nhận được lệnh DỪNG bot.", flush=True)
        else:
            is_bot_running = True
            print("[CONTROL] Nhận được lệnh BẬT bot.", flush=True)
            bot_thread = threading.Thread(target=run_event_bot_thread, daemon=True)
            bot_thread.start()
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
@app.route("/api/panels")
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
        for i, panel in enumerate(spam_panels):
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
