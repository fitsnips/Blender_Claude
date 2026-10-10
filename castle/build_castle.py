"""Procedurally build a medieval castle in Blender.

Usage:
    blender --background --python build_castle.py -- [--render]

Saves castle.blend (and castle.png when --render is passed) next to this script.
"""
import math
import os
import random
import sys

import bmesh
import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
# --print builds a 3D-printable variant (used by print_castle.py): wider arrow
# slits, thicker floors and props, bevelled corbels, solid hall roofs, and a
# lowered portcullis standing on the floor. Nothing is saved or rendered.
PRINT = "--print" in sys.argv
SLIT_W = 0.3 if PRINT else 0.2
FLOOR_T = 0.25 if PRINT else 0.15
random.seed(7)

# ---------------------------------------------------------------- scene reset
def fresh_scene():
    """Start from an empty scene. Headless, reset Blender. With a window open
    (`blender --python ...`), a reset would tear down the window this script is
    running in and break bpy.context, so remove the existing data instead."""
    if bpy.app.background:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        return
    for coll in (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.lights,
                 bpy.data.cameras, bpy.data.textures, bpy.data.worlds, bpy.data.curves):
        for item in list(coll):
            coll.remove(item)


fresh_scene()
scene = bpy.context.scene


# ---------------------------------------------------------------- materials
def _nodes(mat):
    try:
        mat.use_nodes = True
    except AttributeError:
        pass
    return mat.node_tree.nodes, mat.node_tree.links


