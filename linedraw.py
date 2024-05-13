# TODO: figure out directory creation
# TODO: document code

# This module is derived from https://github.com/LingDong-/linedraw, by
# Lingdong Huang.

import argparse
import json
import math
from pathlib import Path
import random
import time

from PIL import Image, ImageDraw, ImageOps

# file constants
EXPORT_PATH = "images/out.svg"
SVG_FOLDER = "images/"
JSON_FOLDER = "images/"

# CV
no_cv = False

try:
    import numpy as np
    import cv2
except ImportError:
    print("Unable to import numpy/openCV. Switching to NO_CV mode.")
    no_cv = True


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

    filename = filename = (
        Path(JSON_FOLDER) / f"{pure_filename}.json"
    )  # may need str cast
    lines_to_file(lines, filename)


def make_svg(lines):
    print("Generating SVG file...")
    width = math.ceil(max([max([p[0] * 0.5 for p in l]) for l in lines]))
    height = math.ceil(max([max([p[1] * 0.5 for p in l]) for l in lines]))
    out = f'<svg xmlns="http://www.w3.org/2000/svg" height="{height}px" width="{width}px" version="1.1">'

    for l in lines:
        l = ",".join([str(p[0] * 0.5) + "," + str(p[1] * 0.5) for p in l])
        out += (
            '<polyline points="'
            + l
            + '" stroke="black" stroke-width="1" fill="none" />\n'
        )
    out += "</svg>"
    return out


# we can use turtle graphics to visualise how a set of lines will be drawn
def draw(lines):
    from tkinter import Tk, LEFT
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


def vectorise(
    image_filename,
    resolution=1024,
    draw_contours=False,
    repeat_contours=1,
    draw_hatch=False,
    repeat_hatch=1,
):

    image = None
    possible = [
        Path(image_filename),
        Path("images") / image_filename,
        Path("images") / f"{image_filename}.jpg",
        Path("images") / f"{image_filename}.jpeg",
        Path("images") / f"{image_filename}.png",
        Path("images") / f"{image_filename}.tif",
    ]

    for p in possible:
        try:
            image = Image.open(Path(p))
            break
        except FileNotFoundError:
            pass
    w, h = image.size

    # convert the image to greyscale
    image = image.convert("L")

    # maximise contrast
    image = ImageOps.autocontrast(image, 10)

    lines = []

    if draw_contours:
        contours = sort_lines(
            get_contours(
                image.resize(
                    (
                        int(resolution / draw_contours),
                        int(resolution / draw_contours * h / w),
                    )
                ),
                draw_contours,
            )
        )
        for r in range(repeat_contours):
            lines += contours

    if draw_hatch:
        hatches = sort_lines(
            hatch(
                # image,
                image.resize(
                    (int(resolution / draw_hatch), int(resolution / draw_hatch * h / w))
                ),
                draw_hatch,
            )
        )
        for r in range(repeat_hatch):
            lines += hatches

    pure_filename = Path(image_filename).stem

    with open(Path(SVG_FOLDER) / f"{pure_filename}.svg", "w") as f:
        f.write(make_svg(lines))

    segments = 0
    for line in lines:
        segments = segments + len(line)
    print(len(lines), "strokes,", segments, "points.")
    print("Done.")
    return lines


# -------------- vectorisation options --------------


def get_contours(image, draw_contours=2):
    print("Generating contours...")
    image = find_edges(image)
    IM1 = image.copy()
    IM2 = image.rotate(-90, expand=True).transpose(Image.FLIP_LEFT_RIGHT)
    dots1 = get_dots(IM1)
    contours1 = connect_dots(dots1)
    dots2 = get_dots(IM2)
    contours2 = connect_dots(dots2)

    for i in range(len(contours2)):
        contours2[i] = [(c[1], c[0]) for c in contours2[i]]
    contours = contours1 + contours2

    contours = [
        (
            contour1 + contour2
            if len(contour1) > 0
            and len(contour2) > 0
            and dist_sum(contour2[0], contour1[-1]) < 8
            else contour1
        )
        for contour1, contour2 in zip(contours, contours[1:])
    ]

    contours = [contour[::8] for contour in contours]

    contours = [c for c in contours if len(c) > 1]

    contours = [
        [(v[0] * draw_contours, v[1] * draw_contours) for v in contour]
        for contour in contours
    ]

    return contours


