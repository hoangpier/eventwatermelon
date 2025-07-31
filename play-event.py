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
lock = threading.Lock()

# ===================================================================
# LOGIC BOT
# ===================================================================

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
    <title>Solis-Fair Bot Control</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #121212; color: #e0e0e0; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; flex-direction: column; gap: 20px;}
        .panel { text-align: center; background-color: #1e1e1e; padding: 30px; border-radius: 10px; box-shadow: 0 0 20px rgba(0,0,0,0.5); width: 400px; }
        h1, h2 { color: #bb86fc; } .status { font-size: 1.1em; margin: 15px 0; }
        .status-on { color: #03dac6; } .status-off { color: #cf6679; }
        button { background-color: #bb86fc; color: #121212; border: none; padding: 12px 24px; font-size: 1em; border-radius: 5px; cursor: pointer; transition: background-color 0.3s; font-weight: bold; }
        button:hover { background-color: #a050f0; } button.off-button { background-color: #444; color: #ccc; } button.off-button:hover { background-color: #555; }
        .input-group { display: flex; margin-top: 15px; } .input-group label { padding: 10px; background-color: #333; border-radius: 5px 0 0 5px; }
        .input-group input { flex-grow: 1; border: 1px solid #333; background-color: #222; color: #eee; padding: 10px; border-radius: 0 5px 5px 0; }
    </style>
</head>
<body>
    <div class="panel">
        <h1>Bot Event Solis-Fair</h1>
        <div id="bot-status" class="status">Trạng thái: Đang tải...</div>
        <button id="toggleBotBtn">Bắt đầu</button>
    </div>
    <div class="panel">
        <h2>Vòng lặp tự động</h2>
        <div id="loop-status" class="status">Trạng thái: Đang tải...</div>
        <div class="input-group">
            <label for="delay-input">Delay (giây)</label>
            <input type="number" id="delay-input" value="3600">
        </div>
        <button id="toggleLoopBtn" style="margin-top: 15px;">Bắt đầu</button>
    </div>
    <script>
        const botStatusDiv = document.getElementById('bot-status'), toggleBotBtn = document.getElementById('toggleBotBtn');
        const loopStatusDiv = document.getElementById('loop-status'), toggleLoopBtn = document.getElementById('toggleLoopBtn'), delayInput = document.getElementById('delay-input');
        async function postData(url, data) { await fetch(url, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data) }); fetchStatus(); }
        async function fetchStatus() {
            try {
                const r = await fetch('/api/status'), data = await r.json();
                botStatusDiv.textContent = data.is_bot_running ? 'Trạng thái: ĐANG CHẠY' : 'Trạng thái: ĐÃ DỪNG';
                botStatusDiv.className = data.is_bot_running ? 'status status-on' : 'status status-off';
                toggleBotBtn.textContent = data.is_bot_running ? 'DỪNG BOT' : 'BẬT BOT';
                loopStatusDiv.textContent = data.is_hourly_loop_enabled ? 'Trạng thái: ĐANG CHẠY' : 'Trạng thái: ĐÃ DỪNG';
                loopStatusDiv.className = data.is_hourly_loop_enabled ? 'status status-on' : 'status status-off';
                toggleLoopBtn.textContent = data.is_hourly_loop_enabled ? 'TẮT VÒNG LẶP' : 'BẬT VÒNG LẶP';
                
                // FIX 2: Sửa lỗi giật số trên giao diện web.
                if (document.activeElement !== delayInput) {
                    delayInput.value = data.loop_delay_seconds;
                }
            } catch (e) { botStatusDiv.textContent = 'Lỗi kết nối đến server.'; botStatusDiv.className = 'status status-off'; }
        }
        toggleBotBtn.addEventListener('click', () => postData('/api/toggle_bot', {}));
        toggleLoopBtn.addEventListener('click', () => {
            const currentStatus = loopStatusDiv.textContent.includes('ĐANG CHẠY');
            postData('/api/toggle_hourly_loop', { enabled: !currentStatus, delay: parseInt(delayInput.value, 10) });
        });
        setInterval(fetchStatus, 5000); fetchStatus();
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

# ===================================================================
# KHỞI CHẠY WEB SERVER
# ===================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"[SERVER] Khởi động Web Server tại http://0.0.0.0:{port}", flush=True)
    app.run(host="0.0.0.0", port=port, debug=False)
