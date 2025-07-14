from flask import Flask, render_template, request, jsonify
from datetime import datetime
import os

app = Flask(__name__)

# Dummy data for demonstration (replace with database or real data in production)
RECORDS = [
    {
        'id': 1,
        'event_name': 'Rondo Joget',
        'person_count': 5,
        'timestamp': '2025-07-14 03:24:56',
        'snapshot_url': '/static/image/snapshot1.jpg'
    },
    {
        'id': 2,
        'event_name': 'Supersemar',
        'person_count': 7,
        'timestamp': '2025-07-14 07:45:07',
        'snapshot_url': '/static/image/snapshot2.jpg'
    }
]

@app.route('/')
def dashboard():
    return render_template('dashboard.html')

@app.route('/api/records', methods=['GET'])
def get_records():
    return jsonify({'status': 'success', 'records': RECORDS})

@app.route('/api/record', methods=['POST'])
def add_record():
    data = request.get_json()
    event_name = data.get('event_name', '').strip()
    person_count = data.get('person_count', 0)
    snapshot_url = data.get('snapshot_url', '')
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if not event_name:
        return jsonify({'status': 'error', 'message': 'Event name is required'}), 400
    new_id = max([r['id'] for r in RECORDS], default=0) + 1
    record = {
        'id': new_id,
        'event_name': event_name,
        'person_count': person_count,
        'timestamp': timestamp,
        'snapshot_url': snapshot_url
    }
    RECORDS.append(record)
    return jsonify({'status': 'success', 'record': record})

@app.route('/api/record/<int:record_id>', methods=['DELETE'])
def delete_record(record_id):
    global RECORDS
    RECORDS = [r for r in RECORDS if r['id'] != record_id]
    return jsonify({'status': 'success', 'message': 'Record deleted'})

@app.route('/api/records', methods=['DELETE'])
def delete_all_records():
    global RECORDS
    RECORDS = []
    return jsonify({'status': 'success', 'message': 'All records deleted'})


# --- Tambahan untuk video streaming ---
import cv2
from threading import Lock
import time

camera_lock = Lock()
camera = None

def get_camera():
    global camera
    with camera_lock:
        if camera is None or not camera.isOpened():
            camera = cv2.VideoCapture(0)
        return camera

def gen_frames():
    while True:
        cam = get_camera()
        if not cam or not cam.isOpened():
            time.sleep(1)
            continue
        success, frame = cam.read()
        if not success:
            continue
        ret, buffer = cv2.imencode('.jpg', frame)
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app.route('/video_feed')
def video_feed():
    return app.response_class(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/start_camera', methods=['POST'])
def start_camera():
    cam = get_camera()
    if cam and cam.isOpened():
        return jsonify({'status': 'success', 'message': 'Camera started'})
    else:
        return jsonify({'status': 'error', 'message': 'Failed to start camera'})

@app.route('/stop_camera', methods=['POST'])
def stop_camera():
    global camera
    with camera_lock:
        if camera:
            camera.release()
            camera = None
    return jsonify({'status': 'success', 'message': 'Camera stopped'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=True)