# improved, faster and easier to understand hatching
def hatch(image, draw_hatch=16):

    t0 = time.time()

    print("Hatching using hatch()...")
    pixels = image.load()
    w, h = image.size
    horizontal_lines = []
    diagonal_lines = []
    for x0 in range(w):
        # print("reading x", x0)
        for y0 in range(h):
            # print("    reading y", x0)
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

        # for lines in line_group:
        #     for lines2 in line_group:

        #         # do items exist in both?
        #         if lines and lines2:
        #             # if the last point of first is the same as the first point of of the second
        #             if lines[-1] == lines2[0]:
        #                 # then extend the first with all the rest of the points of the second
        #                 lines.extend(lines2[1:])
        #                 # and empty the second list
        #                 lines2.clear()

        # in each line group keep any non-empty lines
        saved_lines = [[line[0], line[-1]] for line in line_group if line]
        line_group.clear()
        line_group.extend(saved_lines)

    lines = [item for group in line_groups for item in group]

    t2 = time.time()

    print("Hatching:    ", t1 - t0)
    print("Wrangling:   ", t2 - t1)
    print("Total:       ", t2 - t0)

    return lines


# -------------- supporting functions for drawing contours --------------


def find_edges(image):
    print("Finding edges...")
    if no_cv:
        apply_mask(image, [F_SOBEL_X, F_SOBEL_Y])
    else:
        im = np.array(image)
        im = cv2.GaussianBlur(im, (3, 3), 0)
        im = cv2.Canny(im, 100, 200)
        image = Image.fromarray(im)
    return image.point(lambda p: p > 128 and 255)


def get_dots(IM):
    print("Getting contour points...")
    PX = IM.load()
    dots = []
    w, h = IM.size
    for y in range(h - 1):
        row = []
        for x in range(1, w):
            if PX[x, y] == 255:
                if len(row) > 0:
                    if x - row[-1][0] == row[-1][-1] + 1:
                        row[-1] = (row[-1][0], row[-1][-1] + 1)
                    else:
                        row.append((x, 0))
                else:
                    row.append((x, 0))
        dots.append(row)
    return dots


def connect_dots(dots):
    print("Connecting contour points...")
    contours = []
    for y in range(len(dots)):
        for x, v in dots[y]:
            if v > -1:
                if y == 0:
                    contours.append([(x, y)])
                else:
                    closest = -1
                    cdist = 100
                    for x0, v0 in dots[y - 1]:
                        if abs(x0 - x) < cdist:
                            cdist = abs(x0 - x)
                            closest = x0

                    if cdist > 3:
                        contours.append([(x, y)])
                    else:
                        found = 0
                        for i in range(len(contours)):
                            if contours[i][-1] == (closest, y - 1):
                                contours[i].append(
                                    (
                                        x,
                                        y,
                                    )
                                )
                                found = 1
                                break
                        if found == 0:
                            contours.append([(x, y)])
        for c in contours:
            if c[-1][1] < y - 1 and len(c) < 4:
                contours.remove(c)
    return contours


# -------------- optimisation for pen movement --------------


def sort_lines(lines):
    print("Optimizing stroke sequence...")
    clines = lines[:]
    slines = [clines.pop(0)]
    while clines != []:
        x, s, r = None, 1000000, False
        for l in clines:
            d = dist_sum(l[0], slines[-1][-1])
            dr = dist_sum(l[-1], slines[-1][-1])
            if d < s:
                x, s, r = l[:], d, False
            if dr < s:
                x, s, r = l[:], s, True

        clines.remove(x)
        if r is True:
            x = x[::-1]
        slines.append(x)
    return slines


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


def dist_sum(*args):
    return sum(
        [
            ((args[i][0] - args[i - 1][0]) ** 2 + (args[i][1] - args[i - 1][1]) ** 2)
            ** 0.5
            for i in range(1, len(args))
        ]
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
