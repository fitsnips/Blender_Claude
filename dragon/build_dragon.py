"""Procedurally build a dragon-head bust in Blender.

Based on "Detailed stylized illustration of a fearsome dragon's head" by Promm Design
(Vecteezy, Free License with attribution):
https://www.vecteezy.com/vector-art/73442379

Usage:
    blender --background --python build_dragon.py -- [--render] [--preview]

Saves dragon.blend next to this script. --render also writes dragon.png (coloured,
three-quarter view) and dragon_ink.png (black-and-white profile in the style of the
illustration). --preview renders both quickly at low quality.
"""
import math
import os
import random
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

HERE = os.path.dirname(os.path.abspath(__file__))
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
random.seed(3)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

# The bust faces +X, Z is up, and the profile is seen from -Y (as in the drawing).
# One unit is about 1 cm of a 33 cm bust.


# ---------------------------------------------------------------- materials
def _nodes(mat):
    try:
        mat.use_nodes = True
    except AttributeError:
        pass
    return mat.node_tree.nodes, mat.node_tree.links


def mat_scales(name, dark, light, rough=0.45, scale=3.0, sheen=0.0):
    """Scaly skin: colour varies per scale (Voronoi cells) and darkens in the
    crevices between them."""
    mat = bpy.data.materials.new(name)
    nodes, links = _nodes(mat)
    bsdf = nodes.get("Principled BSDF")
    coord = nodes.new("ShaderNodeTexCoord").outputs["Object"]
    vor = nodes.new("ShaderNodeTexVoronoi")
    vor.inputs["Scale"].default_value = scale
    links.new(coord, vor.inputs["Vector"])
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*dark, 1)
    ramp.color_ramp.elements[1].color = (*light, 1)
    links.new(vor.outputs["Color"], ramp.inputs["Fac"])
    ao = nodes.new("ShaderNodeAmbientOcclusion")
    ao.inputs["Distance"].default_value = 0.4
    cav = nodes.new("ShaderNodeValToRGB")
    cav.color_ramp.elements[0].position = 0.35
    cav.color_ramp.elements[0].color = (0.05, 0.05, 0.05, 1)
    cav.color_ramp.elements[1].color = (1, 1, 1, 1)
    links.new(ao.outputs["AO"], cav.inputs["Fac"])
    mul = nodes.new("ShaderNodeMix")
    mul.data_type = "RGBA"
    mul.blend_type = "MULTIPLY"
    mul.inputs[0].default_value = 1.0
    links.new(ramp.outputs["Color"], next(s for s in mul.inputs if s.name == "A" and s.type == "RGBA"))
    links.new(cav.outputs["Color"], next(s for s in mul.inputs if s.name == "B" and s.type == "RGBA"))
    links.new(next(s for s in mul.outputs if s.type == "RGBA"), bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = rough
    if sheen:
        bsdf.inputs["Metallic"].default_value = sheen
    return mat


def mat_flat(name, color, rough=0.5, metallic=0.0, emission=None, strength=2.0):
    mat = bpy.data.materials.new(name)
    nodes, _ = _nodes(mat)
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metallic
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*emission, 1)
        bsdf.inputs["Emission Strength"].default_value = strength
    return mat


def mat_horn(name):
    """Horn: dark at the root, pale towards the tip, with fine streaks."""
    mat = bpy.data.materials.new(name)
    nodes, links = _nodes(mat)
    bsdf = nodes.get("Principled BSDF")
    coord = nodes.new("ShaderNodeTexCoord").outputs["Generated"]
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 6.0
    noise.inputs["Detail"].default_value = 8.0
    links.new(coord, noise.inputs["Vector"])
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.22, 0.18, 0.12, 1)
    ramp.color_ramp.elements[1].color = (0.62, 0.56, 0.44, 1)
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.35
    return mat


SKIN = mat_scales("Skin", (0.025, 0.06, 0.05), (0.10, 0.20, 0.13), scale=3.5, sheen=0.25)
BELLY = mat_scales("Belly", (0.36, 0.28, 0.14), (0.52, 0.42, 0.22), rough=0.4, scale=0.2)
PLATE = mat_scales("Plates", (0.03, 0.05, 0.04), (0.08, 0.14, 0.10), rough=0.3, scale=1.5,
                   sheen=0.4)
