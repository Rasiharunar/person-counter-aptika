from flask import Flask, render_template, Response, jsonify, request
from datetime import datetime
import requests
import cv2
from ultralytics import YOLO
import numpy as np
import base64
import threading
import time

app = Flask(__name__)

# Load YOLOv8 model
model = YOLO("yolov8n.pt")  # pastikan file ini ada di folder project

# Laravel API endpoint (device_code disisipkan di URL)
LARAVEL_API_URL = "http://withink.pro/api/recordings/smartroom"
LARAVEL_VIDEO_URL = "http://withink.pro/api/video-feed/smartroom"  # Endpoint untuk video feed

# Global variables
person_count = 0
camera_active = False
cap = None
send_video_to_laravel = False  # Flag untuk mengontrol pengiriman video

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start_camera', methods=['POST'])
def start_camera():
    global camera_active, cap
    camera_active = True
    cap = cv2.VideoCapture(0)
    return jsonify({'status': 'success', 'message': 'Camera started'})

@app.route('/stop_camera', methods=['POST'])
def stop_camera():
    global camera_active, cap, send_video_to_laravel
    camera_active = False
    send_video_to_laravel = False
    if cap:
        cap.release()
        cap = None
    return jsonify({'status': 'success', 'message': 'Camera stopped'})

@app.route('/start_video_stream', methods=['POST'])
def start_video_stream():
    global send_video_to_laravel
    send_video_to_laravel = True
    # Mulai thread untuk mengirim video secara terpisah
    thread = threading.Thread(target=send_video_stream_to_laravel)
    thread.daemon = True
    thread.start()
    return jsonify({'status': 'success', 'message': 'Video streaming to Laravel started'})

@app.route('/stop_video_stream', methods=['POST'])
def stop_video_stream():
    global send_video_to_laravel
    send_video_to_laravel = False
    return jsonify({'status': 'success', 'message': 'Video streaming to Laravel stopped'})

def send_video_stream_to_laravel():
    """Fungsi untuk mengirim video stream ke Laravel secara real-time"""
    global cap, send_video_to_laravel, person_count
    
    while send_video_to_laravel and cap and cap.isOpened():
        success, frame = cap.read()
        if not success:
            break

        # Resize frame untuk mengurangi ukuran data
        resized_frame = cv2.resize(frame, (640, 480))
        
        # Deteksi objek
        results = model(resized_frame, verbose=False)[0]
        person_boxes = []
        for box in results.boxes:
            if int(box.cls[0]) == 0:
                person_boxes.append(box)

        person_count = len(person_boxes)

        # Gambar bounding box
        for box in person_boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            cv2.rectangle(resized_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(resized_frame, 'Person', (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        # Encode frame ke base64
        _, buffer = cv2.imencode('.jpg', resized_frame)
        frame_base64 = base64.b64encode(buffer).decode('utf-8')

        try:
            # Kirim frame ke Laravel
            payload = {
                'frame': frame_base64,
                'person_count': person_count,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            response = requests.post(LARAVEL_VIDEO_URL, json=payload, timeout=5)
            
            if response.status_code not in [200, 201]:
                print(f"Error sending frame to Laravel: {response.status_code}")
                
        except Exception as e:
            print(f"Error sending frame: {str(e)}")

        # Delay untuk mengontrol frame rate (30 FPS = 1/30 detik)
        time.sleep(1/30)

def generate_frames():
    global cap, person_count, camera_active

    while camera_active and cap and cap.isOpened():
        success, frame = cap.read()
        if not success:
            break

        resized_frame = cv2.resize(frame, (640, 480))
        results = model(resized_frame, verbose=False)[0]

        person_boxes = []
        for box in results.boxes:
            if int(box.cls[0]) == 0:
                person_boxes.append(box)

        person_count = len(person_boxes)

        for box in person_boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            cv2.rectangle(resized_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(resized_frame, 'Person', (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        ret, buffer = cv2.imencode('.jpg', resized_frame)
        frame = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/get_count')
def get_count():
    return jsonify({'count': person_count})

@app.route('/send_frame', methods=['POST'])
def send_frame():
    """Endpoint untuk mengirim frame tunggal ke Laravel"""
    global cap, person_count
    
    if not cap or not cap.isOpened():
        return jsonify({'status': 'error', 'message': 'Camera not active'})
    
    success, frame = cap.read()
    if not success:
        return jsonify({'status': 'error', 'message': 'Failed to capture frame'})
    
    # Resize dan encode frame
    resized_frame = cv2.resize(frame, (640, 480))
    _, buffer = cv2.imencode('.jpg', resized_frame)
    frame_base64 = base64.b64encode(buffer).decode('utf-8')
    
    try:
        payload = {
            'frame': frame_base64,
            'person_count': person_count,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        response = requests.post(LARAVEL_VIDEO_URL, json=payload, timeout=10)
        
        if response.status_code in [200, 201]:
            return jsonify({
                'status': 'success',
                'message': 'Frame sent successfully',
                'laravel_response': response.json() if response.content else {}
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'Failed to send frame to Laravel',
                'code': response.status_code,
                'laravel_response': response.text
            })
            
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/record_data', methods=['GET'])
def record_data():
    event_name = request.args.get('event_name', '').strip()
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if not event_name:
        return jsonify({'status': 'error', 'message': 'Event name is required'})

    try:
        # Kirim data ke Laravel API via GET
        payload = {
            'event_name': event_name,
            'person_count': person_count
        }

        response = requests.get(LARAVEL_API_URL, params=payload)

        if response.status_code in [200, 201]:
            return jsonify({
                'status': 'success',
                'message': 'Data sent successfully',
                'data': {
                    'event_name': event_name,
                    'person_count': person_count,
                    'timestamp': timestamp
                }
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'Failed to send to Laravel',
                'code': response.status_code,
                'laravel_response': response.text
            })

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/test_api', methods=['GET'])
def test_api():
    try:
        response = requests.get(LARAVEL_API_URL)
        return jsonify({
            'status': 'success' if response.status_code == 200 else 'error',
            'response_code': response.status_code
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/get_stream_status')
def get_stream_status():
    return jsonify({
        'camera_active': camera_active,
        'video_streaming': send_video_to_laravel,
        'person_count': person_count
    })

if __name__ == '__main__':
    app.run(debug=True)