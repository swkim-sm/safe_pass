# import the necessary packages
from tensorflow.keras.applications.mobilenet_v2 import preprocess_input
from tensorflow.keras.preprocessing.image import img_to_array
from tensorflow.keras.models import load_model
from imutils.video import VideoStream
import numpy as np
import argparse
import imutils
import time
import cv2
import os
from yolo import YOLO
import serial

from face_detection import *
from buttonUI import *
from hand_detection import *

# construct the argument parser and parse the arguments
ap = argparse.ArgumentParser()
ap.add_argument("-f", "--face", type=str, default="face_detector", help="path to face detector model directory")
ap.add_argument("-m", "--model", type=str, default="mask_detector.model",
                help="path to trained face mask detector model")
ap.add_argument("-c", "--confidence", type=float, default=0.5, help="minimum probability to filter weak detections")
ap.add_argument('-n', '--network', default="tiny", help='Network Type: normal / tiny / prn')
ap.add_argument('-d', '--device', default=0, help='Device to use')
ap.add_argument('-s', '--size', default=416, help='Size for yolo')
ap.add_argument('-hc', '--handconfidence', default=0.2, help='Confidence for yolo')
args = vars(ap.parse_args())
# args = ap.parse_args()

if args["network"] == "normal":
    print("loading yolo...")
    yolo = YOLO("models/cross-hands.cfg", "models/cross-hands.weights", ["hand"])
elif args["network"] == "prn":
    print("loading yolo-tiny-prn...")
    yolo = YOLO("models/cross-hands-tiny-prn.cfg", "models/cross-hands-tiny-prn.weights", ["hand"])
else:
    print("loading yolo-tiny...")
    yolo = YOLO("models/cross-hands-tiny.cfg", "models/cross-hands-tiny.weights", ["hand"])
yolo.size = int(args["size"])
yolo.confidence = float(args["handconfidence"])

# load our serialized face detector model from disk
print("[INFO] loading face detector model...")
prototxtPath = os.path.sep.join([args["face"], "deploy.prototxt"])
weightsPath = os.path.sep.join([args["face"],
                                "res10_300x300_ssd_iter_140000.caffemodel"])
faceNet = cv2.dnn.readNet(prototxtPath, weightsPath)

# load the face mask detector model from disk
print("[INFO] loading face mask detector model...")
maskNet = load_model(args["model"])

# initialize the video stream and allow the camera sensor to warm up
print("[INFO] starting video stream...")
vs = VideoStream(src=0).start()
time.sleep(2.0)

# loop over the frames from the video stream
wearing_mask = False
motion_end = False
mask_flag = False
prev_btn = -1

# logo image
logo_img = cv2.imread("logo.png")
# I want to put logo on top-left corner, So I create a ROI
rows, cols, channels = logo_img.shape
# Now create a mask of logo and create its inverse mask also
img2gray = cv2.cvtColor(logo_img, cv2.COLOR_BGR2GRAY)
ret, logo_mask = cv2.threshold(img2gray, 10, 255, cv2.THRESH_BINARY)
mask_inv = cv2.bitwise_not(logo_mask)

# led, fan, belt button off : 0 / on : 1
current_status = [0, 0, 0]

# arduino board
arduino = True
#ser = serial.Serial('/dev/ttyACM0', 9600, timeout=1)
if arduino:
    ser = serial.Serial('COM6', 115200, timeout=1)
# ser.open()

# flag for clicking button
before_area = 0
click_check_ratio = 1.4

system_width = GetSystemMetrics(0)
system_height = GetSystemMetrics(1)

w_h_ratio = system_height/system_width

system_width_ = int(system_width/3)
system_height_ = int(system_width_*w_h_ratio)

keyboard_x = int(system_width*3/5)
keyboard_y = 0

keyboard_x_ = int(system_width_*3/5)
keyboard_y_ = 0

hand_count = 0

