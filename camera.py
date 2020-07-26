# -*- coding: utf-8 -*

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
import math


def region_of_interest(img, vertices, color3=(255, 255, 255), color1=255):  # ROI 셋팅
    mask = np.zeros_like(img)  # mask = img와 같은 크기의 빈 이미지
    if len(img.shape) > 2:  # Color 이미지(3채널)라면 :
        color = color3
    else:  # 흑백 이미지(1채널)라면 :
        color = color1

    # vertices에 정한 점들로 이뤄진 다각형부분(ROI 설정부분)을 color로 채움
    cv2.fillPoly(mask, np.array([vertices], dtype=np.int32), color)
    # 이미지와 color로 채워진 ROI를 합침
    ROI_image = cv2.bitwise_and(img, mask)
    return ROI_image


# Skin detect and Noise reduction
def detectSkin(original):
    # Color binarization
    ycbcr = cv2.cvtColor(src=original, code=cv2.COLOR_RGB2YCrCb)
    lower = np.array([0, 85, 135])
    upper = np.array([255, 135, 180])
    mask = cv2.inRange(ycbcr, lower, upper)

    # Noise reduction - Median Filter
    mask = cv2.medianBlur(src=mask, ksize=7)
    element = cv2.getStructuringElement(shape=cv2.MORPH_RECT, ksize=(7, 7))
    mask = cv2.morphologyEx(src=mask, op=cv2.MORPH_CLOSE, kernel=element)
    mask = cv2.morphologyEx(src=mask, op=cv2.MORPH_OPEN, kernel=element)
    return mask


# 점 a1,a2를 잇는 직선과 점 b1,b2를 잇는 직선 사이의 각 반환
def getAngle(a1, a2, b1, b2):
    dx1 = a1[0] - a2[0]
    dy1 = a1[1] - a2[1]
    dx2 = b1[0] - b2[0]
    dy2 = b1[1] - b2[1]

    rad = math.atan2(dy1*dx2 - dx1 * dy2, dx1*dx2 + dy1 * dy2)
    pi = math.acos(-1)
    degree = (rad * 180) / pi
    return abs(degree)


# 벡터 안 요소들의 분산을 반환
def getVariance(v, mean):
    result = 0
    size = len(v)
    for i in range(size):
        diff = mean - v[i]
        result += (diff*diff)
    result /= size
    return result


# 손가락 개수와 손가락 사이 각을 이용한 제스쳐 인식
def getHandGesture(points):
    fingerCount = len(points) - 1
    result = ""
    if fingerCount == 0:
        result = "Rock"  # 주먹
    elif fingerCount == 1:
        result = "One"  # 손가락 하나
    elif fingerCount == 2:
        result = "Two"  # 손가락 둘
    elif fingerCount == 3:
        result = "Three"
    elif fingerCount == 4:
        result = "Four"
    elif fingerCount == 5:
        result = "Five"
    return result