def mat_noise(name, dark, light, rough=0.9, scale=4.0, bump=0.4, voronoi=True):
    """Principled material with noise-driven colour variation and blocky bump."""
    mat = bpy.data.materials.new(name)
    nodes, links = _nodes(mat)
    bsdf = nodes.get("Principled BSDF")
    coord = nodes.new("ShaderNodeTexCoord")
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = scale
    noise.inputs["Detail"].default_value = 8.0
    links.new(coord.outputs["Object"], noise.inputs["Vector"])
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*dark, 1)
    ramp.color_ramp.elements[1].color = (*light, 1)
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = rough
    if bump:
        bump_node = nodes.new("ShaderNodeBump")
        bump_node.inputs["Strength"].default_value = bump
        if voronoi:
            vor = nodes.new("ShaderNodeTexVoronoi")
            vor.feature = "DISTANCE_TO_EDGE"
            vor.inputs["Scale"].default_value = 1.6
            links.new(coord.outputs["Object"], vor.inputs["Vector"])
            links.new(vor.outputs["Distance"], bump_node.inputs["Height"])
        else:
            links.new(noise.outputs["Fac"], bump_node.inputs["Height"])
        links.new(bump_node.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def _socket(sockets, name, kind):
    return next(x for x in sockets if x.name == name and x.type == kind)


def mat_masonry(name, dark, light, mortar, round_=False, block=(0.9, 0.42)):
    """Coursed ashlar: brick-pattern blocks with mortar joints and weathering.

    Flat walls use a tri-planar projection in object space; round_ variants
    unwrap around the object's vertical axis so courses wrap cleanly round
    towers.
    """
    mat = bpy.data.materials.new(name)
    nodes, links = _nodes(mat)
    bsdf = nodes.get("Principled BSDF")
    coord = nodes.new("ShaderNodeTexCoord").outputs["Object"]
    p = nodes.new("ShaderNodeSeparateXYZ")
    links.new(coord, p.inputs[0])
    n = nodes.new("ShaderNodeSeparateXYZ")
    links.new(nodes.new("ShaderNodeNewGeometry").outputs["Normal"], n.inputs[0])

    def op(kind, a, b=None):
        m = nodes.new("ShaderNodeMath")
        m.operation = kind
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                m.inputs[i].default_value = v
            else:
                links.new(v, m.inputs[i])
        return m.outputs[0]

    def vec(x, y):
        c = nodes.new("ShaderNodeCombineXYZ")
        links.new(x, c.inputs[0])
        links.new(y, c.inputs[1])
        return c.outputs[0]

    def bricks(v):
        b = nodes.new("ShaderNodeTexBrick")
        b.offset = 0.5
        b.inputs["Color1"].default_value = (*dark, 1)
        b.inputs["Color2"].default_value = (*light, 1)
        b.inputs["Mortar"].default_value = (*mortar, 1)
        b.inputs["Scale"].default_value = 1.0
        b.inputs["Mortar Size"].default_value = 0.025
        b.inputs["Mortar Smooth"].default_value = 0.3
        b.inputs["Brick Width"].default_value = block[0]
        b.inputs["Row Height"].default_value = block[1]
        links.new(v, b.inputs["Vector"])
        return b.outputs["Color"], b.outputs["Fac"]

    def blend(fac, a, b, kind):
        m = nodes.new("ShaderNodeMix")
        m.data_type = "RGBA" if kind == "RGBA" else "FLOAT"
        links.new(fac, m.inputs[0])
        links.new(a, _socket(m.inputs, "A", kind))
        links.new(b, _socket(m.inputs, "B", kind))
        return _socket(m.outputs, "Result", kind)

    nz = op("ABSOLUTE", n.outputs["Z"])
    top = op("GREATER_THAN", nz, 0.7)
    top_col, top_fac = bricks(vec(p.outputs["X"], p.outputs["Y"]))
    if round_:
        r = op("SQRT", op("ADD", op("MULTIPLY", p.outputs["X"], p.outputs["X"]),
                           op("MULTIPLY", p.outputs["Y"], p.outputs["Y"])))
        u = op("MULTIPLY", op("ARCTAN2", p.outputs["Y"], p.outputs["X"]), r)
        side_col, side_fac = bricks(vec(u, p.outputs["Z"]))
    else:
        side_x = op("GREATER_THAN", op("ABSOLUTE", n.outputs["X"]),
                    op("ABSOLUTE", n.outputs["Y"]))
        cx, fx = bricks(vec(p.outputs["Y"], p.outputs["Z"]))
        cy, fy = bricks(vec(p.outputs["X"], p.outputs["Z"]))
        side_col, side_fac = blend(side_x, cy, cx, "RGBA"), blend(side_x, fy, fx, "VALUE")
    col = blend(top, side_col, top_col, "RGBA")
    fac = blend(top, side_fac, top_fac, "VALUE")

    # broad weathering and per-stone grain
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 0.35
    noise.inputs["Detail"].default_value = 6.0
    links.new(coord, noise.inputs["Vector"])
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.72, 0.72, 0.70, 1)
    ramp.color_ramp.elements[1].color = (1.05, 1.03, 1.0, 1)
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    mul = nodes.new("ShaderNodeMix")
    mul.data_type = "RGBA"
    mul.blend_type = "MULTIPLY"
    mul.inputs[0].default_value = 1.0
    links.new(col, _socket(mul.inputs, "A", "RGBA"))
    links.new(ramp.outputs["Color"], _socket(mul.inputs, "B", "RGBA"))
    links.new(_socket(mul.outputs, "Result", "RGBA"), bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.88

    grain = nodes.new("ShaderNodeTexNoise")
    grain.inputs["Scale"].default_value = 18.0
    links.new(coord, grain.inputs["Vector"])
    height = op("ADD", op("MULTIPLY", op("SUBTRACT", 1.0, fac), 1.0),
                op("MULTIPLY", grain.outputs["Fac"], 0.15))
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.7
    bump.inputs["Distance"].default_value = 0.04
    links.new(height, bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def mat_flat(name, color, rough=0.5, metallic=0.0, emission=None):
    mat = bpy.data.materials.new(name)
    nodes, _ = _nodes(mat)
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metallic
    if emission:
        key = "Emission Color" if "Emission Color" in bsdf.inputs else "Emission"
        bsdf.inputs[key].default_value = (*emission, 1)
        bsdf.inputs["Emission Strength"].default_value = 3.0
    return mat


_GREY = ((0.20, 0.19, 0.17), (0.34, 0.32, 0.29), (0.42, 0.41, 0.38))
_SAND = ((0.27, 0.23, 0.17), (0.42, 0.37, 0.29), (0.50, 0.47, 0.42))
STONE = mat_masonry("Stone", *_GREY)
KEEP_STONE = mat_masonry("KeepStone", *_SAND, block=(1.0, 0.5))
# round towers get a material that unwraps the block courses around them
ROUND = {STONE: mat_masonry("StoneRound", *_GREY, round_=True),
         KEEP_STONE: mat_masonry("KeepStoneRound", *_SAND, round_=True, block=(1.0, 0.5))}
ROOF = mat_noise("RoofSlate", (0.10, 0.12, 0.20), (0.22, 0.25, 0.38), rough=0.6,
                 scale=12, bump=0.2, voronoi=False)
WOOD = mat_noise("Wood", (0.13, 0.07, 0.03), (0.30, 0.17, 0.08), scale=20,
                 bump=0.15, voronoi=False)
GRASS = mat_noise("Grass", (0.06, 0.16, 0.03), (0.20, 0.36, 0.08), scale=0.3,
                  bump=0.1, voronoi=False)
DIRT = mat_noise("Dirt", (0.18, 0.13, 0.08), (0.32, 0.25, 0.16), scale=1.5,
                 bump=0.2, voronoi=False)
LEAVES = mat_noise("Leaves", (0.03, 0.12, 0.03), (0.10, 0.28, 0.06), scale=3,
                   bump=0.3, voronoi=False)
WATER = mat_flat("Water", (0.04, 0.10, 0.12), rough=0.05)
DARK = mat_flat("Shadow", (0.01, 0.01, 0.01), rough=1.0)
IRON = mat_flat("Iron", (0.08, 0.08, 0.08), rough=0.4, metallic=1.0)
BANNER = mat_flat("Banner", (0.55, 0.03, 0.03), rough=0.8)
GOLD = mat_flat("Gold", (0.9, 0.65, 0.2), rough=0.3, metallic=1.0)
TORCH = mat_flat("TorchGlow", (1.0, 0.5, 0.1), emission=(1.0, 0.45, 0.1))


# ---------------------------------------------------------------- helpers
def finish(obj, name, mat, smooth=False):
    obj.name = name
    obj.data.materials.append(mat)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    if smooth:
        bpy.ops.object.shade_smooth()
    return obj


def box(name, loc, size, mat):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = bpy.context.active_object
    obj.scale = size
    return finish(obj, name, mat)


def cyl(name, loc, r, depth, mat, verts=32, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=depth,
                                        location=loc, rotation=rot)
    return finish(bpy.context.active_object, name, ROUND.get(mat, mat), smooth=verts > 12)


def cone(name, loc, r, depth, mat, verts=32):
    bpy.ops.mesh.primitive_cone_add(vertices=verts, radius1=r, depth=depth, location=loc)
    return finish(bpy.context.active_object, name, mat, smooth=True)


def cut(target, cutter):
    """Boolean-difference cutter out of target, then delete cutter."""
    mod = target.modifiers.new("cut", "BOOLEAN")
    mod.operation = "DIFFERENCE"
    mod.object = cutter
    mod.solver = "EXACT"
    mod.use_self = True
    mod.use_hole_tolerant = True
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.data.objects.remove(cutter, do_unlink=True)
    # keep curved walls smooth but the freshly cut openings crisp
    if any(p.use_smooth for p in target.data.polygons):
        bpy.ops.object.select_all(action="DESELECT")
        target.select_set(True)
        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(35))


def join(objs, name):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    objs[0].name = name
    return objs[0]


def arch_cutter(x, y, z_base, width, height, depth, axis="Y"):
    """Arch-shaped cutter (rectangle + half cylinder), opening along axis."""
    rect_h = height - width / 2
    if axis == "Y":
        b = box("cut", (x, y, z_base + rect_h / 2), (width, depth, rect_h), DARK)
        c = cyl("cut", (x, y, z_base + rect_h), width / 2, depth, DARK,
                rot=(math.pi / 2, 0, 0))
    else:
        b = box("cut", (x, y, z_base + rect_h / 2), (depth, width, rect_h), DARK)
        c = cyl("cut", (x, y, z_base + rect_h), width / 2, depth, DARK,
                rot=(0, math.pi / 2, 0))
    return join([b, c], "arch_cut")


def battlements_line(name, start, end, z, thick, mat, merlon=1.0, gap=0.8, h=1.2):
    """Row of merlons from start to end (2D points) at height z."""
    (x0, y0), (x1, y1) = start, end
    length = math.hypot(x1 - x0, y1 - y0)
    n = max(1, int((length + gap) / (merlon + gap)))
    step = length / n
    ang = math.atan2(y1 - y0, x1 - x0)
    parts = []
    for i in range(n):
        t = (i + 0.5) * step
        cx, cy = x0 + math.cos(ang) * t, y0 + math.sin(ang) * t
        bpy.ops.mesh.primitive_cube_add(size=1, location=(cx, cy, z + h / 2),
                                        rotation=(0, 0, ang))
        o = bpy.context.active_object
        o.scale = (merlon, thick, h)
        parts.append(finish(o, name, mat))
    return join(parts, name)


def battlements_ring(name, center, r, z, mat, count=14, h=1.2, depth=0.7):
    cx, cy = center
    parts = []
    for i in range(count):
        a = 2 * math.pi * i / count
        bpy.ops.mesh.primitive_cube_add(
            size=1, location=(cx + math.cos(a) * (r - depth / 2),
                              cy + math.sin(a) * (r - depth / 2), z + h / 2),
            rotation=(0, 0, a))
        o = bpy.context.active_object
        o.scale = (depth, 2 * math.pi * r / count * 0.55, h)
        parts.append(finish(o, name, mat))
    return join(parts, name)


def rbox(name, loc, size, mat, a=0.0):
    """Box rotated by angle a about Z (local X runs along direction a)."""
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=(0, 0, a))
    o = bpy.context.active_object
    o.scale = size
    return finish(o, name, mat)


