from flask import Flask, render_template, Response, jsonify, request
from datetime import datetime
import requests
import cv2
from ultralytics import YOLO
import numpy as np
import base64
import threading
import time
import os
from threading import Lock, Event
import signal
import sys

app = Flask(__name__)

# Load YOLOv8 model
model = YOLO("yolo-weights/yolo11n.pt")  # pastikan file ini ada di folder project

# Laravel API endpoint (device_code disisipkan di URL)
LARAVEL_API_URL = "http://127.0.0.1:8000/api/recordings/smartroomfhx"
LARAVEL_VIDEO_URL = "http://127.0.0.1:8000/api/video-feed/smartroomfhx"  # Endpoint untuk video feed

# Global variables
person_count = 0
camera_active = False
cap = None
send_video_to_laravel = False
frame_lock = Lock()  # Lock untuk thread safety
video_thread = None
stop_event = Event()  # Event untuk menghentikan thread dengan bersih
last_frame = None  # Store last frame globally
camera_session_id = 0  # Add session tracking

@app.route('/')
def index():
    return render_template('index.html')

def release_camera():
    """Fungsi untuk melepas kamera dengan aman"""
    global cap
    if cap is not None:
        try:
            cap.release()
            time.sleep(0.1)  # Beri waktu untuk sistem melepas resource
        except:
            pass
        finally:
            cap = None
    
    # Cleanup OpenCV windows
    try:
        cv2.destroyAllWindows()
    except:
        pass

def initialize_camera():
    """Fungsi untuk inisialisasi kamera dengan retry mechanism"""
    global cap
    
    # Pastikan kamera sebelumnya sudah dilepas
    release_camera()
    
    # Tunggu sebentar untuk memastikan resource benar-benar dilepas
    time.sleep(0.5)
    
    # Coba inisialisasi kamera dengan berbagai cara
    for attempt in range(5):  # Coba 5 kali
        try:
            print(f"Attempting to initialize camera - attempt {attempt + 1}")
            
            # Coba berbagai indeks kamera
            for camera_index in [0, 1, 2]:
                try:
                    # Coba berbagai backend
                    backends = [cv2.CAP_ANY, cv2.CAP_DSHOW, cv2.CAP_V4L2]
                    
                    for backend in backends:
                        cap = cv2.VideoCapture(camera_index, backend)
                        
                        if cap.isOpened():
                            # Test apakah kamera benar-benar bisa capture
                            ret, frame = cap.read()
                            if ret and frame is not None:
                                # Set properti kamera
                                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                                cap.set(cv2.CAP_PROP_FPS, 30)
                                
                                print(f"Camera initialized successfully on index {camera_index} with backend {backend}")
                                return True
                        
                        # Jika tidak berhasil, release dan coba yang lain
                        if cap:
                            cap.release()
                            cap = None
                            
                except Exception as e:
                    print(f"Error trying camera {camera_index}: {e}")
                    if cap:
                        cap.release()
                        cap = None
                    continue
            
            # Jika semua gagal, tunggu dan coba lagi
            print(f"All camera attempts failed, waiting before retry...")
            time.sleep(1)
            
        except Exception as e:
            print(f"Error in camera initialization attempt {attempt + 1}: {e}")
            time.sleep(1)
    
    print("Failed to initialize camera after all attempts")
    return False

@app.route('/start_camera', methods=['POST'])
def start_camera():
    global camera_active, cap, send_video_to_laravel, video_thread, stop_event, camera_session_id
    
    try:
        with frame_lock:
            # Stop video streaming jika sedang berjalan
            if send_video_to_laravel:
                send_video_to_laravel = False
                stop_event.set()
                
            # Tunggu thread video selesai
            if video_thread and video_thread.is_alive():
                video_thread.join(timeout=3)
            
            # Reset event dan increment session ID
            stop_event.clear()
            camera_session_id += 1
            
            # Inisialisasi kamera
            if initialize_camera():
                camera_active = True
                return jsonify({
                    'status': 'success', 
                    'message': 'Camera started successfully',
                    'session_id': camera_session_id
                })
            else:
                camera_active = False
                return jsonify({'status': 'error', 'message': 'Failed to initialize camera'})
                
    except Exception as e:
        camera_active = False
        return jsonify({'status': 'error', 'message': f'Error starting camera: {str(e)}'})