HORN = mat_horn("Horn")
TOOTH = mat_flat("Tooth", (0.85, 0.80, 0.66), rough=0.3)
MOUTH = mat_flat("Mouth", (0.05, 0.008, 0.008), rough=0.85)   # reads as a dark cavity
EYE = mat_flat("Eye", (0.9, 0.5, 0.05), rough=0.1, emission=(1.0, 0.45, 0.02), strength=4.0)
PUPIL = mat_flat("Pupil", (0.0, 0.0, 0.0), rough=0.1)
STONE = mat_flat("Plinth", (0.08, 0.075, 0.07), rough=0.7)


# ---------------------------------------------------------------- mesh helpers
def finish(obj, name, mat, smooth=True):
    obj.name = name
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    if smooth:
        bpy.ops.object.shade_smooth()
    obj.select_set(False)
    return obj


def mesh_object(name, verts, faces, mat, smooth=True):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    scene.collection.objects.link(obj)
    obj.data.materials.append(mat)
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
    return obj


def ellipsoid(name, loc, radii, mat, rot=(0, 0, 0), seg=32):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=seg, ring_count=seg // 2, location=loc,
                                         rotation=rot)
    o = bpy.context.active_object
    o.scale = radii
    return finish(o, name, mat)


def frames(pts, up=Vector((0, 1, 0))):
    """Tangent, side and normal per point. Side stays close to `up` (the bust's
    left-right axis), so cross-sections don't twist."""
    out = []
    for i, p in enumerate(pts):
        t = (pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]).normalized()
        side = (up - t * up.dot(t)).normalized()
        out.append((t, side, t.cross(side)))
    return out


def sweep(name, pts, radii, mat, ring=24):
    """Closed tube through pts; radii[i] = (across, in-plane) half-widths."""
    verts, faces = [], []
    for (p, (t, side, nrm), (a, b)) in zip(pts, frames(pts), radii):
        for k in range(ring):
            ang = 2 * math.pi * k / ring
            verts.append(p + side * math.cos(ang) * a + nrm * math.sin(ang) * b)
    n = len(pts)
    for i in range(n - 1):
        for k in range(ring):
            faces.append((i * ring + k, i * ring + (k + 1) % ring,
                          (i + 1) * ring + (k + 1) % ring, (i + 1) * ring + k))
    faces.append(tuple(reversed(range(ring))))
    faces.append(tuple(range((n - 1) * ring, n * ring)))
    return mesh_object(name, verts, faces, mat)


def bezier(p0, p1, p2, n):
    p0, p1, p2 = Vector(p0), Vector(p1), Vector(p2)
    return [(1 - t) ** 2 * p0 + 2 * (1 - t) * t * p1 + t ** 2 * p2
            for t in (i / (n - 1) for i in range(n))]


def catmull(points, per=8):
    """Smooth path through the control points."""
    pts = [Vector(p) for p in points]
    pts = [pts[0]] + pts + [pts[-1]]
    out = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        for j in range(per):
            t = j / per
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    out.append(pts[-2])
    return out


def spike(name, p0, p1, p2, r0, mat, flat=1.0, n=14, ring=12, power=1.0):
    """Tapered, curved cone from p0 through p1 to a point at p2. flat < 1
    squashes it across the bust (blades, plates)."""
    pts = bezier(p0, p1, p2, n)
    radii = []
    for i in range(n):
        r = max(r0 * (1 - i / (n - 1)) ** power, 0.004)
        radii.append((r * flat, r))
    return sweep(name, pts, radii, mat, ring=ring)


def mirrored(fn, name, npts, *args, **kw):
    """Build a part and its mirror image across the bust's centre plane; the
    first npts arguments are positions to mirror."""
    flipped = [(p[0], -p[1], p[2]) for p in args[:npts]] + list(args[npts:])
    return [fn(name + "_R", *args, **kw), fn(name + "_L", *flipped, **kw)]


def join(objs, name):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    objs[0].name = name
    objs[0].select_set(False)
    return objs[0]


