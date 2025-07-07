from flask import Flask, Response, request
from flask_cors import CORS
import cv2
import threading
import time
import base64
import json

app = Flask(__name__)
CORS(app)  # Enable CORS for cross-origin requests

class VideoCamera:
    def __init__(self):
        self.video = cv2.VideoCapture(0)  # Use default camera
        self.video.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.video.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.video.set(cv2.CAP_PROP_FPS, 30)
        
    def __del__(self):
        self.video.release()
        
    def get_frame(self):
        success, image = self.video.read()
        if not success:
            return None
        
        # Encode frame to JPEG
        ret, jpeg = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return jpeg.tobytes()
    
    def get_frame_base64(self):
        frame = self.get_frame()
        if frame is None:
            return None
        return base64.b64encode(frame).decode('utf-8')

# Global camera instance
camera = VideoCamera()

def generate_frames():
    """Generate video frames for streaming"""
    while True:
        frame = camera.get_frame()
        if frame is None:
            continue
            
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/')
def index():
    return '''
    <html>
    <head><title>Video Stream</title></head>
    <body>
        <h1>Video Stream Test</h1>
        <img src="/video_feed" width="640" height="480">
    </body>
    </html>
    '''

@app.route('/video_feed')
def video_feed():
    """Video streaming route for MJPEG"""
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/frame')
def get_frame_api():
    """API endpoint to get single frame as base64"""
    frame_b64 = camera.get_frame_base64()
    if frame_b64 is None:
        return json.dumps({'error': 'No frame available'}), 500
        
    return json.dumps({
        'frame': frame_b64,
        'timestamp': time.time()
    })

@app.route('/api/stream')
def stream_api():
    """API endpoint for Server-Sent Events streaming"""
    def generate():
        while True:
            frame_b64 = camera.get_frame_base64()
            if frame_b64:
                yield f"data: {json.dumps({'frame': frame_b64, 'timestamp': time.time()})}\n\n"
            time.sleep(1/30)  # 30 FPS
    
    return Response(generate(), mimetype='text/plain')

@app.route('/status')
def status():
    """Health check endpoint"""
    return json.dumps({
        'status': 'running',
        'timestamp': time.time()
    })

if __name__ == '__main__':
    # Run on all interfaces to allow external access
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)