@app.route('/stop_camera', methods=['POST'])
def stop_camera():
    global camera_active, cap, send_video_to_laravel, video_thread, stop_event, last_frame
    
    try:
        with frame_lock:
            # Set flags untuk menghentikan semua aktivitas
            camera_active = False
            send_video_to_laravel = False
            stop_event.set()
            
            # Tunggu thread video selesai
            if video_thread and video_thread.is_alive():
                print("Waiting for video thread to finish...")
                video_thread.join(timeout=3)
                if video_thread.is_alive():
                    print("Video thread did not finish cleanly")
            
            # Release kamera
            release_camera()
            
            # Reset thread reference and clear last frame
            video_thread = None
            last_frame = None
            
            print("Camera stopped successfully")
            
        return jsonify({'status': 'success', 'message': 'Camera stopped successfully'})
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Error stopping camera: {str(e)}'})

@app.route('/start_video_stream', methods=['POST'])
def start_video_stream():
    global send_video_to_laravel, video_thread, stop_event
    
    try:
        if not camera_active or not cap or not cap.isOpened():
            return jsonify({'status': 'error', 'message': 'Camera not active'})
        
        with frame_lock:
            # Stop existing video thread if running
            if send_video_to_laravel:
                send_video_to_laravel = False
                stop_event.set()
                
            if video_thread and video_thread.is_alive():
                video_thread.join(timeout=3)
            
            # Reset event dan start new thread
            stop_event.clear()
            send_video_to_laravel = True
            video_thread = threading.Thread(target=send_video_stream_to_laravel)
            video_thread.daemon = True
            video_thread.start()
            
        return jsonify({'status': 'success', 'message': 'Video streaming to Laravel started'})
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Error starting video stream: {str(e)}'})

@app.route('/stop_video_stream', methods=['POST'])
def stop_video_stream():
    global send_video_to_laravel, video_thread, stop_event
    
    try:
        with frame_lock:
            send_video_to_laravel = False
            stop_event.set()
            
            if video_thread and video_thread.is_alive():
                video_thread.join(timeout=3)
            
            video_thread = None
            
        return jsonify({'status': 'success', 'message': 'Video streaming to Laravel stopped'})
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Error stopping video stream: {str(e)}'})