# ---------------------------------------------------------------- head and neck mass
# Overlapping volumes, fused into one surface by voxel remeshing.
mass = [
    ellipsoid("cranium", (2.4, 0, 19.6), (4.8, 3.6, 3.9), SKIN),
    ellipsoid("cheek", (4.0, 0, 15.6), (3.6, 3.3, 3.2), SKIN),
    ellipsoid("snout", (9.4, 0, 16.0), (6.0, 2.35, 2.1), SKIN, rot=(0, 0.45, 0)),
    ellipsoid("nose", (14.0, 0, 14.3), (1.25, 1.5, 1.15), SKIN),
    ellipsoid("jaw", (8.3, 0, 11.9), (5.5, 1.95, 1.15), SKIN, rot=(0, 0.6, 0)),
    ellipsoid("chin", (11.6, 0, 9.6), (1.4, 1.35, 0.85), SKIN, rot=(0, 0.5, 0)),
    ellipsoid("jaw_hinge", (3.6, 0, 13.0), (2.6, 2.9, 2.4), SKIN),
]
mass += mirrored(ellipsoid, "brow", 1, (6.5, 2.4, 20.6), (3.1, 1.15, 1.05), SKIN,
                 rot=(0, 0.38, 0))
NECK_PATH = catmull([(2.0, 0, 17.5), (-0.6, 0, 14.6), (-3.6, 0, 11.0), (-5.3, 0, 6.6),
                     (-5.0, 0, 2.2), (-4.4, 0, -1.2)], per=6)
NECK_R = [(2.9 + 0.9 * i / (len(NECK_PATH) - 1), 3.2 + 1.2 * i / (len(NECK_PATH) - 1))
          for i in range(len(NECK_PATH))]
mass.append(sweep("neck", NECK_PATH, NECK_R, SKIN, ring=32))

body = join(mass, "Dragon")
body.data.remesh_voxel_size = 0.09
bpy.context.view_layer.objects.active = body
bpy.ops.object.voxel_remesh()
sm = body.modifiers.new("blend", "SMOOTH")
sm.factor, sm.iterations = 0.9, 12
bpy.ops.object.modifier_apply(modifier=sm.name)

# eye sockets carved under the brow, then the scales as real relief
for sy in (1, -1):
    sock = ellipsoid("socket", (7.15, 2.85 * sy, 19.45), (0.95, 0.7, 0.75), SKIN)
    mod = body.modifiers.new("socket", "BOOLEAN")
    mod.operation, mod.object, mod.solver = "DIFFERENCE", sock, "EXACT"
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.data.objects.remove(sock)

tex = bpy.data.textures.new("ScaleCells", "VORONOI")
tex.distance_metric = "DISTANCE"
tex.noise_scale = 0.42
tex.color_mode = "INTENSITY"
disp = body.modifiers.new("scales", "DISPLACE")
disp.texture = tex
disp.texture_coords = "GLOBAL"
disp.strength = -0.24
disp.mid_level = 0.0
bpy.context.view_layer.objects.active = body
bpy.ops.object.modifier_apply(modifier=disp.name)

# flat base where the neck meets the plinth
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, -5))
cutter = bpy.context.active_object
cutter.scale = (60, 60, 10)
mod = body.modifiers.new("base", "BOOLEAN")
mod.operation, mod.object, mod.solver = "DIFFERENCE", cutter, "EXACT"
bpy.context.view_layer.objects.active = body
bpy.ops.object.modifier_apply(modifier=mod.name)
bpy.data.objects.remove(cutter)
for p in body.data.polygons:
    p.use_smooth = True

# ---------------------------------------------------------------- eyes
for sy in (1, -1):
    ellipsoid("Eye", (7.05, 2.55 * sy, 19.45), (0.62, 0.62, 0.62), EYE)
    ellipsoid("Pupil", (7.35, 3.05 * sy, 19.4), (0.12, 0.1, 0.38), PUPIL)
    # heavy upper lid slanting down towards the snout: the scowl
    ellipsoid("Eyelid", (7.0, 2.72 * sy, 19.95), (1.05, 0.62, 0.5), SKIN, rot=(0, 0.42, 0))
    ellipsoid("Eyelid_low", (7.1, 2.7 * sy, 18.92), (0.95, 0.55, 0.32), SKIN, rot=(0, -0.15, 0))

