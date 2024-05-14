# TODO: document code
# TODO: webp?

# This module is derived from https://github.com/LingDong-/linedraw, by
# Lingdong Huang.

import os
import json
import time
import math
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageOps

# constants
EXPORT_PATH = "images/out.svg"
SVG_FOLDER = "images/"
JSON_FOLDER = "images/"
NO_CV_MODE = False

# Ensure directories exist
os.makedirs(SVG_FOLDER, exist_ok=True)
os.makedirs(JSON_FOLDER, exist_ok=True)

try:
    import numpy as np
    import cv2
except ImportError as import_error:
    print(f"ImportError: {import_error}")
    print("Unable to import numpy/openCV. Switching to NO_CV mode.")
    NO_CV_MODE = True


# -------------- output functions --------------


def image_to_json(
    image_filename,
    resolution=1024,
    draw_contours=False,
    repeat_contours=1,
    draw_hatch=False,
    repeat_hatch=1,
):

    lines = vectorise(
        image_filename,
        resolution,
        draw_contours,
        repeat_contours,
        draw_hatch,
        repeat_hatch,
    )

    pure_filename = Path(image_filename).stem

    filename = filename = Path(JSON_FOLDER) / f"{pure_filename}.json"
    lines_to_file(lines, filename)


def make_svg(lines):
    print("Generating SVG file...")
    width = math.ceil(max([max([p[0] * 0.5 for p in l]) for l in lines]))
    height = math.ceil(max([max([p[1] * 0.5 for p in l]) for l in lines]))
    out = f'<svg xmlns="http://www.w3.org/2000/svg" height="{height}px" width="{width}px" version="1.1">'
    out += "".join(
        f'<polyline points="{",".join(f"{p[0] * 0.5},{p[1] * 0.5}" for p in l)}" '
        'stroke="black" stroke-width="1" fill="none" />\n'
        for l in lines
    )
    out += "</svg>"
    return out


# we can use turtle graphics to visualise how a set of lines will be drawn
def draw(lines):
    from tkinter import Tk
    from turtle import Canvas, RawTurtle, TurtleScreen

    # set up the environment
    root = Tk()
    canvas = Canvas(root, width=800, height=800)
    canvas.pack()

    s = TurtleScreen(canvas)
    t = RawTurtle(canvas)
    t.speed(0)
    t.width(1)

    for line in lines:
        x, y = line[0]
        t.up()
        t.goto(x * 800 / 1024 - 400, -(y * 800 / 1024 - 400))
        for point in line:
            t.down()
            t.goto(point[0] * 800 / 1024 - 400, -(point[1] * 800 / 1024 - 400))

    s.mainloop()


# -------------- conversion control --------------
def resize_image(image, resolution, draw_option, h, w):
    return image.resize(
        (int(resolution / draw_option), int(resolution / draw_option * h / w))
    )


def vectorise(
    image_filename,
    resolution=1024,
    draw_contours=False,
    repeat_contours=1,
    draw_hatch=False,
    repeat_hatch=1,
):

    image = None
    possible_paths = [
        Path(image_filename),
        Path("images") / image_filename,
        Path("images") / f"{image_filename}.jpg",
        Path("images") / f"{image_filename}.jpeg",
        Path("images") / f"{image_filename}.png",
        Path("images") / f"{image_filename}.tif",
        Path("images") / f"{image_filename}.tiff",
        Path("images") / f"{image_filename}.webp",
    ]

    for p in possible_paths:
        try:
            image = Image.open(p)
            break
        except Exception:
            pass
    else:
        raise FileNotFoundError(f"Image file not found: {image_filename}")

    w, h = image.size

    # convert the image to greyscale and max contrast
    image = ImageOps.autocontrast(image.convert("L"), 10)
    lines = []

    with ThreadPoolExecutor() as executor:
        if draw_contours:
            image_resized = resize_image(image, resolution, draw_contours, h, w)
            contours = executor.submit(
                get_contours, image_resized, draw_contours
            ).result()
            lines += contours * repeat_contours

        if draw_hatch:
            image_resized = resize_image(image, resolution, draw_hatch, h, w)
            hatches = executor.submit(hatch, image_resized, draw_hatch).result()
            lines += hatches * repeat_hatch
    pure_filename = Path(image_filename).stem

    with open(Path(SVG_FOLDER) / f"{pure_filename}.svg", "w") as f:
        f.write(make_svg(lines))

    segments = sum(len(line) for line in lines)
    print(f"{len(lines)} strokes, {segments} points. Done.")
    return lines