while True:
    frame = vs.read()
    frame = cv2.resize(frame, dsize=(int(system_width), int(system_height)), interpolation=cv2.INTER_LINEAR)
    frame_ = cv2.resize(frame, dsize=(system_width_, system_height_), interpolation=cv2.INTER_AREA)
    frame = cv2.flip(frame, 1)
    frame_ = cv2.flip(frame_, 1)
    # mask 미착용 또는 확인 단계
    if not wearing_mask:
        (locs, preds) = detect_and_predict_mask(frame_, faceNet, maskNet, args)

        for (box, pred) in zip(locs, preds):
            (startX, startY, endX, endY) = box
            (mask, withoutMask) = pred

            label = "Mask" if mask > withoutMask else "No Mask"
            color = (0, 255, 0) if label == "Mask" else (0, 0, 255)

            if label == "Mask" and not mask_flag:  # 마스크 착용 시간 재기
                mask_flag = True
                start = time.time()
            elif label == "Mask":  # 2초간 마스크 확인
                during = time.time() - start
                cv2.putText(frame, "checking : " + str(during), (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                if during > 2:
                    wearing_mask = True
                    mask_flag = False
            else:  # 마스크 미착용 시 경고 문구
                cv2.putText(frame, "Please wear a MASK!!!", (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 2.5, (0, 0, 255), 2)
                mask_flag = False

            label = "{}: {:.2f}%".format(label, max(mask, withoutMask) * 100)
            cv2.putText(frame, label, (startX*3, startY*3 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
            cv2.rectangle(frame, (startX*3, startY*3), (endX*3, endY*3), color, 2)

    # mask 착용 확인 후 virtual keyboard 조작 단계
    else:
        # keyboard 생성
        keyboard_roi = frame[0:int(system_height), keyboard_x:int(system_width)]
        keyboard_roi_ = frame_[0:int(system_height/3), keyboard_x_:int(system_width/3)]


        click_flag = False

        width, height, inference_time, results = yolo.inference(keyboard_roi_)
        center, area = hand_detection(keyboard_roi_, keyboard_roi, results, args)

        btn_list = []

        # cv2.putText(frame, "Please select a device to operate", (100, 100), cv2.FONT_HERSHEY_SIMPLEX, 2.5, (255, 255, 255), 2)
        color_white = (255, 255, 255)
        color_gray = (200, 200, 200, 50)

        keyboard_unit = int((system_width - keyboard_x)/11)
        keyboard_unit_y = int(system_height/17)
        keyboard_width = keyboard_unit*4
        keyboard_height = keyboard_unit_y*3

        if prev_btn == 0:
            btn_LED = make_button(frame, keyboard_x + keyboard_unit, keyboard_unit_y*3, keyboard_width, keyboard_height, color_white, "LED", True)
            btn_FAN = make_button(frame,keyboard_x + keyboard_unit, keyboard_unit_y*7, keyboard_width, keyboard_height, color_gray, "FAN", False)
            btn_BELT = make_button(frame,keyboard_x + keyboard_unit, keyboard_unit_y*11, keyboard_width, keyboard_height, color_gray, "BELT", False)
            btn_ON = make_button(frame,keyboard_x + keyboard_unit*2 + keyboard_width, keyboard_unit_y*3, keyboard_width, keyboard_height,  color_white,"ON", False)
            btn_OFF = make_button(frame,keyboard_x + keyboard_unit*2 + keyboard_width, keyboard_unit_y*7, keyboard_width, keyboard_height,  color_white,"OFF", False)
            btn_END = make_button(frame,keyboard_x + keyboard_unit*2 + keyboard_width, keyboard_unit_y*11, keyboard_width, keyboard_height,  color_white,"END", False)
        elif prev_btn == 1:
            btn_LED = make_button(frame,keyboard_x + keyboard_unit, keyboard_unit_y*3, keyboard_width, keyboard_height, color_gray,"LED", False)
            btn_FAN = make_button(frame,keyboard_x + keyboard_unit, keyboard_unit_y*7, keyboard_width, keyboard_height, color_white,"FAN", True)
            btn_BELT = make_button(frame,keyboard_x + keyboard_unit, keyboard_unit_y*11, keyboard_width, keyboard_height, color_gray,"BELT", False)
            btn_ON = make_button(frame,keyboard_x + keyboard_unit*2 + keyboard_width, keyboard_unit_y*3, keyboard_width, keyboard_height,  color_white,"ON", False)
            btn_OFF = make_button(frame,keyboard_x + keyboard_unit*2 + keyboard_width, keyboard_unit_y*7, keyboard_width, keyboard_height,  color_white,"OFF", False)
            btn_END = make_button(frame,keyboard_x + keyboard_unit*2 + keyboard_width, keyboard_unit_y*11, keyboard_width, keyboard_height,  color_white,"END", False)
        elif prev_btn == 2:
            btn_LED = make_button(frame,keyboard_x + keyboard_unit, keyboard_unit_y*3, keyboard_width, keyboard_height, color_gray,"LED", False)
            btn_FAN = make_button(frame,keyboard_x + keyboard_unit, keyboard_unit_y*7, keyboard_width, keyboard_height, color_gray,"FAN", False)
            btn_BELT = make_button(frame,keyboard_x + keyboard_unit, keyboard_unit_y*11, keyboard_width, keyboard_height, color_white,"BELT", True)
            btn_ON = make_button(frame,keyboard_x + keyboard_unit*2 + keyboard_width, keyboard_unit_y*3, keyboard_width, keyboard_height,  color_white, "ON", False)
            btn_OFF = make_button(frame,keyboard_x + keyboard_unit*2 + keyboard_width, keyboard_unit_y*7, keyboard_width, keyboard_height,  color_white, "OFF", False)
            btn_END = make_button(frame,keyboard_x + keyboard_unit*2 + keyboard_width, keyboard_unit_y*11, keyboard_width, keyboard_height,  color_white, "END", False)
        else:
            btn_LED = make_button(frame,keyboard_x + keyboard_unit, keyboard_unit_y*3, keyboard_width, keyboard_height, color_white, "LED", False)
            btn_FAN = make_button(frame,keyboard_x + keyboard_unit, keyboard_unit_y*7, keyboard_width, keyboard_height, color_white, "FAN", False)
            btn_BELT = make_button(frame,keyboard_x + keyboard_unit, keyboard_unit_y*11, keyboard_width, keyboard_height, color_white, "BELT", False)
            btn_ON = make_button(frame,keyboard_x + keyboard_unit*2 + keyboard_width, keyboard_unit_y*3, keyboard_width, keyboard_height, color_gray, "ON", False)
            btn_OFF = make_button(frame,keyboard_x + keyboard_unit*2 + keyboard_width, keyboard_unit_y*7, keyboard_width, keyboard_height, color_gray, "OFF", False)
            btn_END = make_button(frame,keyboard_x + keyboard_unit*2 + keyboard_width, keyboard_unit_y*11, keyboard_width, keyboard_height, color_white, "END", False)

        btn_list.append(btn_LED)
        btn_list.append(btn_FAN)
        btn_list.append(btn_BELT)
        btn_list.append(btn_ON)
        btn_list.append(btn_OFF)
        btn_list.append(btn_END)


        # 손 면적 여부를 통한 클릭 여부 확인
        if (area >= int(before_area * click_check_ratio)):  # 클릭 후 손 펴는 동작으로 면적이 커졌을 시
            click_flag = True

        if click_flag:  # 클릭 발생 시
            for btn in range(0, len(btn_list)):
                if check_ROI(center, btn_list[btn]):
                    make_button(frame, btn_list[btn][0], btn_list[btn][1], btn_list[btn][2] - btn_list[btn][0],
                                btn_list[btn][3] - btn_list[btn][1], color_white, btn_list[btn][4], True)
                    if (btn in (0, 1, 2)):
                        prev_btn = btn
                    elif btn == 5:
                        wearing_mask = False
                    else:
                        # on 버튼
                        if btn == 3:
                            if current_status[prev_btn] == 0:
                                current_status[prev_btn] = 1
                                print(prev_btn * 2 + 1)
                                if arduino:
                                    text = str(prev_btn * 2 + 1)
                                    text = bytes(text, 'utf-8')
                                    ser.write(text)

                        # off 버튼
                        else:
                            if current_status[prev_btn] == 1:
                                current_status[prev_btn] = 0
                                print(prev_btn * 2 + 2)
                                if arduino:
                                    text = str(prev_btn * 2 + 2)
                                    text = bytes(text, 'utf-8')
                                    ser.write(text)


        before_area = area
        click_flag = False

    # logo
    #keyboard_unit = int((system_width - keyboard_x)/11)
    #roi = frame[keyboard_unit:rows + keyboard_unit, keyboard_x-int(keyboard_unit/5):cols + keyboard_x-int(keyboard_unit/5)]
    # Now black-out the area of logo in ROI
    #img1_bg = cv2.bitwise_and(roi, roi, mask=mask_inv)
    # Take only region of logo from logo image.
    #img2_fg = cv2.bitwise_and(logo_img, logo_img, mask=logo_mask)
    # Put logo in ROI and modify the main image
    #dst = cv2.add(img1_bg, img2_fg)
    #frame[keyboard_unit:rows + keyboard_unit, keyboard_x-int(keyboard_unit/5):cols + keyboard_x-int(keyboard_unit/5)] = dst

    # show the output frame and break the loop by button 'q'
    cv2.imshow("Frame", frame)
    cv2.imshow("Frame2", frame_)

    key = cv2.waitKey(1) & 0xFF
    if key == ord("q"):
        break
    elif key == ord("r"):
        wearing_mask = False
        motion_end = False
        mask_flag = False
        current_status = [0, 0, 0]
        prev_btn = -1

# do a bit of cleanup
cv2.destroyAllWindows()
vs.stop()