# ---------------------------------------------------------------- mouth and teeth
MOUTH_C, MOUTH_TILT = Vector((8.4, 0, 13.4)), 0.52
# dark mouth interior, narrow enough to stay inside the jaws
ellipsoid("Mouth", tuple(MOUTH_C), (4.6, 0.95, 0.85), MOUTH, rot=(0, MOUTH_TILT, 0))
# Teeth are rooted on the real jaw surface: from a point in the mouth gap, cast
# a ray up to the upper gum (or down to the lower), and sink the root into it.
_bm = bmesh.new()
_bm.from_mesh(body.data)
_bm.transform(body.matrix_world)          # the body keeps an origin offset; rays are in world space
gum = BVHTree.FromBMesh(_bm)
_bm.free()
along = Vector((math.cos(MOUTH_TILT), 0, -math.sin(MOUTH_TILT)))   # back of mouth -> snout tip
up = Vector((math.sin(MOUTH_TILT), 0, math.cos(MOUTH_TILT)))       # towards the upper jaw
ROOT_DEPTH = 0.35


def rooted(name, p0, p1, p2, *args, **kw):
    """A spike whose base is moved onto the nearest point of the skin and sunk
    ROOT_DEPTH into it; the whole spike shifts with it, so its shape is kept."""
    p0, p1, p2 = Vector(p0), Vector(p1), Vector(p2)
    loc, normal, _, _ = gum.find_nearest(p0)
    shift = (loc - normal * ROOT_DEPTH) - p0
    p0, p1, p2 = p0 + shift, p1 + shift, p2 + shift
    if min(p.z for p in bezier(p0, p1, p2, 12)) - args[0] < 0.2:
        return None                   # would reach down into the plinth
    return spike(name, p0, p1, p2, *args, **kw)


def rooted_tooth(u, lateral, toward, length, radius):
    """Tooth whose root is embedded in the gum the ray from the mouth gap hits;
    None if the start point is inside the flesh (corner of the mouth)."""
    start = MOUTH_C + along * u + Vector((0, lateral, 0))
    hit, normal, _, _ = gum.ray_cast(start, toward, 4.0)
    if hit is None or normal.dot(toward) > 0:
        return None
    root = hit + toward * ROOT_DEPTH
    tip = hit - toward * length + along * 0.18 * length
    mid = hit - toward * length * 0.5 + along * 0.04 * length
    return spike("Tooth", root, mid, tip, radius, TOOTH, flat=0.8, n=8, ring=10)


teeth = []
for sy in (1, -1):
    for i in range(9):                    # upper row, fang at i == 6
        s = i / 8
        length = 0.8 + 0.35 * math.sin(math.pi * s) + (0.9 if i == 6 else 0)
        teeth.append(rooted_tooth(-3.2 + 7.6 * s, (1.5 - 0.75 * s) * sy, up, length,
                                  0.22 + 0.06 * (i == 6)))
    for i in range(8):                    # lower row, fang at i == 5
        s = i / 7
        length = 0.65 + 0.3 * math.sin(math.pi * s) + (0.7 if i == 5 else 0)
        teeth.append(rooted_tooth(-2.8 + 6.8 * s, (1.25 - 0.6 * s) * sy, -up, length,
                                  0.2 + 0.05 * (i == 5)))
teeth = [t for t in teeth if t]
print(f"Teeth rooted in the jaw: {len(teeth)} of 34")
EXPECTED = {"Teeth": len(teeth)}       # pieces each joined part must still contain
join(teeth, "Teeth")

# ---------------------------------------------------------------- horns
horns = []
horns += mirrored(spike, "Horn_main", 3, (1.4, 2.0, 21.6), (-0.2, 2.8, 28.4), (-6.2, 3.5, 31.6),
                  1.5, HORN, power=0.85, n=20)
horns += mirrored(spike, "Horn_back", 3, (-0.4, 2.4, 20.4), (-4.6, 3.0, 23.6), (-10.2, 3.4, 24.6),
                  1.0, HORN, power=0.85, n=18)
