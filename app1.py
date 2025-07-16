
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from datetime import datetime
import os
import psycopg2
from psycopg2.extras import RealDictCursor



app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'supersecretkey')  # Ganti dengan secret key yang kuat di production

# --- Konfigurasi akun login (hanya di backend, tidak di web) ---
USERS = {
    'admin': 'password123',  # Ganti sesuai kebutuhan
    'user1': 'userpass1',
    'user2': 'passwordku',
    'kominfo': 'kominfo2025',
    'banyumas': 'banyumas123'
}

# --- Konfigurasi koneksi PostgreSQL ---
DB_HOST = os.environ.get('DB_HOST', 'localhost')
DB_NAME = os.environ.get('DB_NAME', 'person_counter')
DB_USER = os.environ.get('DB_USER', 'postgres')
DB_PASS = os.environ.get('DB_PASS', 'Passpostgre1')

def get_db_connection():
    conn = psycopg2.connect(
        host=DB_HOST,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS
    )
    return conn

# Helper untuk insert record ke DB
def insert_record(event_name, person_count, timestamp, snapshot_url):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO records (event_name, person_count, timestamp, snapshot_url)
        VALUES (%s, %s, %s, %s)
        RETURNING id;
        """,
        (event_name, person_count, timestamp, snapshot_url)
    )
    new_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return new_id

# Helper untuk ambil semua record dari DB
def get_all_records():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM records ORDER BY id ASC;")
    records = cur.fetchall()
    cur.close()
    conn.close()
    return records


# --- Proteksi dashboard ---
@app.route('/')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('dashboard.html')

# --- Login page ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        print(f"DEBUG LOGIN: username='{username}', password='{password}'")
        # Cek akun di backend
        if username in USERS:
            print(f"DEBUG: Username ditemukan. Password backend='{USERS[username]}'")
            if USERS[username] == password:
                print("DEBUG: Password cocok. Login berhasil.")
                session['logged_in'] = True
                session['user'] = username
                return redirect(url_for('dashboard'))
            else:
                print("DEBUG: Password tidak cocok.")
                return render_template('login.html', error='Password salah untuk username tersebut.')
        else:
            print("DEBUG: Username tidak ditemukan.")
            return render_template('login.html', error='Username tidak ditemukan.')
    return render_template('login.html')

# --- Logout ---
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/api/records', methods=['GET'])
def get_records():
    try:
        records = get_all_records()
        return jsonify({'status': 'success', 'records': records})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/record', methods=['POST'])
def add_record():
    global person_count
    data = request.get_json()
    event_name = data.get('event_name', '').strip()
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if not event_name:
        return jsonify({'status': 'error', 'message': 'Event name is required'}), 400

    # Ambil screenshot dari kamera
    cam = get_camera()
    if not cam or not cam.isOpened():
        return jsonify({'status': 'error', 'message': 'Camera not active'}), 500
    success, frame = cam.read()
    if not success:
        return jsonify({'status': 'error', 'message': 'Failed to capture image'}), 500

    # Simpan screenshot ke static/image/snapshot_<timestamp>.jpg
    filename = f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    save_path = os.path.join('static', 'image', filename)
    cv2.imwrite(save_path, frame)
    snapshot_url = f"/static/image/{filename}"

    try:
        new_id = insert_record(event_name, person_count, timestamp, snapshot_url)
        record = {
            'id': new_id,
            'event_name': event_name,
            'person_count': person_count,
            'timestamp': timestamp,
            'snapshot_url': snapshot_url
        }
        return jsonify({'status': 'success', 'record': record})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/record/<int:record_id>', methods=['DELETE'])
def delete_record(record_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM records WHERE id = %s;", (record_id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'status': 'success', 'message': 'Record deleted'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/records', methods=['DELETE'])
def delete_all_records():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM records;")
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'status': 'success', 'message': 'All records deleted'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# --- Tambahan untuk video streaming ---

import cv2
from threading import Lock
import time
import numpy as np
from ultralytics import YOLO

camera_lock = Lock()
camera = None
person_count = 0
camera_enabled = False

def get_camera():
    global camera, camera_enabled
    with camera_lock:
        if not camera_enabled:
            if camera:
                camera.release()
                camera = None
            return None
        if camera is None or not camera.isOpened():
            camera = cv2.VideoCapture(0)
        return camera

# Load YOLOv8 model (pastikan path dan model sudah ada)
model = YOLO("yolo-weights/yolo11n.pt")

def gen_frames():
    global person_count
    frame_count = 0
    while True:
        cam = get_camera()
        if not cam or not cam.isOpened():
            # Kamera mati, kirim frame placeholder
            placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(placeholder, "Camera Not Active", (120, 240),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)
            ret, buffer = cv2.imencode('.jpg', placeholder)
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            time.sleep(0.03)
            continue
        success, frame = cam.read()
        if not success:
            continue
        resized_frame = cv2.resize(frame, (640, 480))
        # Deteksi orang setiap 2 frame untuk efisiensi
        if frame_count % 1 == 0:
            try:
                results = model(resized_frame, verbose=False)[0]
                person_boxes = []
                if results.boxes is not None:
                    for box in results.boxes:
                        if int(box.cls[0]) == 0 and float(box.conf[0]) > 0.5:  # hanya box dengan confidence > 0.5
                            person_boxes.append(box)
                person_count = len(person_boxes)
                # Draw bounding boxes
                for box in person_boxes:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    cv2.rectangle(resized_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(resized_frame, 'Person', (x1, y1 - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            except Exception as e:
                print(f"YOLO error: {e}")
        else:
            # Untuk frame non-detect, tetap gambar bounding box dari deteksi terakhir jika ingin
            pass
        frame_count += 1
        ret, buffer = cv2.imencode('.jpg', resized_frame)
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
@app.route('/api/person_count')
def api_person_count():
    global person_count
    return jsonify({'person_count': person_count})

@app.route('/video_feed')
def video_feed():
    return app.response_class(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/start_camera', methods=['POST'])
def start_camera():
    global camera_enabled
    camera_enabled = True
    cam = get_camera()
    if cam and cam.isOpened():
        return jsonify({'status': 'success', 'message': 'Camera started'})
    else:
        return jsonify({'status': 'error', 'message': 'Failed to start camera'})

@app.route('/stop_camera', methods=['POST'])
def stop_camera():
    global camera, camera_enabled
    camera_enabled = False
    with camera_lock:
        if camera:
            camera.release()
            camera = None
    return jsonify({'status': 'success', 'message': 'Camera stopped'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=True)
