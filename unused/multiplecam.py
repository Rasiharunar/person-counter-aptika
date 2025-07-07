from flask import Flask, render_template, Response, jsonify, request
from datetime import datetime
import requests
import cv2
from ultralytics import YOLO
import numpy as np
import threading
import time

app = Flask(__name__)

# Load YOLOv8 model
model = YOLO("yolov8n.pt")  # pastikan file ini ada di folder project

# Laravel API endpoint (device_code disisipkan di URL)
LARAVEL_API_URL = "http://withink.pro/api/recordings/smartroomlabvhx"

# Global variables for multiple cameras
cameras = {
    'cam1': {
        'cap': None,
        'active': False,
        'person_count': 0,
        'frame': None,
        'lock': threading.Lock()
    },
    'cam2': {
        'cap': None,
        'active': False,
        'person_count': 0,
        'frame': None,
        'lock': threading.Lock()
    }
}

total_person_count = 0

@app.route('/')
def index():
    return render_template('multicam.html')

@app.route('/start_camera/<camera_id>', methods=['POST'])
def start_camera(camera_id):
    if camera_id not in cameras:
        return jsonify({'status': 'error', 'message': 'Invalid camera ID'})
    
    camera = cameras[camera_id]
    
    # Determine camera index (0 for cam1, 1 for cam2)
    cam_index = 0 if camera_id == 'cam1' else 1
    
    try:
        camera['cap'] = cv2.VideoCapture(cam_index)
        if not camera['cap'].isOpened():
            return jsonify({'status': 'error', 'message': f'Could not open camera {cam_index}'})
        
        camera['active'] = True
        
        # Start processing thread for this camera
        thread = threading.Thread(target=process_camera, args=(camera_id,))
        thread.daemon = True
        thread.start()
        
        return jsonify({'status': 'success', 'message': f'Camera {camera_id} started'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/stop_camera/<camera_id>', methods=['POST'])
def stop_camera(camera_id):
    if camera_id not in cameras:
        return jsonify({'status': 'error', 'message': 'Invalid camera ID'})
    
    camera = cameras[camera_id]
    camera['active'] = False
    
    if camera['cap']:
        camera['cap'].release()
        camera['cap'] = None
    
    camera['person_count'] = 0
    update_total_count()
    
    return jsonify({'status': 'success', 'message': f'Camera {camera_id} stopped'})

@app.route('/start_all_cameras', methods=['POST'])
def start_all_cameras():
    results = {}
    for camera_id in cameras.keys():
        try:
            response = start_camera(camera_id)
            results[camera_id] = response.get_json()
        except Exception as e:
            results[camera_id] = {'status': 'error', 'message': str(e)}
    
    return jsonify({'status': 'success', 'results': results})

@app.route('/stop_all_cameras', methods=['POST'])
def stop_all_cameras():
    results = {}
    for camera_id in cameras.keys():
        try:
            response = stop_camera(camera_id)
            results[camera_id] = response.get_json()
        except Exception as e:
            results[camera_id] = {'status': 'error', 'message': str(e)}
    
    return jsonify({'status': 'success', 'results': results})

def process_camera(camera_id):
    camera = cameras[camera_id]
    
    while camera['active'] and camera['cap'] and camera['cap'].isOpened():
        success, frame = camera['cap'].read()
        if not success:
            break

        resized_frame = cv2.resize(frame, (640, 480))
        results = model(resized_frame, verbose=False)[0]

        person_boxes = []
        for box in results.boxes:
            if int(box.cls[0]) == 0:  # person class
                person_boxes.append(box)

        # Draw bounding boxes
        for box in person_boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            cv2.rectangle(resized_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(resized_frame, 'Person', (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        # Add camera info and count to frame
        cv2.putText(resized_frame, f'{camera_id.upper()}: {len(person_boxes)} persons', 
                   (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        # Update count and frame
        with camera['lock']:
            camera['person_count'] = len(person_boxes)
            ret, buffer = cv2.imencode('.jpg', resized_frame)
            camera['frame'] = buffer.tobytes()
        
        # Update total count
        update_total_count()
        
        time.sleep(0.03)  # ~30 FPS

def update_total_count():
    global total_person_count
    total_person_count = sum(camera['person_count'] for camera in cameras.values())

def generate_frames(camera_id):
    camera = cameras[camera_id]
    
    while camera['active']:
        with camera['lock']:
            if camera['frame'] is not None:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + camera['frame'] + b'\r\n')
        time.sleep(0.03)

@app.route('/video_feed/<camera_id>')
def video_feed(camera_id):
    if camera_id not in cameras:
        return "Invalid camera ID", 404
    
    return Response(generate_frames(camera_id),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/get_count')
def get_count():
    counts = {
        'cam1': cameras['cam1']['person_count'],
        'cam2': cameras['cam2']['person_count'],
        'total': total_person_count
    }
    return jsonify(counts)

@app.route('/get_count/<camera_id>')
def get_camera_count(camera_id):
    if camera_id not in cameras:
        return jsonify({'error': 'Invalid camera ID'}), 404
    
    return jsonify({
        'camera': camera_id,
        'count': cameras[camera_id]['person_count']
    })

@app.route('/record_data', methods=['GET'])
def record_data():
    event_name = request.args.get('event_name', '').strip()
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if not event_name:
        return jsonify({'status': 'error', 'message': 'Event name is required'})

    try:
        # Kirim data ke Laravel API via GET dengan total count
        payload = {
            'event_name': event_name,
            'person_count': total_person_count,
            'cam1_count': cameras['cam1']['person_count'],
            'cam2_count': cameras['cam2']['person_count']
        }

        response = requests.get(LARAVEL_API_URL, params=payload)

        if response.status_code in [200, 201]:
            return jsonify({
                'status': 'success',
                'message': 'Data sent successfully',
                'data': {
                    'event_name': event_name,
                    'total_person_count': total_person_count,
                    'cam1_count': cameras['cam1']['person_count'],
                    'cam2_count': cameras['cam2']['person_count'],
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

@app.route('/camera_status')
def camera_status():
    status = {}
    for camera_id, camera in cameras.items():
        status[camera_id] = {
            'active': camera['active'],
            'person_count': camera['person_count']
        }
    status['total_count'] = total_person_count
    return jsonify(status)

if __name__ == '__main__':
    app.run(debug=True, threaded=True)