EXPECTED["Horns"] = len(horns)
join(horns, "Horns")

# ---------------------------------------------------------------- brow plates
plates = []
for sy in (1, -1):
    for i in range(5):
        s = i / 4
        bx, bz = 8.6 - 5.2 * s, 20.9 + 1.9 * s
        y = (2.35 + 0.25 * s) * sy
        L = 1.1 + 0.9 * s
        plates.append(rooted("BrowPlate", (bx, y, bz), (bx - 0.4 * L, y * 1.05, bz + 0.7 * L),
                            (bx - 1.0 * L, y * 1.08, bz + 1.0 * L), 0.55, PLATE, flat=0.3,
                            n=8, ring=10))

# ---------------------------------------------------------------- dorsal crest
# serrated blades along the top of the head and down the back of the neck
crest_line = [Vector((7.6, 0, 20.9)), Vector((5.0, 0, 22.6)), Vector((2.0, 0, 23.4))]
for i, (p, (t, side, nrm)) in enumerate(zip(NECK_PATH, frames(NECK_PATH))):
    if i % 2 == 0 and i > 2:
        crest_line.append(p - nrm * (NECK_R[i][1] - 0.2))
for i, p in enumerate(crest_line):
    s = i / (len(crest_line) - 1)
    size = 4.2 * (1 - s) ** 1.5 + 1.6 + random.uniform(-0.3, 0.3)
    # broad serrated blades raking up and back, away from the head
    nxt = crest_line[min(i + 1, len(crest_line) - 1)] - crest_line[max(i - 1, 0)]
    out = Vector((nxt.z, 0, -nxt.x)).normalized() * -1
    back = nxt.normalized()
    tip = p + out * size + back * size * 0.75
    plates.append(rooted("Crest", p - out * 0.4, p + out * size * 0.45 + back * size * 0.1, tip,
                        0.55 * size, PLATE, flat=0.16, n=10, ring=10, power=1.2))

# ---------------------------------------------------------------- mane and frill
# swept-back frill fanning out behind the jaw, like flames
for sy in (1, -1):
    for i in range(8):
        s = i / 7
        base = Vector((2.6 - 1.8 * s, 2.6 * sy, 18.0 - 6.0 * s))
        L = 4.6 + 1.8 * math.sin(math.pi * s) + random.uniform(-0.5, 0.5)
        d = Vector((-1.0, 0.32 * sy, -0.2 - 0.55 * s)).normalized()
        bend = Vector((0, 0, 0.9 - 0.4 * s))
        plates.append(rooted("Frill", base, base + d * L * 0.5 + bend, base + d * L, 0.75, PLATE,
                            flat=0.24, n=12, ring=10, power=1.15))
# mane spikes down the back of the neck
for i, (p, (t, side, nrm)) in enumerate(zip(NECK_PATH, frames(NECK_PATH))):
    if i < 3 or i % 2:
        continue
    s = i / (len(NECK_PATH) - 1)
    for sy in (1.1, -1.1):
        base = p - nrm * (NECK_R[i][1] - 0.5) + side * sy
        d = (-nrm * 1.0 + t * 0.7 + side * 0.25 * sy).normalized()
        L = 4.4 - 1.8 * s + random.uniform(-0.4, 0.4)
        if min(base.z, (base + d * L).z) < 0.8:    # would reach down into the plinth
            continue
        plates.append(rooted("Mane", base, base + d * L * 0.5 - t * 0.5, base + d * L, 0.6,
                            PLATE, flat=0.25, n=10, ring=10, power=1.15))

# ---------------------------------------------------------------- chin spikes
for i in range(6):
    s = i / 5
    base = Vector((6.5 + 4.6 * s, 0.0, 10.9 - 1.6 * s))
    for sy in (0.7, -0.7):
        b = base + Vector((0, sy * (1 - 0.5 * s), 0))
        L = 1.4 - 0.5 * s
        plates.append(rooted("Chin", b, b + Vector((-0.2, 0, -L * 0.6)),
                            b + Vector((-0.7, sy * 0.2, -L)), 0.3, PLATE, flat=0.5, n=8,
                            ring=8))