def radial_cut(center, a, r0, r1, width, z0, h):
    """Box cutter running outward from r0 to r1 along angle a (doors, slits)."""
    cx, cy = center
    rm = (r0 + r1) / 2
    return rbox("cut", (cx + math.cos(a) * rm, cy + math.sin(a) * rm, z0 + h / 2),
                (r1 - r0, width, h), DARK, a)


def arrow_loops(center, r, wall, zs, angles):
    """Arrow loops cut right through a round wall: a narrow outer slit plus a
    wide splayed embrasure on the inside where the archer stands."""
    parts = []
    for z in zs:
        for a in angles:
            parts.append(radial_cut(center, a, r - wall - 0.2, r + 0.3, SLIT_W, z - 0.75, 1.5))
            parts.append(radial_cut(center, a, r - wall - 0.6, r - wall * 0.35, 0.9,
                                    z - 0.95, 1.9))
    return parts


def void_cyl(center, r, z0, z1):
    return cyl("cut", (*center, (z0 + z1) / 2), r, z1 - z0, DARK, verts=48)


def ladder(name, x, y, z0, z1, a=0.0):
    """Timber ladder; rungs run perpendicular to direction a."""
    parts = []
    for s in (-0.3, 0.3):
        parts.append(rbox(name, (x - math.sin(a) * s, y + math.cos(a) * s, (z0 + z1) / 2),
                          (0.08, 0.08, z1 - z0), WOOD, a))
    z = z0 + 0.3
    while z < z1 - 0.1:
        parts.append(rbox(name, (x, y, z), (0.05, 0.6, 0.05), WOOD, a))
        z += 0.35
    return join(parts, name)


def round_floor(name, center, ri, z, a=0.0, hatch=True):
    """Plank floor (top at z) on two beams socketed 0.3 m into the masonry.
    The hatch sits between the beams along direction a."""
    cx, cy = center
    floor = cyl(name, (cx, cy, z - FLOOR_T / 2), ri + 0.15, FLOOR_T, WOOD, verts=48)
    if hatch:
        hr = ri * 0.55
        cut(floor, rbox("cut", (cx + math.cos(a) * hr, cy + math.sin(a) * hr, z),
                        (1.0, 1.0, 1.0), DARK, a))
    for off in (-0.45, 0.45):
        lat = off * ri
        half = math.sqrt(ri ** 2 - lat ** 2) + 0.3
        rbox(name + "_beam", (cx - math.sin(a) * lat, cy + math.cos(a) * lat, z - 0.35),
             (2 * half, 0.3, 0.4), WOOD, a)
    return floor


def hollow_tower(name, center, r, h, wall, mat, floors=(), loops=(), loop_angles=(),
                 doors=(), extra=(), ledge=None, top=0.6, base=0.4, ladder_a=0.0,
                 ladders=True, roof_hatch=True):
    """Round tower built as a masonry shell: solid footing, timber floors on
    socketed beams, a stone top slab (the roof walk) and real openings.

    doors: (angle, z0[, reach]) radial doorways. extra: more cutter objects.
    ledge: (radius, thickness) corbelled walkway ring on top.
    Returns the interior void (center, ri, z0, z1) for cutting adjoining walls.
    """
    ri = r - wall
    t = cyl(name, (*center, h / 2), r, h, mat, verts=48)
    ledge_t = 0.0
    if ledge:
        ledge_t = ledge[1]
        if PRINT:   # 45-degree corbel so the walkway ring prints without support
            bpy.ops.mesh.primitive_cone_add(vertices=48, radius1=r - 0.05, radius2=ledge[0],
                                            depth=ledge_t, location=(*center, h + ledge_t / 2))
            rim = finish(bpy.context.active_object, name, ROUND.get(mat, mat), smooth=True)
        else:
            rim = cyl(name, (*center, h + ledge_t / 2), ledge[0], ledge_t, mat, verts=48)
        t = join([t, rim], name)
    if PRINT and top > 0:
        # 45-degree conical vault under the top slab: self-supporting when printed
        z1 = h - top
        zc = z1 - ri
        bpy.ops.mesh.primitive_cone_add(vertices=48, radius1=ri, radius2=0.2, depth=ri - 0.2,
                                        location=(*center, zc + (ri - 0.2) / 2))
        vault = finish(bpy.context.active_object, "cut", DARK)
        cutters = [void_cyl(center, ri, base, zc + 0.01), vault]
    else:
        cutters = [void_cyl(center, ri, base, h - top)]
    cutters += arrow_loops(center, r, wall, loops, loop_angles)
    for d in doors:
        a, z0 = d[0], d[1]
        reach = d[2] if len(d) > 2 else r + 0.3
        cutters.append(radial_cut(center, a, ri - 0.3, reach, 1.1, z0, 2.3))
    cutters += list(extra)
    # roof hatch sits opposite the floor hatches so its ladder stands on boards
    ra = ladder_a + math.pi
    hx, hy = center[0] + math.cos(ra) * 0.8, center[1] + math.sin(ra) * 0.8
    if roof_hatch:
        cutters.append(rbox("cut", (hx, hy, h + (ledge_t - top) / 2),
                            (0.9, 0.9, top + ledge_t + 0.6), DARK, ra))
    cut(t, join(cutters, "cut"))
    levels = [base] + list(floors)
    for k, z in enumerate(floors):
        round_floor(f"{name}_floor{k}", center, ri, z, ladder_a, hatch=ladders)
        if ladders:
            lr = ri * 0.55 + 0.3
            ladder(f"{name}_ladder{k}", center[0] + math.cos(ladder_a) * lr,
                   center[1] + math.sin(ladder_a) * lr, levels[k], z + 0.9, ladder_a)
    if roof_hatch:
        ladder(f"{name}_roof_ladder", hx + math.cos(ra) * 0.2,
               hy + math.sin(ra) * 0.2, levels[-1], h + ledge_t + 0.9, ra)
    return (center, ri, base, h - top)


def roof_cone(name, center, zt, rim_out, ro, h):
    """Hollow conical timber roof. The inside of the shell is sized so its base
    bears on the wall rim; crossed tie beams on the rim carry a king post."""
    r_bear = rim_out - 0.35
    roof = cone(name, (*center, zt + h / 2), ro, h, ROOF, verts=40)
    h_in = h * r_bear / ro
    cut(roof, cone("cut", (*center, zt - 0.3 + h_in / 2), r_bear, h_in, DARK, verts=40))
    for a in (0.0, math.pi / 2):
        rbox(name + "_tie", (*center, zt), (2 * rim_out - 0.2, 0.25, 0.3), WOOD, a)
    post_top = zt - 0.3 + h_in - 0.3
    cyl(name + "_kingpost", (*center, (zt + post_top) / 2), 0.15, post_top - zt, WOOD,
        verts=8)
    return zt + h


