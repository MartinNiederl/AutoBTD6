import os

import cv2
import numpy as np
import pyautogui

os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
import keras

ocr_model = keras.models.load_model('btd6_ocr_net.h5')


def custom_ocr(img, resolution=pyautogui.size()):
    h = img.shape[0]
    w = img.shape[1]

    white = np.array([255, 255, 255])
    black = np.array([0, 0, 0])

    for y in range(0, h):
        for x in range(0, w):
            if not (img[y][x] == white).all():
                img[y][x] = black

    gray_img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    thresh_img = cv2.threshold(gray_img, 60, 255, cv2.THRESH_BINARY)[1]
    contours, _ = cv2.findContours(thresh_img.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    char_images = []

    for contour in contours:
        # TODO: isn't this wrong?
        min_x = contour[0][0][0]
        min_y = contour[0][0][1]
        max_x = contour[0][0][0]
        max_y = contour[0][0][1]

        for point in contour:
            if point[0][0] < min_x:
                min_x = point[0][0]
            if point[0][0] > max_x:
                max_x = point[0][0]
            if point[0][1] < min_y:
                min_y = point[0][1]
            if point[0][1] > max_y:
                max_y = point[0][1]

        char_img = img[min_y:max_y, min_x:max_x]

        if char_img.shape[0] >= 25 * resolution[0] / 2560 and char_img.shape[0] <= 60 * resolution[0] / 2560 and char_img.shape[1] >= 14 * resolution[1] / 1440 and char_img.shape[1] <= 40 * resolution[1] / 1440:
            char_img = cv2.resize(char_img, (50, 50))
            char_img = cv2.copyMakeBorder(char_img, 5, 5, 5, 5, cv2.BORDER_CONSTANT, value=(0, 0, 0))
            char_img = char_img[:, :, 0]

            for y in range(0, 60):
                for x in range(0, 60):
                    char_img[y][x] = int(char_img[y][x] / 255)

            char_images.append([min_x, char_img])

    char_images.sort(key=lambda item: item[0])
    # ignore entries after gap(e. g. explosion particles)
    filtered_char_images = []
    current_x = 0

    for entry in char_images:
        if current_x + 50 >= entry[0]:
            current_x = entry[0]
            filtered_char_images.append(entry)

    if len(filtered_char_images) == 0:
        return '-1'

    char_images = list(map(lambda item: item[1], filtered_char_images))
    char_images = np.array(char_images)

    predictions = ocr_model.predict(char_images, verbose=0)

    number = ''

    for prediction in predictions:
        value = np.argmax_(prediction)
        if value == 10:
            number += '/'
        else:
            number += str(value)

    return number
