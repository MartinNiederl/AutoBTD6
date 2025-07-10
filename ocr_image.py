import sys
from os.path import exists

import cv2
import numpy as np

from ocr import custom_ocr
from replay import get_resolution_dependent_data

argv = np.array(sys.argv)
if len(argv) < 2:
    print('Usage: py ' + argv[0] + ' <filename>')
    exit()
if not str(argv[1]).endswith('.png'):
    print('Format must be .png!')
    exit()
if not exists(argv[1]):
    print('Image not found!')
    exit()

img = cv2.imread(argv[1])

h = img.shape[0]
w = img.shape[1]

data = get_resolution_dependent_data((w, h))
segment_coordinates = data['segmentCoordinates']

images = [
    img[
        segment_coordinates[segment][1] : segment_coordinates[segment][3],
        segment_coordinates[segment][0] : segment_coordinates[segment][2],
    ]
    for segment in segment_coordinates
]

print(f'detected value: {custom_ocr(images[2], resolution=(w, h))}')

cv2.imwrite(str(argv[1]).replace('.png', '_area.png'), images[2])