# -------------- vectorisation options --------------


def get_contours(image, draw_contours=2):
    print("Generating contours...")
    image = find_edges(image)
    IM1 = np.array(image)
    IM2 = np.rot90(IM1, 3)
    IM2 = np.flip(IM2, axis=1)

    dots1 = get_dots(IM1)
    dots2 = get_dots(IM2)
    contours1 = connect_dots(dots1)
    contours2 = connect_dots(dots2)

    for i in range(len(contours2)):
        contours2[i] = [(c[1], c[0]) for c in contours2[i]]
    contours = contours1 + contours2

    for i in range(len(contours)):
        for j in range(len(contours)):
            if len(contours[i]) > 0 and len(contours[j]) > 0:
                if dist_sum(contours[j][0], contours[i][-1]) < 8:
                    contours[i] = contours[i] + contours[j]
                    contours[j] = []

    for i in range(len(contours)):
        contours[i] = [contours[i][j] for j in range(0, len(contours[i]), 8)]

    contours = [c for c in contours if len(c) > 1]

    for i in range(len(contours)):
        contours[i] = [
            (v[0] * draw_contours, v[1] * draw_contours) for v in contours[i]
        ]

    return contours


# hatching
def hatch(image, draw_hatch=16):

    t0 = time.time()

    print("Hatching using hatch()...")
    pixels = image.load()
    w, h = image.size
    horizontal_lines = []
    diagonal_lines = []
    for x0 in range(w):
        for y0 in range(h):
            x = x0 * draw_hatch
            y = y0 * draw_hatch

            # don't hatch above a certain level of brightness
            if pixels[x0, y0] > 144:
                pass

            # above 64, draw horizontal lines
            elif pixels[x0, y0] > 64:
                horizontal_lines.append(
                    [(x, y + draw_hatch / 4), (x + draw_hatch, y + draw_hatch / 4)]
                )

            # above 16, draw diagonal lines also
            elif pixels[x0, y0] > 16:
                horizontal_lines.append(
                    [(x, y + draw_hatch / 4), (x + draw_hatch, y + draw_hatch / 4)]
                )
                diagonal_lines.append([(x + draw_hatch, y), (x, y + draw_hatch)])

            # below 16, draw diagonal lines and a second horizontal line
            else:
                horizontal_lines.append(
                    [(x, y + draw_hatch / 4), (x + draw_hatch, y + draw_hatch / 4)]
                )  # horizontal lines
                horizontal_lines.append(
                    [
                        (x, y + draw_hatch / 2 + draw_hatch / 4),
                        (x + draw_hatch, y + draw_hatch / 2 + draw_hatch / 4),
                    ]
                )  # horizontal lines with additional offset
                diagonal_lines.append(
                    [(x + draw_hatch, y), (x, y + draw_hatch)]
                )  # diagonal lines, left

    t1 = time.time()

    print("Wrangling points...")

    # Make segments into lines
    line_groups = [horizontal_lines, diagonal_lines]

    for line_group in line_groups:
        line_group = [
            [
                (
                    line1 + line2[1:]
                    if line1 and line2 and line1[-1] == line2[0]
                    else line1
                )
                for line1, line2 in zip(line_group, line_group[1:])
            ]
            for _ in range(len(line_group))
        ]

        # in each line group keep any non-empty lines
        saved_lines = [[line[0], line[-1]] for line in line_group if line]
        line_group.clear()
        line_group.extend(saved_lines)

    lines = [item for group in line_groups for item in group]

    t2 = time.time()

    print(f"Hatching: {t1 - t0}")
    print(f"Wrangling: {t2 - t1}")
    print(f"Total: {t2 - t0}")

    return lines


# -------------- supporting functions for drawing contours --------------


def find_edges(image):
    print("Finding edges...")
    if NO_CV_MODE:
        apply_mask(image, [F_SOBEL_X, F_SOBEL_Y])
    else:
        im = np.array(image)
        im = cv2.GaussianBlur(im, (3, 3), 0)
        im = cv2.Canny(im, 100, 200)
        image = Image.fromarray(im)
    return image.point(lambda p: p > 128 and 255)


