from flask import Flask, render_template, Response, jsonify, request
from ultralytics import YOLO
import cv2
import math
import threading
import time
import numpy as np
import mysql.connector
from mysql.connector import Error
from datetime import datetime
import os

app = Flask(__name__)

# Global variables
person_count = 0
latest_frame = None
camera_active = False
cap = None
model = None
frame_skip_counter = 0
FRAME_SKIP = 10  # Process every 3rd frame only

# MySQL Database configuration
DB_CONFIG = {
    'host': 'https://withink.pro/',
    'database': 'u704290269_smartroom',
    'user': 'u704290269_smartroom',  # Ganti dengan username MySQL Anda
    'password': 'Pokro123321',  # Ganti dengan password MySQL Anda
    'port': 3306
}

def get_db_connection():
    """Create and return database connection"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        return connection
    except Error as e:
        print(f"Error connecting to MySQL: {e}")
        return None

def init_database():
    """Initialize the database with required tables"""
    try:
        connection = get_db_connection()
        if connection is None:
            print("Failed to connect to database")
            return False
            
        cursor = connection.cursor()
        
        # Create database if not exists
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_CONFIG['database']}")
        cursor.execute(f"USE {DB_CONFIG['database']}")
        
        # Create table
        create_table_query = '''
            CREATE TABLE IF NOT EXISTS recordings (
                id INT AUTO_INCREMENT PRIMARY KEY,
                event_name VARCHAR(255) NOT NULL,
                person_count INT NOT NULL,
                timestamp DATETIME NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        '''
        
        cursor.execute(create_table_query)
        connection.commit()
        cursor.close()
        connection.close()
        print("MySQL database initialized successfully")
        return True
        
    except Error as e:
        print(f"Database initialization error: {e}")
        return False

def save_to_database(event_name, person_count, timestamp):
    """Save recording data to database"""
    try:
        connection = get_db_connection()
        if connection is None:
            return False
            
        cursor = connection.cursor()
        
        insert_query = '''
            INSERT INTO recordings (event_name, person_count, timestamp)
            VALUES (%s, %s, %s)
        '''
        
        cursor.execute(insert_query, (event_name, person_count, timestamp))
        connection.commit()
        cursor.close()
        connection.close()
        return True
        
    except Error as e:
        print(f"Database save error: {e}")
        return False

def get_recordings():
    """Get all recordings from database"""
    try:
        connection = get_db_connection()
        if connection is None:
            return []
            
        cursor = connection.cursor(dictionary=True)
        
        query = '''
            SELECT id, event_name, person_count, timestamp, created_at
            FROM recordings
            ORDER BY created_at DESC
            LIMIT 50
        '''
        
        cursor.execute(query)
        recordings = cursor.fetchall()
        cursor.close()
        connection.close()
        
        # Convert datetime objects to strings for JSON serialization
        for record in recordings:
            if record['timestamp']:
                record['timestamp'] = record['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
            if record['created_at']:
                record['created_at'] = record['created_at'].strftime('%Y-%m-%d %H:%M:%S')
        
        return recordings
        
    except Error as e:
        print(f"Database fetch error: {e}")
        return []

def initialize_camera_and_model():
    """Initialize camera and YOLO model with optimized settings"""
    global cap, model
    try:
        # Try different camera indices if 0 doesn't work
        for camera_index in [0, 1, 2]:
            cap = cv2.VideoCapture(camera_index)
            if cap.isOpened():
                print(f"Camera opened successfully with index {camera_index}")
                break
        
        if not cap.isOpened():
            print("No camera found")
            return False
        
        # Reduced resolution for faster processing
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 480)  # Reduced from 640
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 360)  # Reduced from 480
        cap.set(cv2.CAP_PROP_FPS, 15)  # Reduced FPS
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Reduce buffer size
        
        # Test if camera can capture frames
        ret, frame = cap.read()
        if not ret:
            print("Camera opened but cannot read frames")
            cap.release()
            return False
        
        # Use YOLOv8 nano model (lightest version)
        model = YOLO("yolo-Weights/yolov8n.pt")
        print("Model loaded successfully")
        return True
    except Exception as e:
        print(f"Error initializing camera/model: {e}")
        return False

def resize_frame(frame, scale=0.6):
    """Resize frame for faster processing"""
    height, width = frame.shape[:2]
    new_width = int(width * scale)
    new_height = int(height * scale)
    return cv2.resize(frame, (new_width, new_height))

def generate_frames():
    """Generate frames for video streaming with optimizations"""
    global person_count, latest_frame, camera_active, cap, frame_skip_counter
    
    if not camera_active or cap is None:
        return
    
    last_detection_result = []
    detection_frame_counter = 0
    
    while camera_active and cap is not None:
        try:
            success, img = cap.read()
            if not success:
                print("Failed to read from camera")
                time.sleep(0.1)
                continue
            
            frame_skip_counter += 1
            current_person_count = 0
            
            # Only run YOLO detection every FRAME_SKIP frames
            if frame_skip_counter >= FRAME_SKIP:
                frame_skip_counter = 0
                detection_frame_counter += 1
                
                # Resize frame for faster YOLO processing
                small_frame = resize_frame(img, scale=0.5)
                
                # Run YOLO detection on smaller frame
                results = model(small_frame, 
                              stream=True, 
                              verbose=False,  # Reduce console output
                              conf=0.5,      # Higher confidence threshold
                              classes=[0])   # Only detect person class
                
                # Clear previous detections
                last_detection_result = []
                
                # Process detections
                for r in results:
                    boxes = r.boxes
                    if boxes is not None:
                        for box in boxes:
                            # Scale coordinates back to original frame
                            x1, y1, x2, y2 = box.xyxy[0]
                            x1, y1, x2, y2 = int(x1 * 2), int(y1 * 2), int(x2 * 2), int(y2 * 2)
                            
                            # Confidence
                            confidence = math.ceil((box.conf[0]*100))/100
                            
                            # Store detection for reuse
                            last_detection_result.append({
                                'bbox': (x1, y1, x2, y2),
                                'confidence': confidence
                            })
                            current_person_count += 1
            else:
                # Reuse last detection results
                current_person_count = len(last_detection_result)
            
            # Draw bounding boxes from stored results
            for detection in last_detection_result:
                x1, y1, x2, y2 = detection['bbox']
                confidence = detection['confidence']
                
                # Draw bounding box
                cv2.rectangle(img, (x1, y1), (x2, y2), (255, 0, 255), 2)  # Thinner line
                
                # Add label with confidence (smaller font)
                label = f"Person {confidence}"
                cv2.putText(img, label, (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 
                          0.5, (255, 0, 0), 1)  # Smaller font and thickness
            
            # Update global person count
            person_count = current_person_count
            
            # Add person count to frame
            cv2.putText(img, f"Count: {person_count}", (10, 25), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            
            # Encode frame to JPEG with lower quality for faster streaming
            ret, buffer = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 60])
            if not ret:
                print("Failed to encode frame")
                continue
                
            frame = buffer.tobytes()
            
            # Yield frame in multipart format
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            
            # Control frame rate - process at ~10 FPS instead of 30
            time.sleep(0.05)
            
        except Exception as e:
            print(f"Error in generate_frames: {e}")
            time.sleep(0.1)
            continue

@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    """Video streaming route"""
    if not camera_active:
        return Response("", mimetype='multipart/x-mixed-replace; boundary=frame')
    return Response(generate_frames(),
                   mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/start_camera', methods=['POST'])
def start_camera():
    """Start camera and detection"""
    global camera_active
    
    if not camera_active:
        if initialize_camera_and_model():
            camera_active = True
            print("Camera started successfully")
            return jsonify({'status': 'success', 'message': 'Camera started'})
        else:
            return jsonify({'status': 'error', 'message': 'Failed to initialize camera. Check console for details.'})
    else:
        return jsonify({'status': 'info', 'message': 'Camera already running'})

@app.route('/stop_camera', methods=['POST'])
def stop_camera():
    """Stop camera and detection"""
    global camera_active, cap
    
    camera_active = False
    if cap:
        cap.release()
    return jsonify({'status': 'success', 'message': 'Camera stopped'})

@app.route('/get_count')
def get_count():
    """Get current person count"""
    return jsonify({'count': person_count})

@app.route('/record_data', methods=['POST'])
def record_data():
    """Record current data to database"""
    try:
        data = request.get_json()
        event_name = data.get('event_name', '').strip()
        
        if not event_name:
            return jsonify({'status': 'error', 'message': 'Event name is required'})
        
        # Get current timestamp
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Save to database
        if save_to_database(event_name, person_count, current_time):
            return jsonify({
                'status': 'success', 
                'message': f'Data recorded successfully for "{event_name}"',
                'data': {
                    'event_name': event_name,
                    'person_count': person_count,
                    'timestamp': current_time
                }
            })
        else:
            return jsonify({'status': 'error', 'message': 'Failed to save data to database'})
            
    except Exception as e:
        print(f"Error recording data: {e}")
        return jsonify({'status': 'error', 'message': 'Internal server error'})

@app.route('/get_recordings')
def get_recordings_api():
    """Get all recordings from database"""
    recordings = get_recordings()
    return jsonify({'recordings': recordings})

@app.route('/delete_recording/<int:record_id>', methods=['DELETE'])
def delete_recording(record_id):
    """Delete a specific recording"""
    try:
        connection = get_db_connection()
        if connection is None:
            return jsonify({'status': 'error', 'message': 'Database connection failed'})
            
        cursor = connection.cursor()
        
        cursor.execute('DELETE FROM recordings WHERE id = %s', (record_id,))
        
        if cursor.rowcount > 0:
            connection.commit()
            cursor.close()
            connection.close()
            return jsonify({'status': 'success', 'message': 'Recording deleted successfully'})
        else:
            cursor.close()
            connection.close()
            return jsonify({'status': 'error', 'message': 'Recording not found'})
            
    except Error as e:
        print(f"Error deleting recording: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to delete recording'})

# Additional optimization routes
# @app.route('/set_quality/<int:quality>', methods=['POST'])
# def set_quality(quality):
#     """Adjust processing quality (1=lowest, 3=highest)"""
#     global FRAME_SKIP
    
#     if quality == 1:  # Lowest quality, fastest
#         FRAME_SKIP = 5
#     elif quality == 2:  # Medium quality
#         FRAME_SKIP = 3
#     else:  # Highest quality, slowest
#         FRAME_SKIP = 1
    
#     return jsonify({'status': 'success', 'message': f'Quality set to level {quality}'})

if __name__ == '__main__':
    # Initialize database on startup
    init_database()
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)