plates = [p for p in plates if p]
EXPECTED["Plates"] = len(plates)
join(plates, "Plates")

# ---------------------------------------------------------------- belly plates
# large chevron plates down the throat: each is two overlapping wings in a V
belly = []
for i, (p, (t, side, nrm)) in enumerate(zip(NECK_PATH, frames(NECK_PATH))):
    if i < 3 or i > len(NECK_PATH) - 2 or i % 2 == 0:
        continue
    b = NECK_R[i][1]
    w = NECK_R[i][0] * 0.62
    if p.z < 1.8:                     # would reach down into the plinth
        continue
    for sgn in (1, -1):
        c = p + nrm * (b - 0.2) + side * sgn * w * 0.45 + t * 0.35
        bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12)
        o = bpy.context.active_object
        wing = Matrix.Rotation(sgn * 0.5, 4, nrm)
        rot = wing @ Matrix((t, side, nrm)).transposed().to_4x4()
        size = Matrix.Diagonal((1.25, w * 0.75, 0.42, 1))
        o.matrix_world = Matrix.Translation(c) @ rot @ size
        belly.append(finish(o, "BellyPlate", BELLY))
EXPECTED["BellyPlates"] = len(belly)
join(belly, "BellyPlates")
# Nothing is cut to fit the plinth (booleans on these joined parts silently
# drop pieces): parts that would reach it are simply not made, the body is cut
# flat at z = 0 above, and validate() checks both.

# ---------------------------------------------------------------- plinth
bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=7.2, depth=1.6, location=(-4.2, 0, -0.8))
finish(bpy.context.active_object, "Plinth", STONE)
bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=7.8, depth=0.5, location=(-4.2, 0, -1.85))
finish(bpy.context.active_object, "PlinthFoot", STONE)

# ---------------------------------------------------------------- lights, cameras
world = bpy.data.worlds.new("World")
scene.world = world
wn, wl = _nodes(world)
wn["Background"].inputs["Color"].default_value = (0.02, 0.022, 0.025, 1)
wn["Background"].inputs["Strength"].default_value = 1.0


def area(name, loc, rot, energy, size, color=(1, 1, 1)):
    bpy.ops.object.light_add(type="AREA", location=loc, rotation=[math.radians(a) for a in rot])
    lt = bpy.context.active_object
    lt.name = name
    lt.data.energy, lt.data.size, lt.data.color = energy, size, color
    return lt


area("Key", (22, -26, 34), (50, 0, 40), 9000, 14, (1.0, 0.93, 0.85))
area("Fill", (-24, -30, 12), (80, 0, -40), 1800, 20, (0.75, 0.85, 1.0))
area("Rim", (-18, 26, 30), (-55, 0, -150), 7000, 10, (0.9, 0.95, 1.0))

target = bpy.data.objects.new("Target", None)
scene.collection.objects.link(target)
target.location = (2.0, 0, 15.0)


def camera(name, loc, lens):
    bpy.ops.object.camera_add(location=loc)
    c = bpy.context.active_object
    c.name = name
    c.data.lens = lens
    tc = c.constraints.new("TRACK_TO")
    tc.target, tc.track_axis, tc.up_axis = target, "TRACK_NEGATIVE_Z", "UP_Y"
    return c


cam_color = camera("Camera_3q", (30, -52, 22), 62)
cam_ink = camera("Camera_profile", (1.0, -95, 16.0), 78)
scene.camera = cam_color

scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.use_denoising = True
scene.render.resolution_x, scene.render.resolution_y = 1600, 1800
scene.view_settings.view_transform = "AgX"
scene.view_settings.look = "AgX - Medium High Contrast"

# ---------------------------------------------------------------- validation
# Hero renders hide small defects, so the geometry is checked on every build:
#   1. every separate piece (tooth, spike, horn, plate, eye...) touches or sinks
#      into the body: nothing floats;
#   2. nothing but the plinth goes below the plinth top, and everything resting
#      on it stands within its rim.
PLINTH_C, PLINTH_R = Vector((-4.2, 0.0)), 7.2
TOUCH = 0.02