# Find out and draw Hand Gesture
def drawHandGesture(frame, mask):
    font = cv2.FONT_HERSHEY_COMPLEX
    fontScale = 1
    color = (0, 255, 255)
    thickness = 1

    contours, hierarchy = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in contours:
        # 객체 외곽선 그리기
        cv2.drawContours(frame, [cnt], 0, (255, 0, 0), 3)  # blue

        # 손바닥 중심과 반지름 찾기
        (x, y), radius = cv2.minEnclosingCircle(cnt)
        scale = 0.7
        center = (int(x), int(y))
        radius = int(radius)
        cv2.circle(frame, center, 2, (0, 255, 0), -1)
        cv2.circle(frame, center, int(radius*scale), (0, 255, 0), 2)

        # 손가락 개수를 세기 위한 원 그리기
        cImg = np.zeros(mask.shape, np.uint8)
        cv2.circle(cImg, center, int(radius*scale), 255)

        # 원의 외곽선을 저장할 벡터
        circleContours, hierarchy = cv2.findContours(cImg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # 원의 외곽선을 따라 돌며 mask의 값이 0에서 1로 바뀌는 지점 확인
        points = []
        for i in reversed(range(1, len(circleContours[0]))):
            p1 = (circleContours[0][i][0][0], circleContours[0][i][0][1])
            p2 = (circleContours[0][i-1][0][0], circleContours[0][i-1][0][1])
            if mask[p1[1], p1[0]] == 0 and mask[p2[1], p2[0]] > 1:
                points.append(p1)

        # 손가락 마디(선) 그리기
        for i in range(len(points)):
            cv2.line(frame, center, points[i], (0, 255, 0), 3)

        # 제스처 출력
        text = getHandGesture(points)
        cv2.putText(frame, text, center, font, fontScale, color, thickness)

    return frame


def detect_and_predict_mask(frame, faceNet, maskNet):
    # grab the dimensions of the frame and then construct a blob
    # from it
    (h, w) = frame.shape[:2]
    blob = cv2.dnn.blobFromImage(frame, 1.0, (300, 300),
        (104.0, 177.0, 123.0))

    # pass the blob through the network and obtain the face detections
    faceNet.setInput(blob)
    detections = faceNet.forward()

    # initialize our list of faces, their corresponding locations,
    # and the list of predictions from our face mask network
    faces = []
    locs = []
    preds = []

    # loop over the detections
    for i in range(0, detections.shape[2]):
        # extract the confidence (i.e., probability) associated with
        # the detection
        confidence = detections[0, 0, i, 2]

        # filter out weak detections by ensuring the confidence is
        # greater than the minimum confidence
        if confidence > args["confidence"]:
            # compute the (x, y)-coordinates of the bounding box for
            # the object
            box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
            (startX, startY, endX, endY) = box.astype("int")

            # ensure the bounding boxes fall within the dimensions of
            # the frame
            (startX, startY) = (max(0, startX), max(0, startY))
            (endX, endY) = (min(w - 1, endX), min(h - 1, endY))

            # extract the face ROI, convert it from BGR to RGB channel
            # ordering, resize it to 224x224, and preprocess it
            face = frame[startY:endY, startX:endX]
            face = cv2.cvtColor(face, cv2.COLOR_BGR2RGB)
            face = cv2.resize(face, (224, 224))
            face = img_to_array(face)
            face = preprocess_input(face)

            # add the face and bounding boxes to their respective
            # lists
            faces.append(face)
            locs.append((startX, startY, endX, endY))

    # only make a predictions if at least one face was detected
    if len(faces) > 0:
        # for faster inference we'll make batch predictions on *all*
        # faces at the same time rather than one-by-one predictions
        # in the above `for` loop
        faces = np.array(faces, dtype="float32")
        preds = maskNet.predict(faces, batch_size=32)

    # return a 2-tuple of the face locations and their corresponding
    # locations
    return (locs, preds)


# construct the argument parser and parse the arguments
ap = argparse.ArgumentParser()
ap.add_argument("-f", "--face", type=str,
    default="face_detector",
    help="path to face detector model directory")
ap.add_argument("-m", "--model", type=str,
    default="mask_detector.model",
    help="path to trained face mask detector model")
ap.add_argument("-c", "--confidence", type=float, default=0.5,
    help="minimum probability to filter weak detections")
args = vars(ap.parse_args())

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
mask_loop = False
hand_loop = False
while True:
    # -------- | 영상 입력 받기 | ------------------------------------------------------
    # grab the frame from the threaded video stream and resize it
    # to have a maximum width of 400 pixels
    frame = vs.read()
    frame = imutils.resize(frame, 1000)
    frame = cv2.flip(frame, 1)

    # -------- | 얼굴-마스크 인식 | ----------------------------------------------------
    # 얼굴 ROI
    face_start_x, face_end_x = 300, 700
    face_start_y, face_end_y = 100, 600
    vertices = [[face_start_x, face_start_y], [face_end_x, face_start_y], [face_end_x, face_end_y], [face_start_x, face_end_y]]
    frame_face = region_of_interest(frame, vertices, color3=(255, 255, 255), color1=255)

    # detect faces in the frame and determine if they are wearing a
    # face mask or not
    (locs, preds) = detect_and_predict_mask(frame_face, faceNet, maskNet)

    # loop over the detected face locations and their corresponding
    # locations
    mask_flag = False
    for (box, pred) in zip(locs, preds):
        # unpack the bounding box and predictions
        (startX, startY, endX, endY) = box
        (mask, withoutMask) = pred

        # determine the class label and color we'll use to draw
        # the bounding box and text
        label = "Mask" if mask > withoutMask else "No Mask"
        color = (0, 255, 0) if label == "Mask" else (0, 0, 255)
        if mask > withoutMask:
            mask_flag = True
        # include the probability in the label
        label = "{}: {:.2f}%".format(label, max(mask, withoutMask) * 100)

        # display the label and bounding box rectangle on the output
        # frame
        cv2.putText(frame, label, (startX, startY - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 2)
        cv2.rectangle(frame, (startX, startY), (endX, endY), color, 2)
    # 시간 구하기
    if mask_flag:
        if not mask_loop:
            mask_loop = True
            start = time.time()
        else:
            during = time.time() - start
            cv2.putText(frame, str(during), (startX, startY + 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 2)
            if during > 3:
                mask_loop = False
                hand_loop = True
    else:
        mask_loop = False

    # -------- | 모션 인식 - 왼손 & 오른손 | ------------------------------------------------
    # 손 ROI
    left_start_x, left_end_x = 10, 330
    left_start_y, left_end_y = 300, 700
    right_start_x, right_end_x = 670, 990
    right_start_y, right_end_y = 300, 700
    vertices_left = [[left_start_x, left_start_y], [left_end_x, left_start_y], [left_end_x, left_end_y], [left_start_x, left_end_y]]
    vertices_right = [[right_start_x, right_start_y], [right_end_x, right_start_y], [right_end_x, right_end_y], [right_start_x, right_end_y]]
    frame_hand_left = region_of_interest(frame, vertices_left, color3=(255, 255, 255), color1=255)
    frame_hand_right = region_of_interest(frame, vertices_right, color3=(255, 255, 255), color1=255)
    # Skin detect and Noise reduction
    mask_left = detectSkin(frame_hand_left)
    mask_right = detectSkin(frame_hand_right)
    # Find out and Draw Hand Gesture
    frame = drawHandGesture(frame, mask_left)
    frame = drawHandGesture(frame, mask_right)

    # -------- | ROI 영역 그리기 | ----------------------------------------------------------
    frame = cv2.rectangle(frame, (300, 100), (700, 600), (255, 255, 0), 3)
    frame = cv2.rectangle(frame, (10, 300), (330, 700), (255, 255, 0), 3)
    frame = cv2.rectangle(frame, (670, 300), (990, 700), (255, 255, 0), 3)

    # -------- | 영상 출력 | ----------------------------------------------------------------
    # show the output frame
    cv2.imshow("Frame", frame)
    key = cv2.waitKey(1) & 0xFF

    # if the `q` key was pressed, break from the loop
    if key == ord("q"):
        break

# do a bit of cleanup
cv2.destroyAllWindows()
vs.stop()
