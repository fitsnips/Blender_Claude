"""Procedurally build five spaceship cookie cutters, each with an embossing stamp.

Each ship is a pair of prints:

* a cutter: a single wall that follows the silhouette, with a single-bevel blade
  on top and a chamfered foot on the bed. It has no inner parts, so it is one
  loop and needs no ribs.
* a stamp: a plate a little smaller than the cookie with raised detail on it
  (portholes, panel lines, flames, canopies). Cut the cookie, then press the
  stamp into it to emboss the detail. The detail is mirrored on the plate so
  the cookie reads the right way round.

Each silhouette is a 2D signed distance field built from rounded primitives
joined with smooth unions, so every corner is filleted. The zero contour is the
cookie line. Each wall is lofted directly from that contour as one closed mesh,
with no booleans. One Blender unit is one millimetre, and so are the STL files.

Usage:
    blender --background --python build_space_cutters.py -- [--render] [--preview]
                                                            [--closeups] [--check]
                                                            [--only rocket,saucer]

Writes space_cutters.blend and stl/<ship>_cutter.stl + stl/<ship>_stamp.stl.
--render  writes cutters.png (the prints) and cookies.png (the stamped cookies).
--preview writes the same views quickly with Workbench.
--closeups writes Workbench close-ups of blade, foot, ridges and grooves.
--check   exits non-zero if any validation fails.
"""
import math
import os
import random
import struct
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree
from mathutils.geometry import delaunay_2d_cdt

HERE = os.path.dirname(os.path.abspath(__file__))
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ONLY = None
if "--only" in ARGS:
    ONLY = set(ARGS[ARGS.index("--only") + 1].split(","))

# ---------------------------------------------------------------- print profile
# Millimetres. A 0.4 mm nozzle lays the 1.6 mm wall as four perimeters and the
# 0.8 mm blade as two. The inner face of the wall is vertical, on the cookie line,
# so the cookie comes out the shape that was drawn; only the outside tapers.
HEIGHT = 16.0        # cutter height
WALL = 1.6           # wall thickness through the middle
EDGE = 0.8           # blade width at the top
TAPER = 3.5          # height of the blade bevel
FOOT = 2.4           # how far the foot sticks out past the wall
FOOT_H = 1.6         # flat part of the foot; a 45 degree chamfer sits above it
CUTTER_PROFILE = (   # (z, outward offset of the outer face)
    (0.0, WALL + FOOT),
    (FOOT_H, WALL + FOOT),
    (FOOT_H + FOOT, WALL),
    (HEIGHT - TAPER, WALL),
    (HEIGHT, EDGE),
)

PLATE = 3.0          # stamp plate thickness
RELIEF = 2.0         # stamp ridge height
CLEAR = 1.0          # stamp plate edge sits this far inside the cookie line
MARGIN = 1.2         # detail stays this far inside the plate edge
STROKE = 1.4         # width of an embossed line
DOUGH = 7.0          # cookie thickness in the render
GROOVE = 1.5         # depth the stamp presses into the cookie

NECK = 2.5           # cookie parts narrower than 2 * NECK snap off
NECK_AREA = 6.0      # mm^2 of thin dough tolerated at a single tip

FINE = 0.2           # distance grid for the outline, detail and dough checks
ROUND_IN = WALL + FOOT + 0.8   # smallest radius of an inside corner
ROUND_OUT = CLEAR + 0.6        # smallest radius of a tip
SPACING = 0.35       # vertex spacing along the cutter wall
DETAIL_SPACING = 0.25


def fresh_scene():
    """Start from an empty scene. Headless, reset Blender. With a window open
    (`blender --python ...`), a reset would tear down the window this script is
    running in and break bpy.context, so remove the existing data instead."""
    if bpy.app.background:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        return
    for coll in (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.lights,
                 bpy.data.cameras, bpy.data.worlds, bpy.data.collections):
        for item in list(coll):
            coll.remove(item)


fresh_scene()
scene = bpy.context.scene
scene.unit_settings.system = "METRIC"
scene.unit_settings.scale_length = 0.001
scene.unit_settings.length_unit = "MILLIMETERS"


# ---------------------------------------------------------------- 2D distance fields
# Every primitive takes numpy arrays X, Y and returns signed distance: negative
# inside. Smooth union keeps the result smooth where parts meet, which gives the
# concave fillets the foot needs (a sharp notch would fold the foot over itself).
def circle(cx, cy, r):
    return lambda X, Y: np.hypot(X - cx, Y - cy) - r


def ellipse(cx, cy, rx, ry):
    """Not an exact distance, but the zero set is exact, and that is all the
    outline uses. Detail is measured against exact distances further down."""
    k = min(rx, ry)
    return lambda X, Y: (np.hypot((X - cx) / rx, (Y - cy) / ry) - 1.0) * k


def capsule(ax, ay, bx, by, r):
    def f(X, Y):
        px, py = X - ax, Y - ay
        dx, dy = bx - ax, by - ay
        t = np.clip((px * dx + py * dy) / (dx * dx + dy * dy), 0.0, 1.0)
        return np.hypot(px - t * dx, py - t * dy) - r
    return f


def rbox(cx, cy, hx, hy, r=0.0):
    def f(X, Y):
        qx = np.abs(X - cx) - (hx - r)
        qy = np.abs(Y - cy) - (hy - r)
        outside = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0))
        return outside + np.minimum(np.maximum(qx, qy), 0) - r
    return f


def polygon(pts, r=0.0):
    """Exact distance to a polygon, grown by r so its convex corners round off."""
    P = np.asarray(pts, dtype=float)

    def f(X, Y):
        d = np.full(X.shape, np.inf)
        inside = np.zeros(X.shape, dtype=bool)
        n = len(P)
        for i in range(n):
            ax, ay = P[i]
            bx, by = P[(i + 1) % n]
            ex, ey = bx - ax, by - ay
            wx, wy = X - ax, Y - ay
            t = np.clip((wx * ex + wy * ey) / (ex * ex + ey * ey), 0, 1)
            d = np.minimum(d, np.hypot(wx - t * ex, wy - t * ey))
            cross = ((ay > Y) != (by > Y)) & (X < ax + (Y - ay) * ex / (ey + 1e-12))
            inside ^= cross
        return np.where(inside, -d, d) - r
    return f