def roof_drum(name, center, z0, r, h, mat, door_a, hatch=None):
    """Hollow stone drum (stair head) standing on a tower roof with a doorway
    out onto the surrounding wall-walk."""
    d = cyl(name, (*center, z0 + h / 2), r, h, mat, verts=40)
    cutters = [void_cyl(center, r - 0.45, z0 + 0.1, z0 + h + 0.1),
               radial_cut(center, door_a, r - 0.8, r + 0.3, 1.0, z0 + 0.1, 2.2)]
    if hatch:
        cutters.append(rbox("cut", (hatch[0], hatch[1], z0), (0.9, 0.9, 1.0), DARK, hatch[2]))
    cut(d, join(cutters, "cut"))
    return z0 + h


def flag(name, base, pole_h=5.0, wave=0.0):
    x, y, z = base
    pole = cyl(name + "_pole", (x, y, z + pole_h / 2), 0.08, pole_h, WOOD, verts=8)
    knob = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.18, location=(x, y, z + pole_h))
    finish(bpy.context.active_object, name + "_knob", GOLD, smooth=True)
    bpy.ops.mesh.primitive_plane_add(size=1, location=(x + 1.2, y, z + pole_h - 0.9),
                                     rotation=(math.pi / 2, 0, wave))
    cloth = bpy.context.active_object
    cloth.scale = (2.4, 1.4, 1)
    finish(cloth, name + "_banner", BANNER)
    # gentle ripple
    sub = cloth.modifiers.new("sub", "SUBSURF")
    sub.levels = sub.render_levels = 3
    sub.subdivision_type = "SIMPLE"
    wav = cloth.modifiers.new("wave", "WAVE")
    wav.use_x, wav.use_y = True, False
    wav.height, wav.width, wav.speed = 0.15, 0.9, 0.0
    wav.use_normal = True
    return pole


# ---------------------------------------------------------------- terrain + moat
WALL = 20.0          # half-size of curtain wall square
WALL_H = 8.0
WALL_T = 3.0
MOAT_IN, MOAT_OUT = 24.0, 30.0

ground = box("Ground", (0, 0, -2), (2000, 2000, 4), GRASS)
trench = box("trench", (0, 0, -1), (2 * MOAT_OUT, 2 * MOAT_OUT, 4), DARK)
inner = box("inner", (0, 0, -1), (2 * MOAT_IN, 2 * MOAT_IN, 6), DARK)
cut(trench, inner)
cut(ground, trench)
box("MoatBed", (0, 0, -2.9), (2 * MOAT_OUT, 2 * MOAT_OUT, 0.2), DIRT)
bpy.ops.mesh.primitive_plane_add(size=2 * MOAT_OUT, location=(0, 0, -0.9))
water = finish(bpy.context.active_object, "Water", WATER)
# courtyard dirt
box("Courtyard", (0, 0, 0.01), (2 * WALL - 2, 2 * WALL - 2, 0.02), DIRT)

# ---------------------------------------------------------------- curtain walls
walls = []
for name, loc, size in [
    ("Wall_N", (0, WALL, WALL_H / 2), (2 * WALL, WALL_T, WALL_H)),
    ("Wall_S", (0, -WALL, WALL_H / 2), (2 * WALL, WALL_T, WALL_H)),
    ("Wall_E", (WALL, 0, WALL_H / 2), (WALL_T, 2 * WALL, WALL_H)),
    ("Wall_W", (-WALL, 0, WALL_H / 2), (WALL_T, 2 * WALL, WALL_H)),
]:
    walls.append(box(name, loc, size, STONE))
# gate passage through the south wall
cut(walls[1], arch_cutter(0, -WALL, -0.1, 4.0, 6.0, WALL_T + 6))

# battlements: outer and inner parapet rows on each wall
for side, (a, b) in {
    "N": ((-WALL, WALL), (WALL, WALL)),
    "S": ((-WALL, -WALL), (WALL, -WALL)),
    "E": ((WALL, -WALL), (WALL, WALL)),
    "W": ((-WALL, -WALL), (-WALL, WALL)),
}.items():
    nx = 1 if side == "E" else -1 if side == "W" else 0
    ny = 1 if side == "N" else -1 if side == "S" else 0
    off = WALL_T / 2 - 0.25
    battlements_line(f"Battlement_{side}",
                     (a[0] + nx * off, a[1] + ny * off),
                     (b[0] + nx * off, b[1] + ny * off), WALL_H, 0.5, STONE)
    # low inner parapet
    box(f"Parapet_{side}", ((a[0] + b[0]) / 2 - nx * off, (a[1] + b[1]) / 2 - ny * off,
                            WALL_H + 0.4),
        (abs(b[0] - a[0]) + 0.5 if ny else 0.5, abs(b[1] - a[1]) + 0.5 if nx else 0.5, 0.8),
        STONE)

# ---------------------------------------------------------------- corner towers
# Every tower is a hollow masonry shell: a ground-floor door to the courtyard,
# timber floors with ladder hatches, doors out onto the wall-walks, and a stone
# roof walk ringed by battlements with a stair-head drum and conical roof.
WALK_Z = WALL_H                      # wall-walk level (top of curtain walls)
TOWER_R, TOWER_H, TOWER_WALL = 3.6, 14.0, 1.1
LEDGE_R, LEDGE_T = TOWER_R + 0.5, 0.6
DRUM_R, DRUM_H = 2.0, 3.4            # leaves a 1.4 m walk behind the merlons
voids = []                           # tower interiors, cut out of curtain walls
wall_door_specs = []                 # doorways that also pierce the wall-walk
for i, (sx, sy) in enumerate([(-1, -1), (1, -1), (1, 1), (-1, 1)]):
    c = (sx * WALL, sy * WALL)
    out = math.atan2(sy, sx)
    inward = out + math.pi
    lad = out + math.pi / 2
    ri = TOWER_R - TOWER_WALL
    walk_doors = [(math.atan2(0, -sx), WALK_Z), (math.atan2(-sy, 0), WALK_Z)]
    for a, z in walk_doors:
        wall_door_specs.append((c, a, ri - 0.3, TOWER_R + 0.3, 1.1, z, 2.3))
    voids.append(hollow_tower(
        f"Tower_{i}", c, TOWER_R, TOWER_H, TOWER_WALL, STONE,
        floors=(4.0, WALK_Z), loops=(5.6, 9.6),
        loop_angles=[out + math.radians(d) for d in (-60, -20, 20, 60)],
        doors=[(inward, 0.4)] + walk_doors,
        ledge=(LEDGE_R, LEDGE_T), ladder_a=lad))
    roof_walk = TOWER_H + LEDGE_T
    battlements_ring(f"Tower_{i}_merlons", c, LEDGE_R, roof_walk, STONE, count=16)
    ra = lad + math.pi                # roof hatch side (see hollow_tower)
    hatch = (c[0] + math.cos(ra) * 0.8, c[1] + math.sin(ra) * 0.8, ra)
    zt = roof_drum(f"Tower_{i}_drum", c, roof_walk, DRUM_R, DRUM_H, STONE, inward, hatch)
    apex = roof_cone(f"Tower_{i}_roof", c, zt, DRUM_R, DRUM_R + 0.6, 6.0)
    flag(f"Tower_{i}_flag", (*c, apex - 0.1), pole_h=3.0, wave=random.uniform(-0.3, 0.3))