def get_dots(image):
    print("Getting contour points...")
    h, w = image.shape
    dots = []

    for y in range(h - 1):
        row = []
        for x in range(1, w):
            if image[y, x] == 255:
                if row and x - row[-1][0] == row[-1][1] + 1:
                    row[-1] = (row[-1][0], row[-1][1] + 1)
                else:
                    row.append((x, 0))
        dots.append(row)
    return dots


def connect_dots(dots):
    print("Connecting contour points...")
    contours = []
    for y, row in enumerate(dots):
        for x, v in row:
            if v > -1:
                if y == 0:
                    contours.append([(x, y)])
                else:
                    closest, closest_dist = min(
                        ((x0, v0) for x0, v0 in dots[y - 1]),
                        key=lambda point: abs(point[0] - x),
                        default=(None, None),
                    )
                    if closest is None or abs(closest - x) > 3:
                        contours.append([(x, y)])
                    else:
                        for contour in contours:
                            if contour[-1] == (closest, y - 1):
                                contour.append((x, y))
                                break
                        else:
                            contours.append([(x, y)])
    return contours


# -------------- optimisation for pen movement --------------


def sort_lines(lines):
    print("Optimizing stroke sequence...")
    sorted_lines = [lines.pop(0)]
    while lines:
        last_point = sorted_lines[-1][-1]
        closest_line = min(
            lines,
            key=lambda line: min(
                dist_sum(line[0], last_point), dist_sum(line[-1], last_point)
            ),
        )
        if dist_sum(closest_line[0], last_point) > dist_sum(
            closest_line[-1], last_point
        ):
            closest_line.reverse()
        sorted_lines.append(closest_line)
        lines.remove(closest_line)
    return sorted_lines


def lines_to_file(lines, filename):
    with open(filename, "w") as file_to_save:
        json.dump(lines, file_to_save, indent=4)


# -------------- helper functions --------------


def mid_point(*args):
    xs, ys = 0, 0
    for p in args:
        xs += p[0]
        ys += p[1]
    return xs / len(args), ys / len(args)


def dist_sum(*points):
    return sum(
        math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1])
        for i in range(1, len(points))
    )


# -------------- code used when open CV is not available  --------------


def apply_mask(IM, masks):
    px = IM.load()
    w, h = IM.size
    npx = {}
    for x in range(0, w):
        for y in range(0, h):
            a = [0] * len(masks)
            for i in range(len(masks)):
                for p in masks[i].keys():
                    if 0 < x + p[0] < w and 0 < y + p[1] < h:
                        a[i] += px[x + p[0], y + p[1]] * masks[i][p]
                if sum(masks[i].values()) != 0:
                    a[i] = a[i] / sum(masks[i].values())
            npx[x, y] = int(sum([v**2 for v in a]) ** 0.5)
    for x in range(0, w):
        for y in range(0, h):
            px[x, y] = npx[x, y]


# Constants for masking
F_BLUR = {
    (-2, -2): 2,
    (-1, -2): 4,
    (0, -2): 5,
    (1, -2): 4,
    (2, -2): 2,
    (-2, -1): 4,
    (-1, -1): 9,
    (0, -1): 12,
    (1, -1): 9,
    (2, -1): 4,
    (-2, 0): 5,
    (-1, 0): 12,
    (0, 0): 15,
    (1, 0): 12,
    (2, 0): 5,
    (-2, 1): 4,
    (-1, 1): 9,
    (0, 1): 12,
    (1, 1): 9,
    (2, 1): 4,
    (-2, 2): 2,
    (-1, 2): 4,
    (0, 2): 5,
    (1, 2): 4,
    (2, 2): 2,
}
F_SOBEL_X = {
    (-1, -1): 1,
    (0, -1): 0,
    (1, -1): -1,
    (-1, 0): 2,
    (0, 0): 0,
    (1, 0): -2,
    (-1, 1): 1,
    (0, 1): 0,
    (1, 1): -1,
}
F_SOBEL_Y = {
    (-1, -1): 1,
    (0, -1): 2,
    (1, -1): 1,
    (-1, 0): 0,
    (0, 0): 0,
    (1, 0): 0,
    (-1, 1): -1,
    (0, 1): -2,
    (1, 1): -1,
}
