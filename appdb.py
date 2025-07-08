from flask import Flask, render_template, Response, jsonify, request, send_file
from datetime import datetime
import requests
import cv2
from ultralytics import YOLO
import numpy as np
import base64
import threading
import time
import os
import signal
import sys
import mysql.connector
import csv
from io import BytesIO
from fpdf import FPDF

app = Flask(__name__)

model = YOLO("yolo-weights/yolo11n.pt")

# Database config
db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '',  # Ganti jika perlu
    'database': 'smart'
}

cap = None
frame_lock = threading.Lock()
person_count = 0

@app.route('/')
def index():
    return "Flask YOLO Event Recorder"

@app.route('/record_to_mysql', methods=['POST'])
def record_to_mysql():
    global cap, person_count

    event_name = request.form.get('event_name', '').strip()
    if not event_name:
        return jsonify({'status': 'error', 'message': 'Event name is required'})

    if not cap or not cap.isOpened():
        cap = cv2.VideoCapture(0)

    try:
        if frame_lock.acquire(timeout=0.5):
            try:
                success, frame = cap.read()
            finally:
                frame_lock.release()
        else:
            return jsonify({'status': 'error', 'message': 'Camera busy'})

        if not success or frame is None:
            return jsonify({'status': 'error', 'message': 'Failed to capture frame'})

        resized_frame = cv2.resize(frame, (640, 480))
        results = model(resized_frame, verbose=False)[0]
        boxes = results.boxes
        person_count = sum(1 for box in boxes if int(box.cls[0]) == 0)

        _, buffer = cv2.imencode('.jpg', resized_frame)
        image_blob = buffer.tobytes()

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        sql = "INSERT INTO event_records (event_name, person_count, snapshot) VALUES (%s, %s, %s)"
        val = (event_name, person_count, image_blob)
        cursor.execute(sql, val)
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({
            'status': 'success',
            'message': 'Data saved to MySQL',
            'data': {
                'event_name': event_name,
                'person_count': person_count,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        })

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/export_csv')
def export_csv():
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("SELECT id, event_name, person_count, created_at FROM event_records")
        rows = cursor.fetchall()

        output = BytesIO()
        writer = csv.writer(output)
        writer.writerow(['ID', 'Event Name', 'Person Count', 'Created At'])
        for row in rows:
            writer.writerow(row)

        output.seek(0)
        cursor.close()
        conn.close()

        return send_file(output, mimetype='text/csv',
                         download_name=f'event_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv',
                         as_attachment=True)

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

class PDF(FPDF):
    def header(self):
        self.set_font("Arial", "B", 12)
        self.cell(0, 10, "Event Report", 0, 1, "C")

    def footer(self):
        self.set_y(-15)
        self.set_font("Arial", "I", 8)
        self.cell(0, 10, f"Page {self.page_no()}", 0, 0, "C")

@app.route('/export_pdf')
def export_pdf():
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("SELECT id, event_name, person_count, created_at FROM event_records")
        rows = cursor.fetchall()

        pdf = PDF()
        pdf.add_page()
        pdf.set_font("Arial", "", 11)

        col_width = 48
        row_height = 8
        pdf.set_fill_color(200, 220, 255)
        headers = ['ID', 'Event Name', 'Person Count', 'Created At']
        for header in headers:
            pdf.cell(col_width, row_height, header, border=1, fill=True)
        pdf.ln(row_height)

        for row in rows:
            for item in row:
                pdf.cell(col_width, row_height, str(item), border=1)
            pdf.ln(row_height)

        output = BytesIO()
        pdf.output(output)
        output.seek(0)

        cursor.close()
        conn.close()

        return send_file(output, mimetype='application/pdf',
                         download_name=f'event_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf',
                         as_attachment=True)

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)