# ---------------------------------------------------------------- gatehouse
GH_Y = -WALL - 1.0
GH_H = 12.0
GH_CY = GH_Y + 1.0                   # gatehouse centre line
CH_X, CH_Y0, CH_Y1 = 2.5, GH_Y - 1.5, GH_Y + 3.5
CH_Z0, CH_Z1 = WALK_Z, GH_H - 0.8    # portcullis chamber above the vaulted passage
GT_Y, GT_R, GT_H, GT_WALL = GH_Y - 0.3, 2.6, GH_H + 3.0, 0.9
PORT_Y = GH_Y - 1.6


def chamber_void():
    return box("cut", (0, (CH_Y0 + CH_Y1) / 2, (CH_Z0 + CH_Z1) / 2),
               (2 * CH_X, CH_Y1 - CH_Y0, CH_Z1 - CH_Z0), DARK)


def gate_doors(sx, grow=0.0):
    """Gate-tower doorways: to the gate passage, to the portcullis chamber and
    out onto the south wall-walk. grow enlarges the copy cut into a neighbouring
    solid so the two door reveals are never coplanar (keeps the union clean)."""
    w, h = 1.0 + grow, 2.3 + grow
    return [box("cut", (sx * 2.85, GT_Y, 0.4 + 1.15), (2.1, w, h), DARK),
            box("cut", (sx * 3.1, GT_Y, WALK_Z + 1.15), (1.6, w, h), DARK),
            box("cut", (sx * 6.95, -WALL, WALK_Z + 1.15), (1.9, w, h), DARK)]


gate_block = box("Gatehouse", (0, GH_CY, GH_H / 2), (9, 7, GH_H), STONE)
gcut = [arch_cutter(0, GH_CY, -0.1, 4.0, 6.0, 12),
        chamber_void(),
        arch_cutter(0, GH_CY - 3.5, CH_Z0 + 0.6, 1.0, 2.0, 2.5),
        arch_cutter(0, GH_CY + 3.5, CH_Z0 + 0.6, 1.0, 2.0, 2.5),
        box("cut", (0, PORT_Y, 4.05), (4.4, 0.4, 8.3), DARK),          # portcullis slot
        box("cut", (-1.5, GH_CY + 1.5, GH_H - 0.4), (1.0, 1.0, 1.4), DARK)]  # roof hatch
for sx in (-1, 1):
    gcut.append(void_cyl((sx * 5.2, GT_Y), GT_R - GT_WALL, 0.4, GT_H - 0.6))
    gcut += gate_doors(sx, grow=0.02)
cut(gate_block, join(gcut, "cut"))
ladder("Gatehouse_roof_ladder", -1.2, GH_CY + 1.5, CH_Z0, GH_H + 0.9)
battlements_line("Gatehouse_merlons_front", (-4.5, GH_Y - 2.25), (4.5, GH_Y - 2.25),
                 GH_H, 0.5, STONE)
battlements_line("Gatehouse_merlons_back", (-4.5, GH_Y + 4.25), (4.5, GH_Y + 4.25),
                 GH_H, 0.5, STONE)
for sx in (-1, 1):
    c = (sx * 5.2, GT_Y)
    voids.append(hollow_tower(
        f"GateTower_{sx}", c, GT_R, GT_H, GT_WALL, STONE,
        floors=(3.5, WALK_Z, 11.5), loops=(5.0, 9.5, 13.0),
        loop_angles=[-math.pi / 2, -math.pi / 2 + sx * 0.8, math.atan2(-0.35, sx)],
        extra=gate_doors(sx), ledge=(GT_R + 0.4, 0.5), ladder_a=math.pi / 2))
    battlements_ring(f"GateTower_{sx}_merlons", c, GT_R + 0.4, GT_H + 0.5, STONE, count=12)

# portcullis, half raised in its slot and hung from a windlass in the chamber
bars = []
if PRINT:   # lowered onto the floor, thick bars keyed into the slot walls
    for k in range(7):
        bars.append(cyl("bar", (-1.8 + k * 0.6, PORT_Y, 2.8), 0.13, 5.6, IRON, verts=8))
    for k in range(8):
        bars.append(cyl("bar", (0, PORT_Y, 0.6 + k * 0.7), 0.13, 4.5, IRON, verts=8,
                        rot=(0, math.pi / 2, 0)))
else:
    for k in range(7):
        bars.append(cyl("bar", (-1.8 + k * 0.6, PORT_Y, 5.0), 0.07, 5.2, IRON, verts=8))
    for k in range(7):
        bars.append(cyl("bar", (0, PORT_Y, 2.8 + k * 0.7), 0.06, 4.2, IRON, verts=8,
                        rot=(0, math.pi / 2, 0)))
join(bars, "Portcullis")
for sx in (-1, 1):
    box("Windlass_post", (sx * 2.3, PORT_Y + 0.45, CH_Z0 + 1.0), (0.3, 0.3, 2.0), WOOD)
    cyl("Portcullis_chain", (sx * 1.5, PORT_Y + 0.15, (7.6 + CH_Z0 + 1.6) / 2), 0.04,
        CH_Z0 + 1.6 - 7.6, IRON, verts=6)
cyl("Windlass", (0, PORT_Y + 0.45, CH_Z0 + 1.6), 0.3, 4.6, WOOD, verts=16,
    rot=(0, math.pi / 2, 0))
box("GatePaving", (0, GH_CY, 0.03), (4, 9, 0.04), STONE)

# drawbridge over the moat
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, (GH_Y - 2.5 - MOAT_OUT) / 2 - 0.5, -0.05))
bridge = bpy.context.active_object
bridge.scale = (4.4, MOAT_OUT - abs(GH_Y - 2.5) + 2, 0.3)
finish(bridge, "Drawbridge", WOOD)
for sx in (-1, 1):
    bpy.ops.mesh.primitive_cylinder_add(vertices=6, radius=0.05, depth=1,
                                        location=(0, 0, 0))
    chain = bpy.context.active_object
    p0 = (sx * 2.0, MOAT_OUT * -1 + 1.0, 0.1)
    p1 = (sx * 2.6, GH_Y - 2.3, 9.0)
    d = [p1[j] - p0[j] for j in range(3)]
    ln = math.sqrt(sum(v * v for v in d))
    chain.location = [(p0[j] + p1[j]) / 2 for j in range(3)]
    chain.scale = (1, 1, ln)
    chain.rotation_euler = (-math.acos(d[2] / ln), 0, 0)
    finish(chain, f"Chain_{sx}", IRON)