def mirror_x(f):
    return lambda X, Y: f(np.abs(X), Y)


def union(*fs, k=6.0):
    """Polynomial smooth minimum. k is roughly the width of the blend."""
    def f(X, Y):
        d = fs[0](X, Y)
        for g in fs[1:]:
            e = g(X, Y)
            h = np.clip(0.5 + 0.5 * (e - d) / k, 0.0, 1.0)
            d = e * (1 - h) + d * h - k * h * (1 - h)
        return d
    return f


def hard_union(*fs):
    def f(X, Y):
        d = fs[0](X, Y)
        for g in fs[1:]:
            d = np.minimum(d, g(X, Y))
        return d
    return f


def clip_to(f, g):
    """f where g is negative (intersection)."""
    return lambda X, Y: np.maximum(f(X, Y), g(X, Y))


def line(*pts, w=STROKE):
    """A raised stroke along a polyline."""
    caps = [capsule(*pts[i], *pts[i + 1], w / 2.0) for i in range(len(pts) - 1)]
    return hard_union(*caps)


def ring(f, w=STROKE):
    """A stroke along the zero contour of f."""
    return lambda X, Y: np.abs(f(X, Y)) - w / 2.0


# Detail fields also get E, the exact signed distance to the cookie line, so a
# border can run a fixed distance in from the edge.
def piping(inset, w=STROKE):
    return lambda X, Y, E: np.abs(E + inset) - w / 2.0


def plain(f):
    return lambda X, Y, E: f(X, Y)


def detail(*parts):
    def f(X, Y, E):
        d = parts[0](X, Y, E)
        for p in parts[1:]:
            d = np.minimum(d, p(X, Y, E))
        return d
    return f


# ---------------------------------------------------------------- the ships
# Drawn nose-up (or dome-up), in millimetres, roughly centred on the origin.
def rocket():
    """Retro rocket: ogive nose, fat body, swept fins and a flame."""
    nose_r = 40.0

    def nose(X, Y):
        a = np.hypot(X - (nose_r - 13.0), Y - 18.0) - (nose_r - 3.0)
        b = np.hypot(X + (nose_r - 13.0), Y - 18.0) - (nose_r - 3.0)
        return np.maximum(np.maximum(a, b), -(Y - 10.0)) - 3.0
    body = rbox(0, -6, 13, 26, 3)
    fin = mirror_x(polygon([(10, 0), (25, -24), (26, -40), (10, -30)], 2.5))
    flame = union(circle(0, -36, 7.0),
                  polygon([(-4.5, -38), (4.5, -38), (0, -52)], 2.0), k=5)
    outline = union(nose, body, fin, flame, k=7)

    nose_body = union(nose, body, k=7)
    flame_f = flame
    art = detail(
        plain(ring(circle(0, 14, 6.6))),
        plain(circle(0, 14, 2.6)),
        plain(line((-12, 27), (12, 27))),
        plain(clip_to(line((-14, -6), (14, -6)), nose_body)),
        plain(clip_to(line((-14, -20), (14, -20)), nose_body)),
        plain(hard_union(*[circle(x, -13, 0.9) for x in (-7, 0, 7)])),
        plain(mirror_x(line((15, -10), (21.5, -31)))),
        plain(clip_to(ring(lambda X, Y: flame_f(X, Y) + 3.2), lambda X, Y: Y + 31.5)),
    )
    return outline, art


def saucer():
    """Flying saucer: a glass dome on a wide disc with a beam emitter."""
    dome = clip_to(circle(0, 4, 19), lambda X, Y: -(Y - 2.0))
    disc = ellipse(0, 0, 52, 11.5)
    emitter = rbox(0, -10, 13, 5, 3)
    outline = union(dome, disc, emitter, k=6)

    art = detail(
        plain(clip_to(ring(circle(0, 4, 15.5)), lambda X, Y: -(Y - 9.5))),
        plain(capsule(-6.5, 16.5, -3.5, 19.5, 0.9)),
        plain(line((-38, 0.5), (38, 0.5))),
        plain(hard_union(*[circle(x, -5.2, 2.0) for x in (-32, -16, 0, 16, 32)])),
        plain(hard_union(*[circle(x, 4.5, 0.9) for x in (-36, -26, 26, 36)])),
        plain(line((-7, -11.5), (7, -11.5))),
    )
    return outline, art


def shuttle():
    """Space shuttle seen from above: double-delta wing, OMS pods, engines."""
    fuselage = union(capsule(0, -36, 0, 34, 9.5), ellipse(0, 38, 8.5, 13), k=5)
    wing = mirror_x(polygon([(8, 4), (33, -30), (34, -37), (8, -37)], 1.8))
    strake = mirror_x(polygon([(7, 22), (12, 4), (7, -4)], 1.5))
    engines = hard_union(*[circle(x, -46, 3.6) for x in (-5, 0, 5)])
    outline = union(fuselage, wing, strake, engines, k=6)

    wing_f = wing
    art = detail(
        plain(mirror_x(polygon([(0.9, 42.5), (5.0, 41.0), (4.6, 38.8), (0.9, 39.8)]))),
        plain(ring(rbox(0, 4, 6.0, 20, 2.0))),
        plain(line((0, -15), (0, 23))),
        plain(mirror_x(clip_to(line((12, -33.5), (33, -33.5)), lambda X, Y: wing_f(X, Y) + 1.5))),
        plain(mirror_x(line((11, 0), (11, -24)))),
        plain(line((0, -28), (0, -40))),
    )
    return outline, art