def world_bmesh(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.transform(obj.matrix_world)
    return bm


def islands(bm):
    """Connected pieces of a mesh, as lists of vertex positions."""
    seen, out = set(), []
    for v in bm.verts:
        if v.index in seen:
            continue
        stack, part = [v], []
        seen.add(v.index)
        while stack:
            cur = stack.pop()
            part.append(cur.co.copy())
            for e in cur.link_edges:
                o = e.other_vert(cur)
                if o.index not in seen:
                    seen.add(o.index)
                    stack.append(o)
        out.append(part)
    return out


def validate():
    _b = world_bmesh(body)
    flesh = BVHTree.FromBMesh(_b)
    _b.free()
    problems, pieces = [], 0
    for o in scene.objects:
        if o.type != "MESH" or o is body or o.name.startswith("Plinth"):
            continue
        bm = world_bmesh(o)
        parts = islands(bm)
        if o.name in EXPECTED and len(parts) != EXPECTED[o.name]:
            problems.append(f"{o.name}: has {len(parts)} pieces, expected {EXPECTED[o.name]}")
        for part in parts:
            pieces += 1
            attached = False
            for co in part:
                loc, normal, _, dist = flesh.find_nearest(co)
                if loc is not None and (dist <= TOUCH or (co - loc).dot(normal) < 0):
                    attached = True
                    break
            if not attached:
                c = sum(part, Vector()) / len(part)
                problems.append(f"{o.name}: piece at ({c.x:.1f}, {c.y:.1f}, {c.z:.1f}) floats")
        bm.free()
    for o in scene.objects:
        if o.type != "MESH" or o.name.startswith("Plinth"):
            continue
        bm = world_bmesh(o)
        low = min(v.co.z for v in bm.verts)
        if low < -1e-4:
            problems.append(f"{o.name}: goes {-low:.2f} below the plinth top")
        outside = [v.co for v in bm.verts
                   if v.co.z < 0.05 and (v.co.xy - PLINTH_C).length > PLINTH_R]
        if outside:
            problems.append(f"{o.name}: {len(outside)} points rest beyond the plinth rim")
        bm.free()
    print(f"\n=== Validation: {pieces} attached pieces checked ===")
    for p in problems:
        print("  FAIL", p)
    print("  PASS: nothing floats, nothing passes through the plinth" if not problems
          else f"  {len(problems)} problem(s)")
    return problems


PROBLEMS = validate()

if "--preview" not in ARGS:
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(HERE, "dragon.blend"))
    print("Saved", os.path.join(HERE, "dragon.blend"))


def check_closeups():
    """Close-ups of the places hero shots hide: mouth, chin, base, back."""
    folder = os.path.join(HERE, "check")
    os.makedirs(folder, exist_ok=True)
    scene.cycles.samples = 32
    scene.render.resolution_percentage = 100
    size = scene.render.resolution_x, scene.render.resolution_y
    scene.render.resolution_x, scene.render.resolution_y = 900, 700
    shots = [("mouth", (12.0, -14.0, 12.5), (9.0, 0, 12.0), 50),
             ("chin", (16.0, -9.0, 6.0), (9.0, 0, 11.0), 45),
             ("throat", (14.0, -20.0, 8.0), (-1.0, 0, 8.0), 40),
             ("base_front", (8.0, -26.0, 3.0), (-4.2, 0, 0.5), 40),
             ("base_back", (-24.0, -14.0, 4.0), (-4.2, 0, 0.5), 40),
             ("horns_back", (-22.0, 18.0, 30.0), (-1.0, 0, 24.0), 45)]
    keep = target.location.copy(), cam_color.location.copy(), cam_color.data.lens
    for name, loc, look, lens in shots:
        target.location, cam_color.location, cam_color.data.lens = look, loc, lens
        scene.camera = cam_color
        scene.render.filepath = os.path.join(folder, name + ".png")
        bpy.ops.render.render(write_still=True)
    target.location, cam_color.location, cam_color.data.lens = keep
    scene.render.resolution_x, scene.render.resolution_y = size
    print("Close-up check renders in", folder)


