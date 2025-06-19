from flask import Flask, render_template, Response, jsonify, request
import cv2
import torch
import mysql.connector
from mysql.connector import Error
from datetime import datetime
import base64
import numpy as np
import threading
import json

app = Flask(__name__)

# Database configuration
DB_CONFIG = {
    'host': 'localhost',
    'database': 'person_detection',
    'user': 'your_username',
    'password': 'your_password'
}

class PersonDetector:
    def __init__(self):
        # Load YOLOv5 model
        self.model = torch.hub.load('ultralytics/yolov5', 'yolov5s', pretrained=True)
        self.model.classes = [0]  # Only detect persons (class 0 in COCO dataset)
        
        self.camera = cv2.VideoCapture(0)
        self.current_frame = None
        self.person_count = 0
        self.recording = False
        
        # Database setup
        self.init_database()
    
    def init_database(self):
        """Initialize database and create table if not exists"""
        try:
            connection = mysql.connector.connect(**DB_CONFIG)
            cursor = connection.cursor()
            
            create_table_query = """
            CREATE TABLE IF NOT EXISTS person_records (
                id INT AUTO_INCREMENT PRIMARY KEY,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                person_count INT NOT NULL,
                image_data LONGTEXT,
                coordinates JSON
            )
            """
            cursor.execute(create_table_query)
            connection.commit()
            
            cursor.close()
            connection.close()
            print("Database initialized successfully")
            
        except Error as e:
            print(f"Error initializing database: {e}")
    
    def detect_persons(self, frame):
        """Detect persons in frame using YOLO"""
        results = self.model(frame)
        
        # Extract person detections
        detections = results.pandas().xyxy[0]
        persons = detections[detections['name'] == 'person']
        
        person_count = len(persons)
        coordinates = []
        
        # Draw bounding boxes
        for _, person in persons.iterrows():
            x1, y1, x2, y2 = int(person['xmin']), int(person['ymin']), int(person['xmax']), int(person['ymax'])
            confidence = person['confidence']
            
            # Store coordinates
            coordinates.append({
                'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
                'confidence': float(confidence)
            })
            
            # Draw rectangle and label
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, f'Person {confidence:.2f}', (x1, y1-10), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        
        # Display person count
        cv2.putText(frame, f'Persons: {person_count}', (10, 30), 
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
        
        self.person_count = person_count
        return frame, coordinates
    
    def save_to_database(self, person_count, image_data, coordinates):
        """Save detection record to database"""
        try:
            connection = mysql.connector.connect(**DB_CONFIG)
            cursor = connection.cursor()
            
            insert_query = """
            INSERT INTO person_records (person_count, image_data, coordinates)
            VALUES (%s, %s, %s)
            """
            
            cursor.execute(insert_query, (person_count, image_data, json.dumps(coordinates)))
            connection.commit()
            
            record_id = cursor.lastrowid
            cursor.close()
            connection.close()
            
            return record_id
            
        except Error as e:
            print(f"Error saving to database: {e}")
            return None
    
    def record_current_frame(self):
        """Record current frame with person detection data"""
        if self.current_frame is not None:
            # Convert frame to base64 for storage
            _, buffer = cv2.imencode('.jpg', self.current_frame)
            image_base64 = base64.b64encode(buffer).decode('utf-8')
            
            # Detect persons and get coordinates
            _, coordinates = self.detect_persons(self.current_frame.copy())
            
            # Save to database
            record_id = self.save_to_database(self.person_count, image_base64, coordinates)
            
            return {
                'success': True,
                'record_id': record_id,
                'person_count': self.person_count,
                'timestamp': datetime.now().isoformat(),
                'coordinates': coordinates
            }
        
        return {'success': False, 'error': 'No frame available'}
    
    def generate_frames(self):
        """Generate video frames for streaming"""
        while True:
            success, frame = self.camera.read()
            if not success:
                break
            
            # Store current frame
            self.current_frame = frame.copy()
            
            # Detect persons
            frame_with_detections, _ = self.detect_persons(frame)
            
            # Encode frame
            ret, buffer = cv2.imencode('.jpg', frame_with_detections)
            frame = buffer.tobytes()
            
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

# Initialize detector
detector = PersonDetector()

@app.route('/')
def index():
    """Main page with video stream and controls"""
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    """Video streaming route"""
    return Response(detector.generate_frames(),
                   mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/record', methods=['POST'])
def record():
    """Record current frame with person detection"""
    result = detector.record_current_frame()
    return jsonify(result)

@app.route('/api/records', methods=['GET'])
def get_records():
    """API to get all records from database"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # Get query parameters
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        query = """
        SELECT id, timestamp, person_count, coordinates
        FROM person_records
        ORDER BY timestamp DESC
        LIMIT %s OFFSET %s
        """
        
        cursor.execute(query, (limit, offset))
        records = cursor.fetchall()
        
        # Convert datetime to string for JSON serialization
        for record in records:
            record['timestamp'] = record['timestamp'].isoformat()
            if record['coordinates']:
                record['coordinates'] = json.loads(record['coordinates'])
        
        cursor.close()
        connection.close()
        
        return jsonify({
            'success': True,
            'records': records,
            'count': len(records)
        })
        
    except Error as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/records/<int:record_id>', methods=['GET'])
def get_record(record_id):
    """API to get specific record by ID"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        query = """
        SELECT id, timestamp, person_count, image_data, coordinates
        FROM person_records
        WHERE id = %s
        """
        
        cursor.execute(query, (record_id,))
        record = cursor.fetchone()
        
        if record:
            record['timestamp'] = record['timestamp'].isoformat()
            if record['coordinates']:
                record['coordinates'] = json.loads(record['coordinates'])
            
            return jsonify({
                'success': True,
                'record': record
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Record not found'
            }), 404
        
        cursor.close()
        connection.close()
        
    except Error as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """API to get detection statistics"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # Get total records
        cursor.execute("SELECT COUNT(*) as total_records FROM person_records")
        total_records = cursor.fetchone()['total_records']
        
        # Get average person count
        cursor.execute("SELECT AVG(person_count) as avg_persons FROM person_records")
        avg_persons = cursor.fetchone()['avg_persons'] or 0
        
        # Get max person count
        cursor.execute("SELECT MAX(person_count) as max_persons FROM person_records")
        max_persons = cursor.fetchone()['max_persons'] or 0
        
        # Get records from today
        cursor.execute("""
            SELECT COUNT(*) as today_records 
            FROM person_records 
            WHERE DATE(timestamp) = CURDATE()
        """)
        today_records = cursor.fetchone()['today_records']
        
        cursor.close()
        connection.close()
        
        return jsonify({
            'success': True,
            'stats': {
                'total_records': total_records,
                'average_persons': round(float(avg_persons), 2),
                'max_persons': max_persons,
                'today_records': today_records
            }
        })
        
    except Error as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

if __name__ == '__main__':
    app.run(debug=True, threaded=True)