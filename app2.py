from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_file, make_response
from datetime import datetime
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import cv2
from threading import Lock
import time
import numpy as np
from ultralytics import YOLO
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
import tempfile
import io

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'supersecretkey')

# --- Konfigurasi akun login (hanya di backend, tidak di web) ---
USERS = {
    'admin': 'password123',
    'user1': 'userpass1',
    'user2': 'passwordku',
    'kominfo': 'kominfo2025',
    'banyumas': 'banyumas123'
}

# --- Konfigurasi koneksi PostgreSQL ---
DB_HOST = os.environ.get('DB_HOST', '10.98.33.122')
DB_PORT = os.environ.get('DB_PORT', '5433')
DB_NAME = os.environ.get('DB_NAME', 'person_counter')
DB_USER = os.environ.get('DB_USER', 'magang')
DB_PASS = os.environ.get('DB_PASS', 'magang123#')

def get_db_connection():
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
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

# Helper untuk ambil record berdasarkan ID
def get_record_by_id(record_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM records WHERE id = %s;", (record_id,))
    record = cur.fetchone()
    cur.close()
    conn.close()
    return record

# Fungsi untuk generate PDF single record
def generate_single_record_pdf(record):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []
    
    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=20,
        spaceAfter=30,
        alignment=TA_CENTER
    )
    
    # Header
    title = Paragraph("Smart Room Person Counter - Record Report", title_style)
    story.append(title)
    story.append(Spacer(1, 12))
    
    # Record details
    data = [
        ['Record ID:', str(record['id'])],
        ['Event Name:', record['event_name']],
        ['Person Count:', str(record['person_count'])],
        ['Timestamp:', record['timestamp']],
    ]
    
    table = Table(data, colWidths=[2*inch, 3*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.grey),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('BACKGROUND', (1, 0), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    story.append(table)
    story.append(Spacer(1, 20))
    
    # Add snapshot if available
    if record.get('snapshot_url'):
        story.append(Paragraph("Snapshot:", styles['Heading2']))
        story.append(Spacer(1, 10))
        
        try:
            # Construct full path to snapshot
            snapshot_path = record['snapshot_url'].lstrip('/')
            full_path = os.path.join(app.root_path, snapshot_path)
            
            if os.path.exists(full_path):
                img = Image(full_path, width=4*inch, height=3*inch)
                story.append(img)
            else:
                story.append(Paragraph("Snapshot not found", styles['Normal']))
        except Exception as e:
            story.append(Paragraph(f"Error loading snapshot: {str(e)}", styles['Normal']))
    
    # Footer
    story.append(Spacer(1, 30))
    footer = Paragraph(f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal'])
    story.append(footer)
    
    doc.build(story)
    buffer.seek(0)
    return buffer

# Fungsi untuk generate PDF multiple records
def generate_multiple_records_pdf(records):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []
    
    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=20,
        spaceAfter=30,
        alignment=TA_CENTER
    )
    
    # Header
    title = Paragraph("Smart Room Person Counter - All Records Report", title_style)
    story.append(title)
    story.append(Spacer(1, 12))
    
    # Summary
    summary = Paragraph(f"Total Records: {len(records)}", styles['Heading2'])
    story.append(summary)
    story.append(Spacer(1, 20))
    
    # Table headers
    data = [['No.', 'Event Name', 'Person Count', 'Timestamp']]
    
    # Add records data
    for idx, record in enumerate(records, 1):
        data.append([
            str(idx),
            record['event_name'],
            str(record['person_count']),
            record['timestamp']
        ])
    
    table = Table(data, colWidths=[0.5*inch, 2.5*inch, 1*inch, 2*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey])
    ]))
    
    story.append(table)
    story.append(Spacer(1, 30))
    
    # Footer
    footer = Paragraph(f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal'])
    story.append(footer)
    
    doc.build(story)
    buffer.seek(0)
    return buffer

# --- Proteksi dashboard ---
@app.route('/')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('dashboard2.html')

# --- Login page ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        print(f"DEBUG LOGIN: username='{username}', password='{password}'")
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
    save_path = os.path.join('static', 'snapshots', filename)
    cv2.imwrite(save_path, frame)
    snapshot_url = f"/static/snapshots/{filename}"

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

# --- PDF Export Routes ---
@app.route('/export/record/<int:record_id>/pdf')
def export_single_record_pdf(record_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    try:
        record = get_record_by_id(record_id)
        if not record:
            return jsonify({'status': 'error', 'message': 'Record not found'}), 404
        
        pdf_buffer = generate_single_record_pdf(record)
        filename = f"record_{record_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        
        return send_file(
            pdf_buffer,
            as_attachment=True,
            download_name=filename,
            mimetype='application/pdf'
        )
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/export/records/pdf')
def export_all_records_pdf():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    try:
        records = get_all_records()
        if not records:
            return jsonify({'status': 'error', 'message': 'No records found'}), 404
        
        pdf_buffer = generate_multiple_records_pdf(records)
        filename = f"all_records_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        
        return send_file(
            pdf_buffer,
            as_attachment=True,
            download_name=filename,
            mimetype='application/pdf'
        )
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# --- Camera variables ---
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
            camera = cv2.VideoCapture(1, cv2.CAP_DSHOW)
        return camera

# Load YOLOv8 model
model = YOLO("yolo-weights/yolo11n.pt")

def gen_frames():
    global person_count
    frame_count = 0
    while True:
        cam = get_camera()
        if not cam or not cam.isOpened():
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
        if frame_count % 1 == 0:
            try:
                results = model(resized_frame, verbose=False)[0]
                person_boxes = []
                if results.boxes is not None:
                    for box in results.boxes:
                        if int(box.cls[0]) == 0 and float(box.conf[0]) > 0.5:
                            person_boxes.append(box)
                person_count = len(person_boxes)
                for box in person_boxes:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    cv2.rectangle(resized_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(resized_frame, 'Person', (x1, y1 - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            except Exception as e:
                print(f"YOLO error: {e}")
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