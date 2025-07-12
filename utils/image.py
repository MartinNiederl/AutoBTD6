import cv2
import numpy as np

type RawImage = np.ndarray
type BoundingBox = tuple[int, int, int, int]  # (x1, y1, x2, y2), inclusive, x=columns, y=rows


def cut_image(img: RawImage, area: BoundingBox) -> RawImage:
    return np.array(img[area[1] : (area[3] + 1), area[0] : (area[2]) + 1])


def image_areas_equal(img_a: RawImage, img_b: RawImage, area: BoundingBox) -> bool:
    return (cut_image(img_a, area) == cut_image(img_b, area)).all()


def sub_img_equal_img_area(img: RawImage, sub_img: RawImage, area: BoundingBox) -> bool:
    return (cut_image(img, area) == sub_img).all()


def find_image_in_image(img: RawImage, sub_img: RawImage) -> tuple[int, int]:
    result = cv2.matchTemplate(img, sub_img, cv2.TM_SQDIFF_NORMED)
    return [cv2.minMaxLoc(result)[i] for i in [0, 2]]