# torches either side of the gate
for sx in (-1, 1):
    box(f"TorchBracket_{sx}", (sx * 2.8, GH_Y - 2.7, 4.5), (0.15, 0.4, 0.15), IRON)
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.22, location=(sx * 2.8, GH_Y - 2.9, 4.8))
    finish(bpy.context.active_object, f"TorchFlame_{sx}", TORCH, smooth=True)
    bpy.ops.object.light_add(type="POINT", location=(sx * 2.8, GH_Y - 3.3, 4.9))
    lt = bpy.context.active_object
    lt.data.energy = 300
    lt.data.color = (1.0, 0.55, 0.2)

# ---------------------------------------------------------------- keep
# Hollow keep: storage at ground level, a raised entrance hall, great hall and
# solar on timber floors carried by beams and a central stone pier, and a stone
# roof slab you can walk on. Corner stair turrets open off every floor.
KX, KY = 0.0, 6.0
KW, KH, KT = 13.0, 20.0, 1.6
KIN = KW / 2 - KT                    # interior half-width
K_FLOORS = (3.0, 8.6, 15.0)
K_ROOF = KH - 0.8                    # underside of the roof slab
K_HATCH = (KX - KIN + 1.2, KY + KIN * 0.25)
TURRET_R, TURRET_WALL, TURRET_H = 2.3, 0.8, KH + 4.0
TURRET_DOOR_Z = K_FLOORS + (KH,)
TURRETS = [(sx, sy, (KX + sx * KW / 2, KY + sy * KW / 2))
           for sx, sy in [(-1, -1), (1, -1), (1, 1), (-1, 1)]]


def keep_void():
    return box("cut", (KX, KY, (0.4 + K_ROOF) / 2), (2 * KIN, 2 * KIN, K_ROOF - 0.4), DARK)


def turret_cutters(doors=True):
    parts = []
    for sx, sy, c in TURRETS:
        parts.append(void_cyl(c, TURRET_R - TURRET_WALL, 0.4, TURRET_H + 1.5))
        if doors:
            parts += [radial_cut(c, math.atan2(-sy, -sx), TURRET_R - TURRET_WALL - 0.3, 3.6,
                                 1.1, z, 2.3) for z in TURRET_DOOR_Z]
    return parts


keep = box("Keep", (KX, KY, KH / 2), (KW, KW, KH), KEEP_STONE)
kcut = [keep_void(), arch_cutter(KX, KY - KW / 2, K_FLOORS[0], 2.2, 3.6, 4.0),
        box("cut", (*K_HATCH, K_ROOF), (1.0, 1.0, 2.0), DARK)]
for face in range(4):
    a = face * math.pi / 2
    nx, ny = math.sin(a), -math.cos(a)
    tx, ty = math.cos(a), math.sin(a)
    axis = "Y" if face % 2 == 0 else "X"
    for off in (-3.5, 0.0, 3.5):
        x, y = KX + nx * (KW / 2) + tx * off, KY + ny * (KW / 2) + ty * off
        if off:   # narrow lights for the entrance hall
            kcut.append(arch_cutter(x, y, K_FLOORS[0] + 1.2, 0.5, 1.5, 4.0, axis=axis))
        for z in (K_FLOORS[1] + 0.4, K_FLOORS[2] + 0.5):
            if face == 3 and z < K_FLOORS[2] and off == 0.0:
                continue
            kcut.append(arch_cutter(x, y, z, 1.0, 2.4, 4.0, axis=axis))
kcut += turret_cutters()
cut(keep, join(kcut, "cut"))

plinth = box("Keep_plinth", (KX, KY, 1.0), (KW + 1.2, KW + 1.2, 2.0), STONE)
cut(plinth, join([keep_void()] + turret_cutters(), "cut"))
for z in (7.0, 14.0):
    course = box(f"Keep_course_{int(z)}", (KX, KY, z), (KW + 0.3, KW + 0.3, 0.35), STONE)
    cut(course, join([keep_void()] + turret_cutters(), "cut"))
cornice = box("Keep_cornice", (KX, KY, KH - 0.2), (KW + 1.0, KW + 1.0, 0.6), KEEP_STONE)
cut(cornice, join([box("cut", (KX, KY, KH), (KW - 0.4, KW - 0.4, 2.0), DARK)]
                  + turret_cutters(), "cut"))
merlons = []
for (a, b) in [((-KW / 2, -KW / 2), (KW / 2, -KW / 2)), ((KW / 2, -KW / 2), (KW / 2, KW / 2)),
               ((KW / 2, KW / 2), (-KW / 2, KW / 2)), ((-KW / 2, KW / 2), (-KW / 2, -KW / 2))]:
    merlons.append(battlements_line("Keep_merlons", (KX + a[0] * 1.02, KY + a[1] * 1.02),
                                    (KX + b[0] * 1.02, KY + b[1] * 1.02), KH, 0.7,
                                    KEEP_STONE))
cut(join(merlons, "Keep_merlons"), join(turret_cutters(doors=False), "cut"))

# structure inside: central pier, floors on beams, ladders between hatches
box("Keep_pier", (KX, KY, (0.4 + K_ROOF) / 2), (1.2, 1.2, K_ROOF - 0.4), STONE)
levels = (0.4,) + K_FLOORS
for k, z in enumerate(K_FLOORS):
    slab = box(f"Keep_floor{k}", (KX, KY, z - FLOOR_T / 2),
               (2 * KIN + 0.3, 2 * KIN + 0.3, FLOOR_T), WOOD)
    cut(slab, box("cut", (*K_HATCH, z), (1.0, 1.0, 1.0), DARK))
    for dy in (-KIN * 0.5, 0.0, KIN * 0.5):
        box(f"Keep_floor{k}_beam", (KX, KY + dy, z - 0.35), (2 * KIN + 0.4, 0.3, 0.4), WOOD)
    ladder(f"Keep_ladder{k}", K_HATCH[0] - 0.3, K_HATCH[1], levels[k], z + 0.9)
ladder("Keep_roof_ladder", K_HATCH[0] - 0.3, K_HATCH[1], K_FLOORS[-1], KH + 0.9)
# entrance: stone steps from the courtyard, door standing open into the hall
box("Keep_door", (KX - 1.05, KY - KW / 2 + KT + 1.1, K_FLOORS[0] + 1.3), (0.12, 2.2, 2.6),
    WOOD)