def send_video_stream_to_laravel():
    """Fungsi untuk mengirim video stream ke Laravel secara real-time"""
    global cap, send_video_to_laravel, person_count, stop_event
    
    print("Video streaming thread started")
    frame_count = 0
    
    while send_video_to_laravel and not stop_event.is_set():
        try:
            # Check if we should stop
            if stop_event.wait(timeout=0.001):  # Non-blocking check
                break
            
            # Try to acquire lock with timeout to prevent blocking
            if frame_lock.acquire(timeout=0.1):
                try:
                    if not cap or not cap.isOpened():
                        frame_lock.release()
                        break
                    success, frame = cap.read()
                finally:
                    frame_lock.release()
            else:
                # If can't acquire lock, skip this frame
                time.sleep(0.067)  # ~15 FPS
                continue
                
            if not success or frame is None:
                print("Failed to read frame from camera")
                time.sleep(0.1)
                continue

            # Process only every 2nd frame for performance
            if frame_count % 2 == 0:
                # Resize frame untuk mengurangi ukuran data
                resized_frame = cv2.resize(frame, (640, 480))
                
                # Deteksi objek
                try:
                    results = model(resized_frame, verbose=False)[0]
                    person_boxes = []
                    
                    if results.boxes is not None:
                        for box in results.boxes:
                            if int(box.cls[0]) == 0:  # Person class
                                person_boxes.append(box)

                    person_count = len(person_boxes)

                    # Gambar bounding box
                    for box in person_boxes:
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        cv2.rectangle(resized_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        cv2.putText(resized_frame, 'Person', (x1, y1 - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                except Exception as yolo_error:
                    print(f"YOLO processing error in stream: {yolo_error}")
                    # Continue without YOLO processing
                    resized_frame = cv2.resize(frame, (640, 480))

                # Encode frame ke base64
                _, buffer = cv2.imencode('.jpg', resized_frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                frame_base64 = base64.b64encode(buffer).decode('utf-8')

                try:
                    # Kirim frame ke Laravel
                    payload = {
                        'frame': frame_base64,
                        'person_count': person_count,
                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }
                    
                    response = requests.post(LARAVEL_VIDEO_URL, json=payload, timeout=3)
                    
                    if response.status_code not in [200, 201]:
                        print(f"Error sending frame to Laravel: {response.status_code}")
                        
                except requests.exceptions.RequestException as e:
                    print(f"Error sending frame to Laravel: {str(e)}")
            
            frame_count += 1
            # Delay untuk mengontrol frame rate (15 FPS)
            time.sleep(0.067)
            
        except Exception as e:
            print(f"Error in video stream: {str(e)}")
            time.sleep(0.1)
    
    print("Video streaming thread ended")

def generate_frames():
    """Generator yang akan restart ketika camera dimulai ulang"""
    global cap, person_count, camera_active, last_frame, camera_session_id
    
    current_session = camera_session_id
    frame_count = 0
    
    while camera_active and current_session == camera_session_id:
        try:
            # Check if session has changed (camera restarted)
            if current_session != camera_session_id:
                print("Camera session changed, restarting generator")
                break
                
            # Check if camera is still active
            if not camera_active:
                break
                
            # Try to acquire lock with timeout
            if frame_lock.acquire(timeout=0.1):
                try:
                    if not cap or not cap.isOpened():
                        frame_lock.release()
                        break
                    success, frame = cap.read()
                finally:
                    frame_lock.release()
            else:
                # Jika tidak bisa acquire lock, gunakan frame terakhir
                if last_frame is not None:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + last_frame + b'\r\n')
                time.sleep(0.033)  # ~30 FPS
                continue
                
            if not success or frame is None:
                # Jika gagal capture, gunakan frame terakhir
                if last_frame is not None:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + last_frame + b'\r\n')
                time.sleep(0.033)
                continue

            # Process frame
            resized_frame = cv2.resize(frame, (640, 480))
            
            # Skip YOLO processing setiap beberapa frame untuk performance
            if frame_count % 3 == 0:  # Process setiap 3 frame
                try:
                    results = model(resized_frame, verbose=False)[0]
                    person_boxes = []
                    if results.boxes is not None:
                        for box in results.boxes:
                            if int(box.cls[0]) == 0:  # Person class
                                person_boxes.append(box)

                    person_count = len(person_boxes)

                    # Draw bounding boxes
                    for box in person_boxes:
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        cv2.rectangle(resized_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        cv2.putText(resized_frame, 'Person', (x1, y1 - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                except Exception as yolo_error:
                    print(f"YOLO processing error: {yolo_error}")
                    # Continue without YOLO processing
                    pass
            
            frame_count += 1

            # Encode frame
            ret, buffer = cv2.imencode('.jpg', resized_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ret:
                frame_bytes = buffer.tobytes()
                last_frame = frame_bytes  # Store for fallback
                
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            else:
                # Jika encoding gagal, gunakan frame terakhir
                if last_frame is not None:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + last_frame + b'\r\n')
            
            # Control frame rate
            time.sleep(0.033)  # ~30 FPS
                   
        except Exception as e:
            print(f"Error in generate_frames: {str(e)}")
            # Jika ada error, coba lanjutkan dengan frame terakhir
            if last_frame is not None:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + last_frame + b'\r\n')
            time.sleep(0.1)
            continue

@app.route('/video_feed')
def video_feed():
    """Modified video feed that handles camera restarts"""
    def generate_with_restart_handling():
        max_retries = 5
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                if not camera_active:
                    # Send placeholder frame when camera is not active
                    placeholder_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                    cv2.putText(placeholder_frame, "Camera Not Active", (200, 240), 
                               cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                    _, buffer = cv2.imencode('.jpg', placeholder_frame)
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
                    time.sleep(1)  # Wait before checking again
                    continue
                
                # Generate frames from active camera
                frame_generated = False
                for frame in generate_frames():
                    frame_generated = True
                    yield frame
                
                # If no frames were generated and camera is supposed to be active
                if not frame_generated and camera_active:
                    retry_count += 1
                    print(f"No frames generated, retry {retry_count}/{max_retries}")
                    time.sleep(0.5)
                else:
                    retry_count = 0  # Reset retry count on success
                    
            except Exception as e:
                print(f"Error in video feed generator: {str(e)}")
                retry_count += 1
                
                # Send error frame
                error_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(error_frame, f"Error: {str(e)[:30]}", (50, 240), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                _, buffer = cv2.imencode('.jpg', error_frame)
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
                time.sleep(1)
        
        # Send final error frame if max retries reached
        final_error_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(final_error_frame, "Max retries reached", (180, 240), 
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
        _, buffer = cv2.imencode('.jpg', final_error_frame)
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
    
    return Response(generate_with_restart_handling(),
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
    
    try:
        # Try to acquire lock with timeout
        if frame_lock.acquire(timeout=0.5):
            try:
                success, frame = cap.read()
            finally:
                frame_lock.release()
        else:
            return jsonify({'status': 'error', 'message': 'Camera busy, try again'})
            
        if not success or frame is None:
            return jsonify({'status': 'error', 'message': 'Failed to capture frame'})
        
        # Resize dan encode frame
        resized_frame = cv2.resize(frame, (640, 480))
        _, buffer = cv2.imencode('.jpg', resized_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        frame_base64 = base64.b64encode(buffer).decode('utf-8')
        
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

        response = requests.get(LARAVEL_API_URL, params=payload, timeout=10)

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
        response = requests.get(LARAVEL_API_URL, timeout=10)
        return jsonify({
            'status': 'success' if response.status_code == 200 else 'error',
            'response_code': response.status_code,
            'message': response.text if response.status_code != 200 else 'API connection successful'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/get_stream_status')
def get_stream_status():
    return jsonify({
        'camera_active': camera_active,
        'video_streaming': send_video_to_laravel,
        'person_count': person_count,
        'camera_available': cap is not None and cap.isOpened() if cap else False,
        'session_id': camera_session_id
    })

@app.route('/health')
def health_check():
    """Health check endpoint untuk monitoring"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'camera_active': camera_active,
        'video_streaming': send_video_to_laravel,
        'camera_available': cap is not None and cap.isOpened() if cap else False,
        'session_id': camera_session_id
    })

# Cleanup function untuk memastikan resources dibersihkan
def cleanup():
    global cap, camera_active, send_video_to_laravel, video_thread, stop_event
    
    print("Cleaning up resources...")
    
    camera_active = False
    send_video_to_laravel = False
    stop_event.set()
    
    # Wait for video thread to finish
    if video_thread and video_thread.is_alive():
        video_thread.join(timeout=3)
    
    # Release camera
    release_camera()
    
    print("Cleanup completed")

def signal_handler(sig, frame):
    """Handler untuk sinyal shutdown"""
    print("Received shutdown signal")
    cleanup()
    sys.exit(0)

# Register cleanup functions
import atexit
atexit.register(cleanup)
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

if __name__ == '__main__':
    # Konfigurasi untuk ngrok
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)