if "--check" in ARGS:
    check_closeups()
    if PROBLEMS:
        sys.exit(1)


def ink_style():
    """Black-and-white engraving look: white matte everything, dark crevices,
    and Freestyle outlines."""
    def ink(name, cell_scale, use_ao=True, black=False):
        """White paper with a black outline round every scale cell, and solid
        black in deep crevices (under the brow, between spikes)."""
        mat = bpy.data.materials.new(name)
        nodes, links = _nodes(mat)
        nodes.remove(nodes.get("Principled BSDF"))
        out = nodes.get("Material Output")
        vor = nodes.new("ShaderNodeTexVoronoi")
        vor.feature = "DISTANCE_TO_EDGE"
        vor.inputs["Scale"].default_value = cell_scale or 1.0
        links.new(nodes.new("ShaderNodeTexCoord").outputs["Object"], vor.inputs["Vector"])
        lines = nodes.new("ShaderNodeMath")
        lines.operation = "GREATER_THAN"
        lines.inputs[1].default_value = 0.06 if cell_scale else -1.0   # None: no scale lines
        links.new(vor.outputs["Distance"], lines.inputs[0])
        ao = nodes.new("ShaderNodeAmbientOcclusion")
        ao.inputs["Distance"].default_value = 0.5
        shade = nodes.new("ShaderNodeMath")
        shade.operation = "GREATER_THAN"
        shade.inputs[1].default_value = 0.35 if use_ao else -1.0
        links.new(ao.outputs["AO"], shade.inputs[0])
        both = nodes.new("ShaderNodeMath")
        both.operation = "MULTIPLY"
        links.new(lines.outputs[0], both.inputs[0])
        links.new(shade.outputs[0], both.inputs[1])
        em = nodes.new("ShaderNodeEmission")
        if black:
            em.inputs["Color"].default_value = (0, 0, 0, 1)
        else:
            links.new(both.outputs[0], em.inputs["Color"])
        links.new(em.outputs[0], out.inputs["Surface"])
        return mat

    by_name = {"Dragon": ink("InkScales", 1.9),
               "Teeth": ink("InkTeeth", None, use_ao=False),
               "Horns": ink("InkHorns", None, use_ao=False),
               "Mouth": ink("InkMouth", None, black=True)}
    plain = ink("InkPlain", None, use_ao=False)
    white = ink("InkWhite", None, use_ao=False)
    black = ink("InkBlack", None, black=True)
    for o in scene.objects:
        if o.type != "MESH":
            continue
        mat = by_name.get(o.name)
        if mat is None:
            mat = (black if o.name.startswith("Pupil") else
                   white if o.name.startswith("Eye") and "lid" not in o.name else plain)
        o.data.materials.clear()
        o.data.materials.append(mat)
    wn["Background"].inputs["Color"].default_value = (1, 1, 1, 1)
    wn["Background"].inputs["Strength"].default_value = 1.0
    for name in ("Key", "Fill", "Rim"):
        bpy.data.objects[name].hide_render = True
    bpy.data.objects["Plinth"].hide_render = True
    bpy.data.objects["PlinthFoot"].hide_render = True
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.render.use_freestyle = True
    scene.render.line_thickness_mode = "ABSOLUTE"
    scene.render.line_thickness = 3.0
    fs = bpy.context.view_layer.freestyle_settings
    ls = fs.linesets[0] if fs.linesets else fs.linesets.new("Lines")
    ls.select_silhouette = ls.select_border = True
    ls.select_crease = False
    if ls.linestyle is None:
        ls.linestyle = bpy.data.linestyles.new("Ink")
    ls.linestyle.color = (0, 0, 0)
    ls.linestyle.thickness = 3.0
    scene.camera = cam_ink


if "--render" in ARGS or "--preview" in ARGS:
    quick = "--preview" in ARGS
    scene.cycles.samples = 24 if quick else 256
    scene.render.resolution_percentage = 40 if quick else 100
    scene.render.filepath = os.path.join(HERE, "dragon.png")
    bpy.ops.render.render(write_still=True)
    ink_style()
    scene.render.filepath = os.path.join(HERE, "dragon_ink.png")
    bpy.ops.render.render(write_still=True)
