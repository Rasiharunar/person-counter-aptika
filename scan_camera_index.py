import cv2

print("Scanning available camera indexes (0-10)...")

available = []
for idx in range(11):
    cap = cv2.VideoCapture(idx)
    if cap is not None and cap.isOpened():
        print(f"Camera found at index {idx}")
        available.append(idx)
        cap.release()
    else:
        print(f"No camera at index {idx}")

if available:
    print(f"\nAvailable camera indexes: {available}")
else:
    print("\nNo cameras detected.")