for s in range(6):
    box(f"Keep_step_{s}", (KX, KY - KW / 2 - 3.05 + s * 0.55, 0.25 * (s + 1)),
        (2.6, 0.6, 0.5 * (s + 1)), STONE)

# corner stair turrets, full height from the ground, open onto every floor and
# the keep roof, capped by hollow conical roofs resting on the turret walls
for n, (sx, sy, c) in enumerate(TURRETS):
    out = math.atan2(sy, sx)
    hollow_tower(f"Keep_turret_{n}", c, TURRET_R, TURRET_H, TURRET_WALL, KEEP_STONE,
                 floors=K_FLOORS + (KH,), loops=(5.0, 11.0, 17.0, 22.0), loop_angles=[out],
                 doors=[(out + math.pi, z, 3.6) for z in TURRET_DOOR_Z],
                 top=0.0, ladders=False, roof_hatch=False)
    base = cyl(f"Keep_turret_{n}_base", (*c, 1.0), TURRET_R + 0.6, 2.0, STONE, verts=48)
    cut(base, void_cyl(c, TURRET_R - TURRET_WALL, 0.4, 2.5))
    roof_cone(f"Keep_turret_{n}_roof", c, TURRET_H, TURRET_R, TURRET_R + 0.4, 5.0)
flag("Keep_flag", (KX, KY, KH), pole_h=8.0)

# ---------------------------------------------------------------- curtain wall openings
# tower interiors and their doorways run through where the walls meet them
def wall_cutters():
    parts = [void_cyl(c, ri, z0, z1) for c, ri, z0, z1 in voids]
    parts.append(chamber_void())
    parts += [radial_cut(*s) for s in wall_door_specs]
    for sx in (-1, 1):
        parts += gate_doors(sx)
    return join(parts, "cut")


for o in [o for o in bpy.data.objects
          if o.name.split("_")[0] in ("Wall", "Battlement", "Parapet")]:
    cut(o, wall_cutters())

# stone stair from the courtyard up to the east wall-walk
STEP_RISE, STEP_RUN = 0.25, 0.35
stair_x = WALL - WALL_T / 2 - 0.7      # 1.6 m wide, bonded 0.15 m into the wall
steps = []
for s in range(int(WALK_Z / STEP_RISE)):
    top = (s + 1) * STEP_RISE
    steps.append(box("Stair_E", (stair_x, -8.0 + (s + 0.5) * STEP_RUN, top / 2),
                     (1.6, STEP_RUN, top), STONE))
join(steps, "Stair_E")
cut(bpy.data.objects["Parapet_E"],
    box("cut", (WALL - WALL_T / 2 + 0.25, 2.5, WALK_Z + 0.5), (0.8, 1.6, 1.4), DARK))