def starfighter():
    """Arrow-head starfighter with wingtip engine pods and twin tail engines."""
    hull = polygon([(0, 46), (7, 22), (8.5, -30), (0, -38), (-8.5, -30), (-7, 22)], 2.0)
    wing = mirror_x(polygon([(6, 6), (36, -18), (36, -28), (6, -24)], 2.0))
    pod = mirror_x(capsule(39, -4, 39, -33, 4.0))
    engine = mirror_x(capsule(6.5, -30, 6.5, -40, 4.0))
    outline = union(hull, wing, pod, engine, k=6)

    art = detail(
        plain(ring(ellipse(0, 18, 3.6, 9.0))),
        plain(line((0, 29.5), (0, 40))),
        plain(mirror_x(line((12, -2), (30, -16)))),
        plain(mirror_x(line((12, -8), (30, -22)))),
        plain(mirror_x(line((39, -6.5), (39, -30.5)))),
        plain(mirror_x(circle(6.5, -40, 1.7))),
        plain(line((-3, -14), (0, -20), (3, -14))),
    )
    return outline, art


def lander():
    """Moon lander: faceted cabin on a descent stage, splayed legs, foot pads."""
    cabin = polygon([(-16, 10), (16, 10), (16, 25), (8.5, 32), (-8.5, 32), (-16, 25)], 2.0)
    stage = rbox(0, -1, 26, 9, 2.5)
    leg = mirror_x(capsule(21, -3, 37, -26, 4.5))
    pad = mirror_x(rbox(39, -29, 8, 3.8, 2.5))
    bell = polygon([(-6, -9), (6, -9), (9, -19), (-9, -19)], 1.5)
    outline = union(cabin, stage, leg, pad, bell, k=6)

    stage_f = stage
    art = detail(
        plain(polygon([(-8, 20), (8, 20), (5, 26), (-5, 26)], 0.6)),
        plain(ring(rbox(0, 13.8, 5, 3.0, 1.0))),
        plain(mirror_x(line((12, 15), (12, 22)))),
        plain(mirror_x(line((10, 18.5), (14, 18.5)))),
        plain(ring(lambda X, Y: stage_f(X, Y) + 3.0)),
        plain(line((-12, -1), (12, -1))),
        plain(mirror_x(line((27, -10), (35, -21)))),
        plain(line((-5, -14.5), (5, -14.5))),
    )
    return outline, art


SHIPS = (
    ("rocket", rocket, (0.82, 0.14, 0.10)),
    ("saucer", saucer, (0.30, 0.76, 0.46)),
    ("shuttle", shuttle, (0.90, 0.90, 0.87)),
    ("starfighter", starfighter, (0.13, 0.36, 0.82)),
    ("lander", lander, (0.92, 0.70, 0.16)),
)


# ---------------------------------------------------------------- contours
def grid_for(f, step, pad=8.0, probe=80.0):
    """A grid that covers the shape with pad millimetres of outside around it."""
    xs = np.arange(-probe, probe, 0.5)
    X, Y = np.meshgrid(xs, xs)
    inside = f(X, Y) < 0
    if not inside.any():
        raise ValueError("shape is empty")
    ys_in, xs_in = np.nonzero(inside)
    x0, x1 = xs[xs_in.min()] - pad, xs[xs_in.max()] + pad
    y0, y1 = xs[ys_in.min()] - pad, xs[ys_in.max()] + pad
    gx = np.arange(x0, x1 + step, step)
    gy = np.arange(y0, y1 + step, step)
    return np.meshgrid(gx, gy)


def contours(F, X, Y):
    """Closed loops where F crosses zero (marching squares). F < 0 is inside.
    The grid border must be outside everywhere."""
    F = np.where(F == 0.0, 1e-9, F)
    ny, nx = F.shape
    x0, y0 = X[0, 0], Y[0, 0]
    h = X[0, 1] - X[0, 0]
    inside = F < 0

    def h_key(j, i):
        return j * nx + i

    def v_key(j, i):
        return ny * nx + j * nx + i

    def h_pt(j, i):
        t = F[j, i] / (F[j, i] - F[j, i + 1])
        return (x0 + (i + t) * h, y0 + j * h)

    def v_pt(j, i):
        t = F[j, i] / (F[j, i] - F[j + 1, i])
        return (x0 + i * h, y0 + (j + t) * h)

    a = inside[:-1, :-1]
    b = inside[:-1, 1:]
    c = inside[1:, 1:]
    d = inside[1:, :-1]
    mixed = ~((a == b) & (b == c) & (c == d))
    links = {}
    points = {}

    def connect(k1, p1, k2, p2):
        points[k1] = p1
        points[k2] = p2
        links.setdefault(k1, []).append(k2)
        links.setdefault(k2, []).append(k1)

    for j, i in zip(*np.nonzero(mixed)):
        ca, cb, cc, cd = inside[j, i], inside[j, i + 1], inside[j + 1, i + 1], inside[j + 1, i]
        edges = {}
        if ca != cb:
            edges["bottom"] = (h_key(j, i), h_pt(j, i))
        if cb != cc:
            edges["right"] = (v_key(j, i + 1), v_pt(j, i + 1))
        if cd != cc:
            edges["top"] = (h_key(j + 1, i), h_pt(j + 1, i))
        if ca != cd:
            edges["left"] = (v_key(j, i), v_pt(j, i))
        if len(edges) == 2:
            (k1, p1), (k2, p2) = edges.values()
            connect(k1, p1, k2, p2)
        else:
            # Saddle: cut off the two corners that disagree with the centre.
            centre = (F[j, i] + F[j, i + 1] + F[j + 1, i + 1] + F[j + 1, i]) < 0
            if ca != centre:
                pairs = (("left", "bottom"), ("right", "top"))
            else:
                pairs = (("bottom", "right"), ("top", "left"))
            for e1, e2 in pairs:
                connect(*edges[e1], *edges[e2])

    loops = []
    seen = set()
    for start in links:
        if start in seen:
            continue
        loop = [start]
        seen.add(start)
        prev, cur = None, start
        while True:
            nxt = [k for k in links[cur] if k != prev]
            if not nxt:
                break
            step = nxt[0]
            if step == start:
                break
            if step in seen:
                break
            loop.append(step)
            seen.add(step)
            prev, cur = cur, step
        if len(loop) >= 4:
            loops.append(np.array([points[k] for k in loop]))
    return loops


