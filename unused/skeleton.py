from ultralytics import YOLO
import cv2
import csv

# Load model pose estimation
model = YOLO("yolo11n-pose.pt")

# Open webcam
cap = cv2.VideoCapture(0)

# Buat CSV dan tulis header
csv_file = open("pose_output.csv", mode="w", newline="")
csv_writer = csv.writer(csv_file)
# Header: frame, person_id, x0, y0, conf0, x1, y1, conf1, ...
csv_header = ["frame", "person"]
for i in range(17):  # 17 keypoints (COCO format)
    csv_header += [f"x{i}", f"y{i}", f"conf{i}"]
csv_writer.writerow(csv_header)

frame_number = 0

while True:
    ret, frame = cap.read()
    if not ret:
        break

    # Predict pose (skeleton)
    results = model.predict(frame, stream=True, task='pose')

    for result in results:
        frame_number += 1
        frame = result.plot()

        # Ambil semua keypoints (banyak orang)
        keypoints_list = result.keypoints.xy  # [num_people, num_keypoints, 2]
        conf_list = result.keypoints.conf  # [num_people, num_keypoints]

        for idx, (keypoints, confs) in enumerate(zip(keypoints_list, conf_list)):
            row = [frame_number, idx]  # frame, person_id

            for (x, y), c in zip(keypoints.cpu().numpy(), confs.cpu().numpy()):
                row += [round(x, 2), round(y, 2), round(c, 2)]

            csv_writer.writerow(row)

    # Tampilkan frame dengan skeleton
    cv2.imshow("YOLO Pose Estimation", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# Cleanup
cap.release()
csv_file.close()
cv2.destroyAllWindows()