# ---------------------------------------------------------------- courtyard buildings
def gable(name, cx, cy, w, l, z0, rise, mat):
    hw, hl = w / 2, l / 2
    verts = [(-hw, -hl, 0), (hw, -hl, 0), (0, -hl, rise),
             (-hw, hl, 0), (hw, hl, 0), (0, hl, rise)]
    faces = [(0, 1, 2), (3, 5, 4), (0, 3, 4, 1), (1, 4, 5, 2), (2, 5, 3, 0)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(obj)
    obj.location = (cx, cy, z0)
    obj.data.materials.append(mat)
    return obj


# timber halls along the west wall: hollow, with a door and windows facing the
# courtyard, tie beams and king posts carrying a ridge beam and a hollow roof
HALL_W, HALL_L, HALL_H = 5.0, 6.5, 4.0
for i, y in enumerate((-10.0, -2.0)):
    hx = -WALL + WALL_T / 2 + HALL_W / 2
    hall = box(f"Hall_{i}", (hx, y, HALL_H / 2), (HALL_W, HALL_L, HALL_H), DIRT)
    face = hx + HALL_W / 2
    cut(hall, join([box("cut", (hx, y, HALL_H / 2), (HALL_W - 0.6, HALL_L - 0.6, HALL_H + 1), DARK),
                    box("cut", (face, y, 1.15), (1.0, 1.4, 2.3), DARK),
                    box("cut", (face, y + 2.0, 2.3), (1.0, 0.9, 0.9), DARK),
                    box("cut", (face, y - 2.0, 2.3), (1.0, 0.9, 0.9), DARK)], "cut"))
    rise = 2.4
    eave = 0.0 if PRINT else 1.0      # no overhanging eaves on the printed model
    roof = gable(f"Hall_{i}_roof", hx, y, HALL_W + eave, HALL_L + 0.1 * eave, HALL_H, rise, WOOD)
    hw_in = HALL_W / 2 - 0.2 + 0.1 * (HALL_W + 1.0) / 2 / rise
    if not PRINT:   # printed solid: the hall ceiling then bridges flat
        cut(roof, gable("cut", hx, y, 2 * hw_in, HALL_L - 0.5, HALL_H - 0.1,
                        hw_in * rise / ((HALL_W + 1.0) / 2), DARK))
    ridge_z = HALL_H - 0.1 + hw_in * rise / ((HALL_W + 1.0) / 2) - 0.25
    box(f"Hall_{i}_ridge", (hx, y, ridge_z), (0.2, HALL_L - 0.5, 0.2), WOOD)
    for dy in (-2.0, 0.0, 2.0):
        box(f"Hall_{i}_tie", (hx, y + dy, HALL_H - 0.15), (HALL_W - 0.2, 0.2, 0.3), WOOD)
        box(f"Hall_{i}_kingpost", (hx, y + dy, (HALL_H + ridge_z) / 2), (0.18, 0.18,
            ridge_z - HALL_H), WOOD)

# well: a real shaft down through the ground to water, with a stone lining
WELL = (10.0, -8.0)
WELL_T = 0.3 if PRINT else 0.15
well = cyl("Well", (*WELL, 0.5), 1.2, 1.0, STONE)
cut(well, void_cyl(WELL, 0.85, -0.1, 1.1))
cut(ground, void_cyl(WELL, 1.0, -3.5, 0.1))
cut(bpy.data.objects["Courtyard"], void_cyl(WELL, 1.0, -0.5, 0.5))
lining = cyl("Well_lining", (*WELL, -1.75), 1.0, 3.5, STONE)
cut(lining, void_cyl(WELL, 0.85, -3.4, 0.1))
cyl("Well_water", (*WELL, -2.6), 0.86, 0.05, WATER)
for sx in (-1, 1):
    box("Well_post", (WELL[0] + sx * 1.0, WELL[1], 1.6), (WELL_T, WELL_T, 2.2), WOOD)
box("Well_beam", (WELL[0], WELL[1], 2.7), (2.3, WELL_T, WELL_T), WOOD)

# barrels / crates
for i in range(6):
    x, y = 14 + random.uniform(-2, 2), 12 + random.uniform(-3, 3)
    cyl("Barrel", (x, y, 0.5), 0.45, 1.0, WOOD, verts=16)
for i in range(4):
    box("Crate", (-14 + i * 1.1, 14, 0.45), (0.9, 0.9, 0.9), WOOD)

# ---------------------------------------------------------------- trees
def tree(x, y, s):
    cyl("Trunk", (x, y, 1.5 * s), 0.3 * s, 3.0 * s, WOOD, verts=8)
    for k in range(3):
        bpy.ops.mesh.primitive_ico_sphere_add(
            subdivisions=2, radius=(1.8 - 0.4 * k) * s,
            location=(x + random.uniform(-0.4, 0.4) * s, y + random.uniform(-0.4, 0.4) * s,
                      (3.4 + 1.3 * k) * s))
        finish(bpy.context.active_object, "Foliage", LEAVES, smooth=False)


placed = 0
while placed < 45:
    x, y = random.uniform(-90, 90), random.uniform(-90, 90)
    if max(abs(x), abs(y)) < MOAT_OUT + 6:
        continue
    if abs(x) < 8 and y < 0:  # keep the approach road clear
        continue
    tree(x, y, random.uniform(0.9, 1.6))
    placed += 1
# approach road
box("Road", (0, -MOAT_OUT - 30, 0.02), (5, 60, 0.04), DIRT)

# ---------------------------------------------------------------- world, lighting, camera
world = bpy.data.worlds.new("Sky")
scene.world = world
wn, wl = _nodes(world)
bg = wn.get("Background")
try:
    sky = wn.new("ShaderNodeTexSky")
    for t in ("MULTIPLE_SCATTERING", "SINGLE_SCATTERING", "NISHITA"):
        try:
            sky.sky_type = t
            break
        except TypeError:
            continue
    sky.sun_elevation = math.radians(28)
    sky.sun_rotation = math.radians(215)
    wl.new(sky.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 0.2
except Exception as exc:  # fall back to a flat sky colour
    print("Sky texture unavailable:", exc)
    bg.inputs["Color"].default_value = (0.45, 0.6, 0.85, 1)
    bg.inputs["Strength"].default_value = 1.0

bpy.ops.object.light_add(type="SUN", rotation=(math.radians(55), 0, math.radians(-35)))
sun = bpy.context.active_object
sun.name = "Sun"
sun.data.energy = 2.5
sun.data.angle = math.radians(1.5)
sun.data.color = (1.0, 0.93, 0.82)

bpy.ops.object.camera_add(location=(52, -78, 34))
cam = bpy.context.active_object
cam.name = "Camera"
cam.data.lens = 40
target = bpy.data.objects.new("CameraTarget", None)
scene.collection.objects.link(target)
target.location = (0, 0, 6)
tc = cam.constraints.new("TRACK_TO")
tc.target = target
tc.track_axis = "TRACK_NEGATIVE_Z"
tc.up_axis = "UP_Y"
scene.camera = cam

# ---------------------------------------------------------------- render settings
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = 512
scene.cycles.use_adaptive_sampling = True
scene.cycles.adaptive_threshold = 0.005
scene.cycles.use_denoising = True
scene.cycles.denoiser = "OPENIMAGEDENOISE"
scene.cycles.denoising_input_passes = "RGB_ALBEDO_NORMAL"
scene.cycles.denoising_prefilter = "ACCURATE"
try:
    scene.cycles.denoising_quality = "HIGH"
except AttributeError:
    pass
scene.cycles.use_guiding = True          # path guiding: cleaner indirect light indoors
scene.render.resolution_x = 1920
scene.render.resolution_y = 1080
scene.render.film_transparent = False
try:
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = -1.1
except TypeError:
    pass


# ---------------------------------------------------------------- cross-sections
# Orthographic cameras whose near clip plane slices through the buildings, with
# an area light on the cut plane so the hollow interiors are visible.
SECTIONS = [
    # name, camera location, rotation (deg), distance to cut plane, ortho width
    ("section_keep", (0, -60, 13), (90, 0, 0), 60 + KY - 1.4, 54),
    ("section_towers", (0, -60, 12), (90, 0, 0), 60 + WALL, 60),
    ("section_gate", (60, -10, 10), (90, 0, 90), 60 - 1.0, 48),
]
POCHE = (0.55, 0.16, 0.10)


def poche_fill():
    """Section-drawing fill: where the clip plane opens a solid, the camera sees
    back faces; shade those flat red so cut masonry reads as solid."""
    for m in bpy.data.materials:
        if m in (BANNER, WATER) or not m.node_tree:
            continue
        nt = m.node_tree
        out = nt.nodes.get("Material Output")
        if not out or not out.inputs["Surface"].links:
            continue
        src = out.inputs["Surface"].links[0].from_socket
        geo = nt.nodes.new("ShaderNodeNewGeometry")
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs["Color"].default_value = (*POCHE, 1)
        em.inputs["Strength"].default_value = 0.6
        mix = nt.nodes.new("ShaderNodeMixShader")
        nt.links.new(geo.outputs["Backfacing"], mix.inputs[0])
        nt.links.new(src, mix.inputs[1])
        nt.links.new(em.outputs[0], mix.inputs[2])
        nt.links.new(mix.outputs[0], out.inputs["Surface"])


section_rigs = []
for name, loc, rot, clip, width in SECTIONS:
    rot = tuple(math.radians(v) for v in rot)
    bpy.ops.object.camera_add(location=loc, rotation=rot)
    c = bpy.context.active_object
    c.name = name
    c.data.type = "ORTHO"
    c.data.ortho_scale = width
    c.data.clip_start = clip
    c.data.clip_end = 1000
    bpy.ops.object.light_add(type="AREA", rotation=rot)
    lamp = bpy.context.active_object
    lamp.name = name + "_light"
    d = lamp.matrix_world.to_3x3() @ __import__("mathutils").Vector((0, 0, -1))
    lamp.location = [loc[j] + d[j] * (clip - 0.2) for j in range(3)]
    lamp.data.size = 120
    lamp.data.energy = 60000
    lamp.hide_render = True
    section_rigs.append((name, c, lamp))

if not PRINT:
    blend_path = os.path.join(HERE, "castle.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    print("Saved", blend_path)

if "--render" in sys.argv and not PRINT:
    scene.render.filepath = os.path.join(HERE, "castle.png")
    bpy.ops.render.render(write_still=True)
    print("Rendered", scene.render.filepath)
    scene.cycles.samples = 256
    poche_fill()
    for name, c, lamp in section_rigs:
        scene.camera = c
        lamp.hide_render = False
        scene.render.filepath = os.path.join(HERE, name + ".png")
        bpy.ops.render.render(write_still=True)
        lamp.hide_render = True
        print("Rendered", scene.render.filepath)
    scene.camera = cam