def signed_area(P):
    x, y = P[:, 0], P[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def resample(P, spacing):
    seg = np.linalg.norm(np.roll(P, -1, axis=0) - P, axis=1)
    total = seg.sum()
    count = max(16, int(round(total / spacing)))
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    target = np.arange(count) * total / count
    closed = np.vstack([P, P[:1]])
    x = np.interp(target, cum, closed[:, 0])
    y = np.interp(target, cum, closed[:, 1])
    return np.stack([x, y], axis=1)


def dist_to_loop(Q, L, chunk=1500):
    """Exact distance from each point in Q to the closed polyline L."""
    A = L
    B = np.roll(L, -1, axis=0)
    AB = B - A
    ab2 = np.maximum((AB ** 2).sum(axis=1), 1e-12)
    out = np.empty(len(Q))
    for s in range(0, len(Q), chunk):
        q = Q[s:s + chunk]
        ap = q[:, None, :] - A[None, :, :]
        t = np.clip((ap * AB[None]).sum(axis=2) / ab2[None], 0, 1)
        diff = ap - t[..., None] * AB[None]
        out[s:s + chunk] = np.sqrt((diff ** 2).sum(axis=2)).min(axis=1)
    return out


def inside_loop(Q, L):
    """Even-odd point-in-polygon for many points at once."""
    x, y = Q[:, 0], Q[:, 1]
    inside = np.zeros(len(Q), dtype=bool)
    ax, ay = L[:, 0], L[:, 1]
    bx, by = np.roll(ax, -1), np.roll(ay, -1)
    for i in range(len(L)):
        if ay[i] == by[i]:
            continue
        crosses = (ay[i] > y) != (by[i] > y)
        xi = ax[i] + (y - ay[i]) * (bx[i] - ax[i]) / (by[i] - ay[i])
        inside ^= crosses & (x < xi)
    return inside


def signed_distance(loop, X, Y, inside):
    """Distance from grid points to a closed loop, negative where inside is
    true. The loop is sampled every 0.05 mm, so the nearest sample is within
    a few microns of the true nearest point."""
    dense = resample(loop, 0.05)
    tree = KDTree(len(dense))
    for i, p in enumerate(dense):
        tree.insert((p[0], p[1], 0.0), i)
    tree.balance()
    d = np.array([tree.find((x, y, 0.0))[2] for x, y in zip(X.ravel(), Y.ravel())])
    d = d.reshape(X.shape)
    return np.where(inside, -d, d)


def main_loop(F, X, Y):
    loops = contours(F, X, Y)
    loop = max(loops, key=lambda L: abs(signed_area(L)))
    return (loop if signed_area(loop) > 0 else loop[::-1]), len(loops)


def loop_normals(P):
    """Outward unit normals of a CCW loop, from a slightly smoothed tangent."""
    t = np.roll(P, -2, axis=0) - np.roll(P, 2, axis=0)
    t = t / np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-12)
    n = np.stack([t[:, 1], -t[:, 0]], axis=1)
    return n


def fft_dilate(mask, radius_cells):
    r = int(math.ceil(radius_cells))
    ky, kx = np.mgrid[-r:r + 1, -r:r + 1]
    kernel = (kx * kx + ky * ky <= radius_cells * radius_cells).astype(float)
    shape = (mask.shape[0] + kernel.shape[0] - 1, mask.shape[1] + kernel.shape[1] - 1)
    conv = np.fft.irfft2(np.fft.rfft2(mask.astype(float), shape) * np.fft.rfft2(kernel, shape), shape)
    return conv[r:r + mask.shape[0], r:r + mask.shape[1]] > 0.5


def components(mask):
    """4-connected blobs of a boolean grid, as lists of (j, i)."""
    seen = np.zeros(mask.shape, dtype=bool)
    blobs = []
    for j, i in zip(*np.nonzero(mask)):
        if seen[j, i]:
            continue
        stack, blob = [(j, i)], []
        seen[j, i] = True
        while stack:
            cj, ci = stack.pop()
            blob.append((cj, ci))
            for nj, ni in ((cj + 1, ci), (cj - 1, ci), (cj, ci + 1), (cj, ci - 1)):
                if 0 <= nj < mask.shape[0] and 0 <= ni < mask.shape[1] \
                        and mask[nj, ni] and not seen[nj, ni]:
                    seen[nj, ni] = True
                    stack.append((nj, ni))
        blobs.append(blob)
    return blobs


