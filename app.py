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
import queue
import weakref

app = Flask(__name__)

# Load YOLOv8 model
model = YOLO("yolo-weights/yolo11n.pt")

# Laravel API endpoint
LARAVEL_API_URL = "http://127.0.0.1:8000/api/recordings/smartroomfhx"
LARAVEL_VIDEO_URL = "http://127.0.0.1:8000/api/video-feed/smartroomfhx"

# Global variables with proper synchronization
class CameraManager:
    def __init__(self):
        self.person_count = 0
        self.camera_active = False
        self.cap = None
        self.send_video_to_laravel = False
        self.frame_lock = Lock()
        self.video_thread = None
        self.stop_event = Event()
        self.last_frame = None
        self.camera_session_id = 0
        self.frame_queue = queue.Queue(maxsize=2)  # Buffer untuk frames
        self.state_lock = Lock()  # Lock untuk state management
        self.active_generators = set()  # Track active generators
        self.shutdown_in_progress = False
        
    def release_camera(self):
        """Safely release camera resources"""
        with self.frame_lock:
            if self.cap is not None:
                try:
                    self.cap.release()
                    time.sleep(0.2)  # Give more time for resource cleanup
                except Exception as e:
                    print(f"Error releasing camera: {e}")
                finally:
                    self.cap = None
            
            # Clear frame queue
            while not self.frame_queue.empty():
                try:
                    self.frame_queue.get_nowait()
                except queue.Empty:
                    break
            
            # Cleanup OpenCV windows
            try:
                cv2.destroyAllWindows()
            except:
                pass
    
    def initialize_camera(self):
        """Initialize camera with improved error handling"""
        self.release_camera()
        time.sleep(0.5)
        
        for attempt in range(3):
            try:
                print(f"Camera initialization attempt {attempt + 1}")
                
                for camera_index in [0, 1, 2]:
                    try:
                        # Try different backends
                        backends = [cv2.CAP_DSHOW, cv2.CAP_V4L2, cv2.CAP_ANY]
                        
                        for backend in backends:
                            with self.frame_lock:
                                self.cap = cv2.VideoCapture(1, backend)
                                
                                if self.cap.isOpened():
                                    # Test capture
                                    ret, frame = self.cap.read()
                                    if ret and frame is not None:
                                        # Set camera properties
                                        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                                        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                                        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                                        self.cap.set(cv2.CAP_PROP_FPS, 30)
                                        
                                        print(f"Camera initialized on index {camera_index}")
                                        return True
                                
                                if self.cap:
                                    self.cap.release()
                                    self.cap = None
                                    
                    except Exception as e:
                        print(f"Error with camera {camera_index}: {e}")
                        if self.cap:
                            self.cap.release()
                            self.cap = None
                        continue
                
                print(f"Attempt {attempt + 1} failed, retrying...")
                time.sleep(1)
                
            except Exception as e:
                print(f"Error in initialization attempt {attempt + 1}: {e}")
                time.sleep(1)
        
        print("Failed to initialize camera after all attempts")
        return False
    
    def start_camera(self):
        """Start camera with proper state management"""
        with self.state_lock:
            # Stop any existing operations
            self.stop_all_operations()
            
            # Increment session ID
            self.camera_session_id += 1
            current_session = self.camera_session_id
            
            # Initialize camera
            if self.initialize_camera():
                self.camera_active = True
                print(f"Camera started with session ID: {current_session}")
                return True, current_session
            else:
                self.camera_active = False
                return False, current_session
    
    def stop_camera(self):
        """Stop camera with proper cleanup"""
        with self.state_lock:
            print("Stopping camera...")
            self.stop_all_operations()
            
            # Mark all generators as inactive
            for gen_ref in list(self.active_generators):
                try:
                    gen = gen_ref()
                    if gen:
                        gen.active = False
                except:
                    pass
            self.active_generators.clear()
            
            # Release camera
            self.release_camera()
            
            # Reset state
            self.camera_active = False
            self.last_frame = None
            self.person_count = 0
            
            print("Camera stopped successfully")
    
    def stop_all_operations(self):
        """Stop all camera operations"""
        # Stop video streaming
        if self.send_video_to_laravel:
            self.send_video_to_laravel = False
            self.stop_event.set()
            
        # Wait for video thread to finish
        if self.video_thread and self.video_thread.is_alive():
            print("Waiting for video thread to finish...")
            self.video_thread.join(timeout=3)
            if self.video_thread.is_alive():
                print("Video thread did not finish cleanly")
        
        # Reset thread and event
        self.video_thread = None
        self.stop_event.clear()
    
    def start_video_stream(self):
        """Start video streaming with improved thread management"""
        with self.state_lock:
            if not self.camera_active or not self.cap or not self.cap.isOpened():
                return False, "Camera not active"
            
            # Stop existing video stream
            self.stop_video_stream()
            
            # Start new video stream
            self.send_video_to_laravel = True
            self.video_thread = threading.Thread(target=self.send_video_stream_to_laravel)
            self.video_thread.daemon = True
            self.video_thread.start()
            
            return True, "Video streaming started"
    
    def stop_video_stream(self):
        """Stop video streaming"""
        if self.send_video_to_laravel:
            self.send_video_to_laravel = False
            self.stop_event.set()
            
        if self.video_thread and self.video_thread.is_alive():
            self.video_thread.join(timeout=3)
        
        self.video_thread = None
        self.stop_event.clear()
    
    def send_video_stream_to_laravel(self):
        """Send video stream to Laravel"""
        print("Video streaming thread started")
        frame_count = 0
        
        while self.send_video_to_laravel and not self.stop_event.is_set():
            try:
                if self.stop_event.wait(timeout=0.001):
                    break
                
                success, frame = self.get_frame()
                
                if not success or frame is None:
                    time.sleep(0.1)
                    continue
                
                # Process every 2nd frame for performance
                if frame_count % 2 == 0:
                    resized_frame = cv2.resize(frame, (640, 480))
                    
                    # YOLO detection
                    try:
                        results = model(resized_frame, verbose=False)[0]
                        person_boxes = []
                        
                        if results.boxes is not None:
                            for box in results.boxes:
                                if int(box.cls[0]) == 0:  # Person class
                                    person_boxes.append(box)
                        
                        self.person_count = len(person_boxes)
                        
                        # Draw bounding boxes
                        for box in person_boxes:
                            x1, y1, x2, y2 = map(int, box.xyxy[0])
                            cv2.rectangle(resized_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                            cv2.putText(resized_frame, 'Person', (x1, y1 - 10),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                    except Exception as yolo_error:
                        print(f"YOLO processing error: {yolo_error}")
                        resized_frame = cv2.resize(frame, (640, 480))
                    
                    # Encode and send frame
                    _, buffer = cv2.imencode('.jpg', resized_frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    frame_base64 = base64.b64encode(buffer).decode('utf-8')
                    
                    try:
                        payload = {
                            'frame': frame_base64,
                            'person_count': self.person_count,
                            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        }
                        
                        response = requests.post(LARAVEL_VIDEO_URL, json=payload, timeout=3)
                        
                        if response.status_code not in [200, 201]:
                            print(f"Error sending frame: {response.status_code}")
                            
                    except requests.exceptions.RequestException as e:
                        print(f"Request error: {str(e)}")
                
                frame_count += 1
                time.sleep(0.067)  # ~15 FPS
                
            except Exception as e:
                print(f"Error in video stream: {str(e)}")
                time.sleep(0.1)
        
        print("Video streaming thread ended")
    
    def get_frame(self):
        """Safely get frame from camera"""
        if not self.cap or not self.cap.isOpened():
            return False, None
        
        try:
            if self.frame_lock.acquire(timeout=0.1):
                try:
                    return self.cap.read()
                finally:
                    self.frame_lock.release()
            else:
                return False, None
        except Exception as e:
            print(f"Error getting frame: {e}")
            return False, None
    
    def create_frame_generator(self):
        """Create a new frame generator"""
        class FrameGenerator:
            def __init__(self, camera_manager, session_id):
                self.camera_manager = camera_manager
                self.session_id = session_id
                self.active = True
                self.frame_count = 0
                
                # Register this generator
                self.camera_manager.active_generators.add(weakref.ref(self))
            
            def generate(self):
                """Generate frames for web streaming"""
                while (self.active and 
                       self.camera_manager.camera_active and 
                       self.session_id == self.camera_manager.camera_session_id):
                    
                    try:
                        success, frame = self.camera_manager.get_frame()
                        
                        if not success or frame is None:
                            if self.camera_manager.last_frame is not None:
                                yield (b'--frame\r\n'
                                       b'Content-Type: image/jpeg\r\n\r\n' + 
                                       self.camera_manager.last_frame + b'\r\n')
                            time.sleep(0.033)
                            continue
                        
                        # Process frame
                        resized_frame = cv2.resize(frame, (640, 480))
                        
                        # YOLO processing every 3rd frame
                        if self.frame_count % 3 == 0:
                            try:
                                results = model(resized_frame, verbose=False)[0]
                                person_boxes = []
                                
                                if results.boxes is not None:
                                    for box in results.boxes:
                                        if int(box.cls[0]) == 0:  # Person class
                                            person_boxes.append(box)
                                
                                self.camera_manager.person_count = len(person_boxes)
                                
                                # Draw bounding boxes
                                for box in person_boxes:
                                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                                    cv2.rectangle(resized_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                                    cv2.putText(resized_frame, 'Person', (x1, y1 - 10),
                                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                            except Exception as yolo_error:
                                print(f"YOLO processing error: {yolo_error}")
                        
                        self.frame_count += 1
                        
                        # Encode frame
                        ret, buffer = cv2.imencode('.jpg', resized_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                        if ret:
                            frame_bytes = buffer.tobytes()
                            self.camera_manager.last_frame = frame_bytes
                            
                            yield (b'--frame\r\n'
                                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                        else:
                            if self.camera_manager.last_frame is not None:
                                yield (b'--frame\r\n'
                                       b'Content-Type: image/jpeg\r\n\r\n' + 
                                       self.camera_manager.last_frame + b'\r\n')
                        
                        time.sleep(0.033)  # ~30 FPS
                        
                    except Exception as e:
                        print(f"Error in frame generator: {str(e)}")
                        if self.camera_manager.last_frame is not None:
                            yield (b'--frame\r\n'
                                   b'Content-Type: image/jpeg\r\n\r\n' + 
                                   self.camera_manager.last_frame + b'\r\n')
                        time.sleep(0.1)
                
                print("Frame generator ended")
        
        return FrameGenerator(self, self.camera_session_id)

# Initialize camera manager
camera_manager = CameraManager()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start_camera', methods=['POST'])
def start_camera():
    try:
        success, session_id = camera_manager.start_camera()
        
        if success:
            return jsonify({
                'status': 'success',
                'message': 'Camera started successfully',
                'session_id': session_id
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'Failed to initialize camera'
            })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Error starting camera: {str(e)}'
        })

@app.route('/stop_camera', methods=['POST'])
def stop_camera():
    try:
        camera_manager.stop_camera()
        return jsonify({
            'status': 'success',
            'message': 'Camera stopped successfully'
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Error stopping camera: {str(e)}'
        })

@app.route('/start_video_stream', methods=['POST'])
def start_video_stream():
    try:
        success, message = camera_manager.start_video_stream()
        
        if success:
            return jsonify({'status': 'success', 'message': message})
        else:
            return jsonify({'status': 'error', 'message': message})
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Error starting video stream: {str(e)}'
        })

@app.route('/stop_video_stream', methods=['POST'])
def stop_video_stream():
    try:
        camera_manager.stop_video_stream()
        return jsonify({
            'status': 'success',
            'message': 'Video streaming stopped'
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Error stopping video stream: {str(e)}'
        })

@app.route('/video_feed')
def video_feed():
    """Video feed endpoint with improved generator management"""
    if not camera_manager.camera_active:
        # Return placeholder when camera is not active
        def placeholder_generator():
            while not camera_manager.camera_active:
                placeholder_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(placeholder_frame, "Camera Not Active", (200, 240),
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                _, buffer = cv2.imencode('.jpg', placeholder_frame)
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
                time.sleep(1)
        
        return Response(placeholder_generator(),
                        mimetype='multipart/x-mixed-replace; boundary=frame')
    
    # Create and return frame generator
    generator = camera_manager.create_frame_generator()
    return Response(generator.generate(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/get_count')
def get_count():
    return jsonify({'count': camera_manager.person_count})

@app.route('/send_frame', methods=['POST'])
def send_frame():
    """Send single frame to Laravel"""
    if not camera_manager.camera_active:
        return jsonify({'status': 'error', 'message': 'Camera not active'})
    
    try:
        success, frame = camera_manager.get_frame()
        
        if not success or frame is None:
            return jsonify({'status': 'error', 'message': 'Failed to capture frame'})
        
        # Process and encode frame
        resized_frame = cv2.resize(frame, (640, 480))
        _, buffer = cv2.imencode('.jpg', resized_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        frame_base64 = base64.b64encode(buffer).decode('utf-8')
        
        payload = {
            'frame': frame_base64,
            'person_count': camera_manager.person_count,
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
                'code': response.status_code
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
        payload = {
            'event_name': event_name,
            'person_count': camera_manager.person_count
        }

        response = requests.get(LARAVEL_API_URL, params=payload, timeout=10)

        if response.status_code in [200, 201]:
            return jsonify({
                'status': 'success',
                'message': 'Data sent successfully',
                'data': {
                    'event_name': event_name,
                    'person_count': camera_manager.person_count,
                    'timestamp': timestamp
                }
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'Failed to send to Laravel',
                'code': response.status_code
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
        'camera_active': camera_manager.camera_active,
        'video_streaming': camera_manager.send_video_to_laravel,
        'person_count': camera_manager.person_count,
        'camera_available': camera_manager.cap is not None and camera_manager.cap.isOpened() if camera_manager.cap else False,
        'session_id': camera_manager.camera_session_id
    })

@app.route('/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'camera_active': camera_manager.camera_active,
        'video_streaming': camera_manager.send_video_to_laravel,
        'camera_available': camera_manager.cap is not None and camera_manager.cap.isOpened() if camera_manager.cap else False,
        'session_id': camera_manager.camera_session_id
    })

def cleanup():
    """Cleanup resources on shutdown"""
    print("Cleaning up resources...")
    camera_manager.shutdown_in_progress = True
    camera_manager.stop_camera()
    print("Cleanup completed")

def signal_handler(sig, frame):
    """Handle shutdown signals"""
    print("Received shutdown signal")
    cleanup()
    sys.exit(0)

# Register cleanup functions
import atexit
atexit.register(cleanup)
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)