# ---------------------------------------------------------------- planning a ship
def plan(name, shape_fn):
    """Everything 2D about one ship, plus the drawing problems found on the way."""
    outline_f, art_f = shape_fn()
    problems = []

    # Centre the silhouette on its bounding box.
    X, Y = grid_for(outline_f, 0.5)
    inside = outline_f(X, Y) < 0
    cx = 0.5 * (X[inside].min() + X[inside].max())
    cy = 0.5 * (Y[inside].min() + Y[inside].max())

    def f(X, Y):
        return outline_f(X + cx, Y + cy)

    def art(X, Y, E):
        return art_f(X + cx, Y + cy, E)

    # Cookie line. Close the drawn silhouette by ROUND_IN (every inside corner
    # gets at least that radius, so the foot can follow it without folding),
    # then open it by ROUND_OUT (every tip gets at least that radius, so the
    # stamp plate can follow it inset). Both are exact distance-field offsets.
    FX, FY = grid_for(f, FINE, pad=ROUND_IN + 6.0)
    raw, count = main_loop(f(FX, FY), FX, FY)
    if count != 1:
        problems.append(f"{name}: silhouette has {count} separate outlines, want 1")
    F0 = f(FX, FY)
    E0 = signed_distance(raw, FX, FY, F0 < 0)
    grown, _ = main_loop(E0 - ROUND_IN, FX, FY)
    closed = signed_distance(grown, FX, FY, E0 - ROUND_IN < 0) + ROUND_IN
    shrunk, _ = main_loop(closed + ROUND_OUT, FX, FY)
    rounded = signed_distance(shrunk, FX, FY, closed + ROUND_OUT < 0) - ROUND_OUT
    base, _ = main_loop(rounded, FX, FY)
    base = resample(base, SPACING)
    normals = loop_normals(base)
    E = signed_distance(base, FX, FY, rounded < 0)

    def cookie_dist(Q):
        d = dist_to_loop(Q, base)
        return np.where(inside_loop(Q, base), -d, d)

    # Dough check: open the cookie by NECK. Whatever the opening removes is a
    # part thinner than 2 * NECK, and a long one snaps off when the cookie moves.
    cookie = E < 0
    core = E <= -NECK
    kept = fft_dilate(core, NECK / FINE)
    thin = cookie & ~kept & (E < -0.25)
    for blob in components(thin):
        area = len(blob) * FINE * FINE
        if area > NECK_AREA:
            j, i = blob[len(blob) // 2]
            problems.append(f"{name}: {area:.0f} mm² of dough thinner than "
                            f"{2 * NECK:.0f} mm near ({FX[j, i]:.0f}, {FY[j, i]:.0f})")

    # Wall rings. Each is the cookie line pushed out along its normal; if part of
    # the silhouette lies closer than the push, the foot would fold through it.
    rings = []
    for z, off in CUTTER_PROFILE:
        ring_pts = base + normals * off
        rings.append((z, ring_pts))
    widest = max(off for _z, off in CUTTER_PROFILE)
    outer = base + normals * widest
    gap = dist_to_loop(outer, base)
    if gap.min() < widest - 0.05:
        k = int(np.argmin(gap))
        problems.append(f"{name}: foot folds through the wall near "
                        f"({outer[k, 0]:.0f}, {outer[k, 1]:.0f}); notch is too tight")

    # Stamp plate: the cookie line pulled in by CLEAR.
    plate = base - normals * CLEAR
    gap = dist_to_loop(plate, base)
    if gap.min() < CLEAR - 0.05:
        problems.append(f"{name}: stamp plate outline folds at a tip")

    # Detail: the art, kept MARGIN inside the plate edge.
    D = np.maximum(art(FX, FY, E), E + CLEAR + MARGIN)
    raw = contours(D, FX, FY)
    detail_loops = []
    for L in raw:
        L = resample(L, DETAIL_SPACING)
        area = abs(signed_area(L))
        if area < 1.2:
            c = L.mean(axis=0)
            problems.append(f"{name}: detail sliver of {area:.1f} mm² near ({c[0]:.0f}, {c[1]:.0f})")
            continue
        detail_loops.append(L)
    # A ridge must be wide enough to print: somewhere inside each island the
    # field must reach -STROKE/2 (allowing for the grid).
    relief_mask = D < 0
    for blob in components(relief_mask):
        deepest = min(D[j, i] for j, i in blob)
        if deepest > -(STROKE / 2.0) + FINE:
            j, i = blob[0]
            problems.append(f"{name}: ridge near ({FX[j, i]:.0f}, {FY[j, i]:.0f}) is only "
                            f"{-2 * deepest:.1f} mm wide")

    width = base[:, 0].max() - base[:, 0].min()
    height = base[:, 1].max() - base[:, 1].min()
    return {
        "name": name, "cookie_dist": cookie_dist, "base": base, "normals": normals, "rings": rings,
        "plate": plate, "details": detail_loops, "problems": problems,
        "size2d": (width, height),
    }


# ---------------------------------------------------------------- meshes
def material(name, color, rough=0.35):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    if mat.node_tree is None:
        mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = rough
    return mat


def make_object(name, verts, faces, mat):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    if bm.calc_volume(signed=True) < 0:
        bmesh.ops.reverse_faces(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    me.update()
    obj = bpy.data.objects.new(name, me)
    scene.collection.objects.link(obj)
    obj.data.materials.append(mat)
    return obj


def cutter_mesh(ship, mat):
    """One closed ring: a vertical inner face on the cookie line, and an outer
    face lofted through the profile (foot, chamfer, wall, blade bevel)."""
    base = ship["base"]
    n = len(base)
    verts = []
    inner_bottom = 0
    verts += [(p[0], p[1], 0.0) for p in base]
    inner_top = len(verts)
    verts += [(p[0], p[1], HEIGHT) for p in base]
    outer_rows = []
    for z, ring_pts in ship["rings"]:
        outer_rows.append(len(verts))
        verts += [(p[0], p[1], z) for p in ring_pts]
    faces = []
    for i in range(n):
        k = (i + 1) % n
        faces.append((inner_bottom + i, inner_bottom + k, inner_top + k, inner_top + i))
        for r0, r1 in zip(outer_rows, outer_rows[1:]):
            faces.append((r0 + i, r1 + i, r1 + k, r0 + k))
        faces.append((inner_bottom + i, outer_rows[0] + i, outer_rows[0] + k, inner_bottom + k))
        faces.append((inner_top + i, inner_top + k, outer_rows[-1] + k, outer_rows[-1] + i))
    return make_object(ship["name"] + "_cutter", verts, faces, mat)


def fill_even_odd(loops, offset_of):
    """Triangles filling the region inside an odd number of loops, from a
    constrained Delaunay triangulation of all the loop edges. Each triangle
    indexes the loop vertices it was built from (offset_of[i] + j)."""
    coords = np.vstack(loops)
    starts = np.cumsum([0] + [len(L) for L in loops])
    edges = []
    for li, L in enumerate(loops):
        m = len(L)
        edges += [(starts[li] + j, starts[li] + (j + 1) % m) for j in range(m)]
    # A frame well outside keeps straight runs of outline off the convex hull,
    # where the triangulation would leave zero-area slivers.
    lo, hi = coords.min(axis=0) - 10.0, coords.max(axis=0) + 10.0
    frame = [(lo[0], lo[1]), (hi[0], lo[1]), (hi[0], hi[1]), (lo[0], hi[1])]
    verts, _e, faces, orig, _oe, _of = delaunay_2d_cdt(
        [Vector(p) for p in coords] + [Vector(p) for p in frame], edges, [], 0, 1e-6)
    if len(verts) != len(coords) + 4:
        raise RuntimeError(f"triangulation added {len(verts) - len(coords) - 4} vertices; "
                           "two outlines touch")
    remap = [o[0] for o in orig]
    flat = [offset_of[li] + j for li, L in enumerate(loops) for j in range(len(L))]
    faces = [tri for tri in faces if all(remap[v] < len(coords) for v in tri)]
    tris = np.array([[remap[v] for v in tri] for tri in faces])
    cent = coords[tris].mean(axis=1)
    depth = np.zeros(len(tris), dtype=int)
    for L in loops:
        depth += inside_loop(cent, L)
    return [tuple(flat[v] for v in tri) for tri, d in zip(tris, depth) if d % 2 == 1]


def relief_mesh(name, outline, detail_loops, thickness, relief, mat):
    """A slab on the outline with raised (relief > 0) or sunken (relief < 0)
    detail on top, built as one closed surface with shared edges."""
    verts = []
    faces = []
    n = len(outline)
    b0 = len(verts)
    verts += [(p[0], p[1], 0.0) for p in outline]
    t0 = len(verts)
    verts += [(p[0], p[1], thickness) for p in outline]
    for i in range(n):
        k = (i + 1) % n
        faces.append((b0 + i, b0 + k, t0 + k, t0 + i))
    for tri in fill_even_odd([outline], [b0]):
        faces.append(tri)
    low, high = [], []
    for L in detail_loops:
        low.append(len(verts))
        verts += [(p[0], p[1], thickness) for p in L]
        high.append(len(verts))
        verts += [(p[0], p[1], thickness + relief) for p in L]
        m = len(L)
        for i in range(m):
            k = (i + 1) % m
            faces.append((low[-1] + i, low[-1] + k, high[-1] + k, high[-1] + i))
    # Top of the slab: outline minus the detail. Top of the detail: the detail.
    faces += fill_even_odd([outline] + detail_loops, [t0] + low)
    if detail_loops:
        faces += fill_even_odd(detail_loops, high)
    return make_object(name, verts, faces, mat)


def mesh_report(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bad = [e for e in bm.edges if not e.is_manifold]
    open_edges = len(bad)
    where = [tuple(round(c, 1) for c in (e.verts[0].co)) for e in bad[:4]]
    volume = bm.calc_volume(signed=True)
    seen, pieces = set(), 0
    bm.verts.ensure_lookup_table()
    for v in bm.verts:
        if v.index in seen:
            continue
        pieces += 1
        stack = [v]
        seen.add(v.index)
        while stack:
            cur = stack.pop()
            for e in cur.link_edges:
                o = e.other_vert(cur)
                if o.index not in seen:
                    seen.add(o.index)
                    stack.append(o)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.faces.ensure_lookup_table()
    tree = BVHTree.FromBMesh(bm, epsilon=0.0)
    crossings = 0
    for i, j in tree.overlap(tree):
        if i < j and not ({v.index for v in bm.faces[i].verts}
                          & {v.index for v in bm.faces[j].verts}):
            crossings += 1
    bm.free()
    zs = [v.co.z for v in obj.data.vertices]
    xs = [v.co.x for v in obj.data.vertices]
    ys = [v.co.y for v in obj.data.vertices]
    return {"open": open_edges, "where": where, "volume": volume, "pieces": pieces, "crossings": crossings,
            "size": (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)),
            "zmin": min(zs)}


def write_stl(obj, path):
    """Binary STL in millimetres, straight from the mesh (no unit scaling)."""
    me = obj.data
    me.calc_loop_triangles()
    with open(path, "wb") as fh:
        fh.write(b"space cookie cutter".ljust(80, b" "))
        fh.write(struct.pack("<I", len(me.loop_triangles)))
        for tri in me.loop_triangles:
            nrm = tri.normal
            fh.write(struct.pack("<3f", nrm.x, nrm.y, nrm.z))
            for vi in tri.vertices:
                co = me.vertices[vi].co
                fh.write(struct.pack("<3f", co.x, co.y, co.z))
            fh.write(b"\0\0")


# ---------------------------------------------------------------- build
print("\n=== Space cookie cutters ===")
PROBLEMS = []
ships = []
for name, shape_fn, color in SHIPS:
    if ONLY and name not in ONLY:
        continue
    print(f"\n{name}")
    ship = plan(name, shape_fn)
    for line_ in ship["problems"]:
        print("  DRAW", line_)
    PROBLEMS += ship["problems"]
    mat = material(name, color)
    ship["cutter"] = cutter_mesh(ship, mat)
    # The stamp is pressed face-down, so its detail is the mirror image.
    flip = np.array([-1.0, 1.0])
    plate = (ship["plate"] * flip)[::-1]
    det = [(L * flip)[::-1] for L in ship["details"]]
    ship["stamp"] = relief_mesh(name + "_stamp", plate, det, PLATE, RELIEF, mat)
    ships.append(ship)

    for part in ("cutter", "stamp"):
        rep = mesh_report(ship[part])
        ship[part + "_report"] = rep
        sx, sy, sz = rep["size"]
        print(f"  {part:6s} {sx:5.1f} x {sy:5.1f} x {sz:4.1f} mm  "
              f"volume={rep['volume'] / 1000:.2f} cm³  pieces={rep['pieces']}  "
              f"open={rep['open']}  crossings={rep['crossings']}")
        want_h = HEIGHT if part == "cutter" else PLATE + (RELIEF if ship["details"] else 0)
        label = f"{name} {part}"
        if rep["open"]:
            PROBLEMS.append(f"{label}: {rep['open']} non-manifold edges, e.g. at {rep['where']}")
        if rep["pieces"] != 1:
            PROBLEMS.append(f"{label}: {rep['pieces']} pieces, want 1")
        if rep["crossings"]:
            PROBLEMS.append(f"{label}: surface passes through itself ({rep['crossings']} spots)")
        if abs(rep["size"][2] - want_h) > 0.01 or abs(rep["zmin"]) > 1e-6:
            PROBLEMS.append(f"{label}: height {rep['size'][2]:.2f}, want {want_h:.2f} on the bed")
        if rep["volume"] <= 0:
            PROBLEMS.append(f"{label}: no volume")
        if max(rep["size"][:2]) > 240:
            PROBLEMS.append(f"{label}: too big for the bed")

    # Flip the stamp over the way a person presses it (x -> -x) and check that
    # every ridge lands on the art, inside the cookie, clear of the cutter.
    pressed = np.array([(-v.co.x, v.co.y) for v in ship["stamp"].data.vertices])
    fv = ship["cookie_dist"](pressed)
    if fv.max() > -CLEAR + 0.05:
        PROBLEMS.append(f"{name} stamp: plate reaches {fv.max():+.2f} mm from the cookie "
                        f"line, want inside by {CLEAR}")
    print(f"  {len(ship['details'])} detail outlines")

# Stamps and cutters belong together; check the fit pairwise.
for ship in ships:
    w_cookie, h_cookie = ship["size2d"]
    sx, sy, _ = ship["stamp_report"]["size"]
    if sx > w_cookie - 2 * CLEAR + 0.1 or sy > h_cookie - 2 * CLEAR + 0.1:
        PROBLEMS.append(f"{ship['name']}: stamp {sx:.1f} x {sy:.1f} does not fit the "
                        f"{w_cookie:.1f} x {h_cookie:.1f} cookie")

print("\n=== STL ===")
os.makedirs(os.path.join(HERE, "stl"), exist_ok=True)
for ship in ships:
    for part in ("cutter", "stamp"):
        path = os.path.join(HERE, "stl", f"{ship['name']}_{part}.stl")
        write_stl(ship[part], path)
        sx, sy, sz = ship[part + "_report"]["size"]
        print(f"  {os.path.basename(path):24s} {sx:6.1f} x {sy:6.1f} x {sz:5.1f} mm")

print("\n=== Validation ===")
if PROBLEMS:
    for line_ in PROBLEMS:
        print("  FAIL", line_)
    print(f"  {len(PROBLEMS)} problem(s)")
else:
    print(f"  PASS: {len(ships)} cutters and {len(ships)} stamps, each one closed piece "
          "on the bed; stamps fit their cookies")


# ---------------------------------------------------------------- layout and renders
def place(objs_by_col, gap=16.0, row_gap=20.0):
    """Lay objects out in rows; objs_by_col is a list of rows."""
    bounds = []
    for row in objs_by_col:
        sizes = []
        for obj in row:
            xs = [v.co.x for v in obj.data.vertices]
            ys = [v.co.y for v in obj.data.vertices]
            sizes.append((min(xs), max(xs), min(ys), max(ys)))
        bounds.append(sizes)
    row_h = [max(s[3] - s[2] for s in sizes) for sizes in bounds]
    y = (sum(row_h) + row_gap * (len(row_h) - 1)) / 2.0
    for row, sizes, height in zip(objs_by_col, bounds, row_h):
        widths = [s[1] - s[0] for s in sizes]
        x = -(sum(widths) + gap * (len(row) - 1)) / 2.0
        yc = y - height / 2.0
        for obj, s, w in zip(row, sizes, widths):
            obj.location = (x + w / 2.0 - (s[0] + s[1]) / 2.0, yc - (s[2] + s[3]) / 2.0, 0)
            x += w + gap
        y -= height + row_gap


def bounds_of(objs):
    bpy.context.view_layer.update()
    pts = [o.matrix_world @ v.co for o in objs for v in o.data.vertices]
    return ([p.x for p in pts], [p.y for p in pts], [p.z for p in pts])


def clear_stage():
    for obj in list(scene.objects):
        if obj.type in {"LIGHT", "CAMERA", "EMPTY"} or obj.get("stage"):
            bpy.data.objects.remove(obj, do_unlink=True)


def stage(objs, table_color, look_z, stars=False):
    xs, ys, _zs = bounds_of(objs)
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    span = max(max(xs) - min(xs), max(ys) - min(ys))
    bpy.ops.mesh.primitive_plane_add(size=2, location=(cx, cy, -0.02))
    table = bpy.context.active_object
    table.name = "Table"
    table["stage"] = True
    table.scale = (span * 1.6, span * 1.6, 1)
    table.data.materials.append(material("Table", table_color, 0.6))
    if stars:
        # Sugar stars and sprinkles scattered on the board, resting on it.
        rng = random.Random(7)
        star_mat = material("Sprinkle", (0.98, 0.95, 0.80), 0.3)
        star_mat.node_tree.nodes["Principled BSDF"].inputs["Emission Color"].default_value = (1, 0.95, 0.7, 1)
        star_mat.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"].default_value = 0.6
        placed = 0
        tries = 0
        while placed < 140 and tries < 5000:
            tries += 1
            x = cx + rng.uniform(-0.62, 0.62) * span * 1.25
            y = cy + rng.uniform(-0.45, 0.45) * span * 1.0
            hit = False
            for ship in ships:
                c = ship["cookie"]
                if ship["cookie_dist"](np.array([[x - c.location.x, y - c.location.y]]))[0] < 3.0:
                    hit = True
                    break
            if hit:
                continue
            r = rng.uniform(0.35, 0.9)
            bpy.ops.mesh.primitive_uv_sphere_add(radius=r, location=(x, y, r * 0.55),
                                                 segments=12, ring_count=6)
            s = bpy.context.active_object
            s["stage"] = True
            s.scale.z = 0.6
            s.data.materials.append(star_mat)
            placed += 1

    world = bpy.data.worlds.new("World")
    scene.world = world
    if world.node_tree is None:
        world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.9, 0.9, 0.95, 1) if not stars else (0.25, 0.3, 0.5, 1)
    bg.inputs["Strength"].default_value = 0.35

    def area(name, loc, rot, energy, size, color):
        bpy.ops.object.light_add(type="AREA", location=loc,
                                 rotation=[math.radians(a) for a in rot])
        light = bpy.context.active_object
        light.name = name
        light.data.energy = energy
        light.data.size = size
        light.data.color = color
    # Area lights are in watts; the scene is a few hundred millimetres across.
    area("Key", (cx + span * 0.25, cy - span * 0.6, span * 0.8), (55, 0, 20),
         span * span * 1.7, span * 0.5, (1.0, 0.95, 0.88))
    area("Fill", (cx - span * 0.75, cy - span * 0.15, span * 0.45), (70, 0, -60),
         span * span * 0.5, span * 0.7, (0.78, 0.86, 1.0))
    area("Rim", (cx - span * 0.1, cy + span * 0.75, span * 0.5), (-60, 0, 180),
         span * span * 0.9, span * 0.4, (1.0, 0.97, 0.95))
    return cx, cy, span


def camera(name, loc, target, lens=None, ortho=None):
    bpy.ops.object.camera_add(location=loc)
    cam = bpy.context.active_object
    cam.name = name
    cam.data.clip_start = 1.0
    cam.data.clip_end = 5000.0
    empty = bpy.data.objects.new(name + "_target", None)
    scene.collection.objects.link(empty)
    empty.location = target
    con = cam.constraints.new("TRACK_TO")
    con.target = empty
    con.track_axis = "TRACK_NEGATIVE_Z"
    con.up_axis = "UP_Y"
    if ortho:
        cam.data.type = "ORTHO"
        cam.data.ortho_scale = ortho
    else:
        cam.data.lens = lens
    return cam


def shoot(cam, path, preview, res=(1800, 1200)):
    scene.camera = cam
    scene.render.resolution_x, scene.render.resolution_y = res
    scene.render.resolution_percentage = 55 if preview else 100
    if preview:
        scene.render.engine = "BLENDER_WORKBENCH"
        scene.display.shading.light = "STUDIO"
        scene.display.shading.color_type = "MATERIAL"
        scene.display.shading.show_shadows = True
        scene.display.shading.show_cavity = True
    else:
        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = 128
        scene.cycles.use_denoising = True
        scene.view_settings.view_transform = "AgX"
        scene.view_settings.look = "AgX - Medium High Contrast"
    scene.render.filepath = os.path.join(HERE, path)
    bpy.ops.render.render(write_still=True)
    print("Rendered", path)


def build_cookies():
    dough = material("Dough", (0.95, 0.70, 0.38), 0.7)
    bsdf = dough.node_tree.nodes["Principled BSDF"]
    if "Subsurface Weight" in bsdf.inputs:
        bsdf.inputs["Subsurface Weight"].default_value = 0.15
        bsdf.inputs["Subsurface Radius"].default_value = (1.0, 0.5, 0.25)
    for ship in ships:
        cookie = relief_mesh(ship["name"] + "_cookie", ship["base"], ship["details"],
                             DOUGH, -GROOVE, dough)
        rep = mesh_report(cookie)
        if rep["open"] or rep["pieces"] != 1 or rep["crossings"]:
            PROBLEMS.append(f"{ship['name']} cookie: open={rep['open']} pieces={rep['pieces']} "
                            f"crossings={rep['crossings']}")
        ship["cookie"] = cookie


bpy.ops.wm.save_as_mainfile(filepath=os.path.join(HERE, "space_cutters.blend"))

WANT_RENDER = "--render" in ARGS or "--preview" in ARGS
if WANT_RENDER or "--closeups" in ARGS:
    preview = "--preview" in ARGS or "--render" not in ARGS
    # The stamps are shown ridge-side up, the way they print, behind their cutters.
    place([[s["stamp"] for s in ships], [s["cutter"] for s in ships]])
    objs = [s[p] for s in ships for p in ("cutter", "stamp")]
    cx, cy, span = stage(objs, (0.08, 0.10, 0.16), HEIGHT * 0.3)
    hero = camera("Hero", (cx, cy - span * 1.3, span * 1.15), (cx, cy - span * 0.04, 2.0), lens=50)
    if WANT_RENDER:
        shoot(hero, "cutters_preview.png" if preview else "cutters.png", preview)
    if "--closeups" in ARGS:
        for s in ships:
            c = s["cutter"]
            loc = c.matrix_world.translation
            w = s["size2d"][0]
            cam = camera("Close_" + s["name"], (loc.x + w * 0.7, loc.y - w * 1.1, w * 0.75),
                         (loc.x, loc.y, HEIGHT * 0.3), lens=50)
            shoot(cam, f"closeup_{s['name']}_cutter.png", True, (1200, 900))
            st = s["stamp"].matrix_world.translation
            cam = camera("CloseStamp_" + s["name"], (st.x, st.y, 200), (st.x, st.y, 0),
                         ortho=max(s["size2d"]) * 1.1)
            shoot(cam, f"closeup_{s['name']}_stamp.png", True, (1200, 900))

    clear_stage()
    build_cookies()
    for s in ships:
        s["cutter"].hide_render = True
        s["stamp"].hide_render = True
        s["cutter"].hide_viewport = True
        s["stamp"].hide_viewport = True
    row1 = [s["cookie"] for s in ships[:3]]
    row2 = [s["cookie"] for s in ships[3:]]
    place([row1, row2] if row2 else [row1], gap=22, row_gap=22)
    cookies = [s["cookie"] for s in ships]
    cx, cy, span = stage(cookies, (0.035, 0.045, 0.09), DOUGH * 0.3, stars=True)
    hero = camera("CookieHero", (cx, cy - span * 1.15, span * 1.45), (cx, cy - span * 0.03, 1.0), lens=50)
    if WANT_RENDER:
        shoot(hero, "cookies_preview.png" if preview else "cookies.png", preview)
    if "--closeups" in ARGS:
        top = camera("CookieTop", (cx, cy, span), (cx, cy, 0), ortho=span * 1.1)
        shoot(top, "closeup_cookies_top.png", True, (1500, 1200))
    if PROBLEMS:
        print("\n=== Problems found while rendering ===")
        for line_ in PROBLEMS:
            print("  FAIL", line_)

if "--check" in ARGS and PROBLEMS:
    sys.exit(1)
