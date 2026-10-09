"""Export a single-colour, 3D-printable castle as one Bambu Studio 3MF (default 1:210).

Usage:
    blender --background --python print_castle.py [-- --scale 210] [--stl]

Builds the --print variant of build_castle.py, strips parts too fine to print,
merges each printable piece into one watertight solid and writes, to print/:

    castle_print_1-210.3mf  one project, two plates, ready to slice in Bambu Studio:
        plate 1  castle_base   walls, towers, gatehouse, halls and courtyard on a base plate
        plate 2  keep_half_A   keep cut in half through its centre, cut face down
                 keep_half_B   (the two halves show the floors inside; glue or display apart)
                 roofs         8 removable cone roofs (4 corner towers + 4 keep turrets)
    print_layout.blend      all parts as exported, for inspection
    print_preview.png       render of the parts

--stl also writes each part as its own STL, for other slicers.
"""
import math
import os
import sys
import zipfile

import bmesh
import bpy
from mathutils import Matrix

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "print")
os.makedirs(OUT, exist_ok=True)
args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
SCALE = float(args[args.index("--scale") + 1]) if "--scale" in args else 210.0   # 1:210 keeps the base clear of the P1S purge-chute corner
MM_PER_M = 1000.0 / SCALE
MIN_FEATURE_MM = 0.8          # two 0.4 mm extrusion lines
# keep halves lie on their sides: tree supports carry the turret tops
KEEP_SUPPORT = {"enable_support": "1", "support_type": "tree(auto)"}
SOLVERS = ("EXACT", "MANIFOLD") if "--exact" in args else ("MANIFOLD", "EXACT")

# ---------------------------------------------------------------- build print variant
sys.argv.append("--print")
src = os.path.join(HERE, "build_castle.py")
castle = {"__file__": src, "__name__": "__main__"}
exec(compile(open(src).read(), src, "exec"), castle)
scene = bpy.context.scene
KX, KY = castle["KX"], castle["KY"]
ISLAND = castle["MOAT_IN"]

# ---------------------------------------------------------------- strip unprintable parts
DROP = ("Ground", "Water", "MoatBed", "Courtyard", "Road", "Drawbridge", "Trunk",
        "Foliage", "_flag", "ladder", "Chain_", "Portcullis_chain", "Torch",
        "Well_water", "Well_lining", "Keep_door", "GatePaving")
for o in list(bpy.data.objects):
    if o.type != "MESH" or any(k in o.name for k in DROP):
        bpy.data.objects.remove(o, do_unlink=True)

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
for o in bpy.data.objects:
    o.modifiers.clear()
    o.data.materials.clear()

thin = sorted((min(o.dimensions) * MM_PER_M, o.name) for o in bpy.data.objects
              if min(o.dimensions) * MM_PER_M < MIN_FEATURE_MM)
print(f"Thin parts (< {MIN_FEATURE_MM} mm) left after stripping: {thin or 'none'}")


# ---------------------------------------------------------------- helpers
def non_manifold(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bad = sum(1 for e in bm.edges if not e.is_manifold)
    bm.free()
    return bad


def _triangulated(mesh, method):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.triangulate(bm, faces=bm.faces[:], quad_method="BEAUTY", ngon_method=method)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    out = mesh.copy()
    bm.to_mesh(out)
    bm.free()
    return out


def clean(obj):
    """Triangulate the boolean's large n-gons here, where the result can be
    checked, instead of leaving it to the STL exporter. Returns open edges."""
    best = None
    for method in ("BEAUTY", "EAR_CLIP"):
        tri = _triangulated(obj.data, method)
        probe = bpy.data.objects.new("probe", tri)
        bad = non_manifold(probe)
        bpy.data.objects.remove(probe)
        if best is None or bad < best[0]:
            best = (bad, tri)
        if bad == 0:
            break
    obj.data = best[1]
    return best[0]


def apply_boolean(target, op, operand, collection=False):
    """Boolean with the fast Manifold solver, falling back to Exact."""
    before = target.data.copy()
    for solver in SOLVERS:
        mod = target.modifiers.new("bool", "BOOLEAN")
        mod.operation = op
        if collection:
            mod.operand_type = "COLLECTION"
            mod.collection = operand
        else:
            mod.object = operand
        try:
            mod.solver = solver
        except TypeError:
            target.modifiers.remove(mod)
            continue
        if solver == "EXACT":
            mod.use_self = True
            mod.use_hole_tolerant = True
        bpy.context.view_layer.objects.active = target
        try:
            bpy.ops.object.modifier_apply(modifier=mod.name)
        except RuntimeError as exc:
            print(f"  {solver} failed on {target.name}: {exc}")
            target.modifiers.clear()
            continue
        if len(target.data.polygons) and non_manifold(target) == 0:
            print(f"  {target.name}: {op.lower()} via {solver}")
            return solver
        print(f"  {target.name}: {solver} left {non_manifold(target)} open edges, retrying")
        target.data = before.copy()
    print(f"  {target.name}: kept last result")
    return None


def union(objs, name):
    target, rest = objs[0], objs[1:]
    if rest:
        coll = bpy.data.collections.new(name + "_parts")
        for o in rest:
            coll.objects.link(o)
        apply_boolean(target, "UNION", coll, collection=True)
        for o in rest:
            bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.collections.remove(coll)
    target.name = name
    if clean(target):
        print(f"  {name}: Manifold result does not triangulate cleanly")
    return target


def cut_box(target, center, size):
    bpy.ops.mesh.primitive_cube_add(size=1, location=center)
    c = bpy.context.active_object
    c.scale = size
    bpy.ops.object.transform_apply(scale=True)
    apply_boolean(target, "DIFFERENCE", c)
    bpy.data.objects.remove(c, do_unlink=True)
    clean(target)


def place(obj, x=0.0, y=0.0):
    """Sit the part on z=0 centred at (x, y)."""
    vs = [v.co for v in obj.data.vertices]
    mn = [min(v[i] for v in vs) for i in range(3)]
    mx = [max(v[i] for v in vs) for i in range(3)]
    obj.data.transform(Matrix.Translation((x - (mn[0] + mx[0]) / 2,
                                           y - (mn[1] + mx[1]) / 2, -mn[2])))
    return [(mx[i] - mn[i]) * MM_PER_M for i in range(3)]


# ---------------------------------------------------------------- sort into parts
groups = {"base": [], "keep": []}
for o in list(bpy.data.objects):
    n = o.name
    if "_roof" in n and (n.startswith("Tower_") or n.startswith("Keep_turret_")):
        groups.setdefault("roof:" + n.split("_roof")[0], []).append(o)
    elif (n == "Keep" or n.startswith("Keep_")) and not n.startswith("Keep_step"):
        groups["keep"].append(o)
    else:
        groups["base"].append(o)

# base plate under the island: 3 mm at 1:200
# (its top sits 5 cm above z=0 so everything standing on the ground bonds into it)
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, -0.275))
plate = bpy.context.active_object
plate.scale = (2 * ISLAND, 2 * ISLAND, 0.65)
bpy.ops.object.transform_apply(scale=True)
# a 1 m grid on the plate keeps every face small; one huge top face pierced by
# dozens of footprints does not triangulate cleanly after the union
_bm = bmesh.new()
_bm.from_mesh(plate.data)
bmesh.ops.subdivide_edges(_bm, edges=[e for e in _bm.edges
                                      if abs(e.verts[0].co.z - e.verts[1].co.z) < 1e-6],
                          cuts=int(2 * ISLAND) - 1, use_grid_fill=True)
_bm.to_mesh(plate.data)
_bm.free()
plate.name = "BasePlate"
groups["base"].insert(0, plate)

parts = {}
print("Merging castle base ...")
parts["castle_base"] = union(groups["base"], "castle_base")

print("Merging and splitting keep ...")
keep = union(groups["keep"], "keep")
for label, side in (("A", 1), ("B", -1)):
    half = keep.copy()
    half.data = keep.data.copy()
    scene.collection.objects.link(half)
    half.name = f"keep_half_{label}"
    # remove the other side of the x = KX plane
    cut_box(half, (KX - side * 50, KY, 15), (100, 100, 100))
    # lay it on the cut face: the kept side's +x/-x direction becomes up
    half.data.transform(Matrix.Translation((KX, KY, 0)) @ Matrix.Rotation(-side * math.pi / 2, 4, "Y")
                        @ Matrix.Translation((-KX, -KY, 0)))
    parts[half.name] = half
bpy.data.objects.remove(keep, do_unlink=True)

print("Merging roofs ...")
roofs = []
for key in sorted(k for k in groups if k.startswith("roof:")):
    prefix = key.split(":", 1)[1]
    objs = groups[key]
    cone_obj = next(o for o in objs if o.name == prefix + "_roof")
    cvs = [v.co for v in cone_obj.data.vertices]
    zt = min(v.z for v in cvs)
    cx = (min(v.x for v in cvs) + max(v.x for v in cvs)) / 2
    cy = (min(v.y for v in cvs) + max(v.y for v in cvs)) / 2
    objs.sort(key=lambda o: o is not cone_obj)
    r = union(objs, prefix + "_roof")
    # drop the halves of the tie beams that sit down into the wall top
    cut_box(r, (cx, cy, zt - 5), (40, 40, 10))
    roofs.append(r)

# ---------------------------------------------------------------- lay out and export
report = []
layout_x = {"castle_base": 0, "keep_half_A": 40, "keep_half_B": 40}
layout_y = {"castle_base": 0, "keep_half_A": -12, "keep_half_B": 12}
for name, obj in parts.items():
    dims = place(obj, layout_x[name], layout_y[name])
    report.append((name, dims, len(obj.data.polygons), non_manifold(obj)))
for i, r in enumerate(roofs):
    place(r, -40 + (i % 4) * 7.0, -6 + (i // 4) * 12.0)
bpy.ops.object.select_all(action="DESELECT")
for r in roofs:
    r.select_set(True)
bpy.context.view_layer.objects.active = roofs[0]
bpy.ops.object.join()
roof_plate = bpy.context.active_object
roof_plate.name = "roofs"
vs = [v.co for v in roof_plate.data.vertices]
report.append(("roofs", [(max(v[i] for v in vs) - min(v[i] for v in vs)) * MM_PER_M
                         for i in range(3)], len(roof_plate.data.polygons),
               non_manifold(roof_plate)))
parts["roofs"] = roof_plate

# Bambu Studio project: one 3MF, two plates, per-object print settings
PLATE_STRIDE = 256.0 * 1.2      # Bambu lays plates out on a grid with a 20% gap
PLATES = [
    ("Castle base", [("castle_base", (137.0, 128.0), {"brim_type": "no_brim"})]),
    ("Keep and roofs", [
        ("keep_half_A", (78.0, 205.0), KEEP_SUPPORT),
        ("keep_half_B", (196.0, 205.0), KEEP_SUPPORT),
        ("roofs", (137.0, 80.0), {}),
    ]),
]


def mesh_xml(obj):
    """Triangle mesh in millimetres, centred on x/y with its base at z = 0."""
    me = obj.data
    me.calc_loop_triangles()
    co = [v.co * MM_PER_M for v in me.vertices]
    cx = (min(c.x for c in co) + max(c.x for c in co)) / 2
    cy = (min(c.y for c in co) + max(c.y for c in co)) / 2
    z0 = min(c.z for c in co)
    verts = "".join(f'<vertex x="{c.x - cx:.4f}" y="{c.y - cy:.4f}" z="{c.z - z0:.4f}"/>'
                    for c in co)
    tris = "".join(f'<triangle v1="{t.vertices[0]}" v2="{t.vertices[1]}" '
                   f'v3="{t.vertices[2]}"/>' for t in me.loop_triangles)
    return f"<mesh><vertices>{verts}</vertices><triangles>{tris}</triangles></mesh>"


def write_3mf(path):
    objects, items, settings, plates = [], [], [], []
    oid = 0
    for p, (plate_name, entries) in enumerate(PLATES):
        ox, oy = (p % 2) * PLATE_STRIDE, -(p // 2) * PLATE_STRIDE
        instances = []
        for name, (x, y), overrides in entries:
            oid += 1
            objects.append(f'<object id="{oid}" type="model" name="{name}">'
                           f'{mesh_xml(parts[name])}</object>')
            items.append(f'<item objectid="{oid}" '
                         f'transform="1 0 0 0 1 0 0 0 1 {x + ox:.3f} {y + oy:.3f} 0" '
                         f'printable="1"/>')
            meta = "".join(f'<metadata key="{k}" value="{v}"/>'
                           for k, v in {"name": name, "extruder": "1", **overrides}.items())
            settings.append(f'<object id="{oid}">{meta}<part id="1" subtype="normal_part">'
                            f'<metadata key="name" value="{name}"/>'
                            f'<metadata key="matrix" '
                            f'value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/></part></object>')
            instances.append(f'<model_instance><metadata key="object_id" value="{oid}"/>'
                             f'<metadata key="instance_id" value="0"/></model_instance>')
        plates.append(f'<plate><metadata key="plater_id" value="{p + 1}"/>'
                      f'<metadata key="plater_name" value="{plate_name}"/>'
                      f'<metadata key="locked" value="false"/>{"".join(instances)}</plate>')
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    model = (xml + '<model unit="millimeter" xml:lang="en-US" '
             'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
             f'<metadata name="Title">Castle print kit 1:{SCALE:g}</metadata>'
             f'<resources>{"".join(objects)}</resources>'
             f'<build>{"".join(items)}</build></model>')
    config = xml + "<config>" + "".join(settings) + "".join(plates) + "</config>"
    content_types = (
        xml + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="model" '
        'ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
        '<Default Extension="config" ContentType="text/xml"/></Types>')
    rels = (xml + '<Relationships '
            'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel-1" '
            'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
            '</Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)
        z.writestr("Metadata/model_settings.config", config)
    print("Exported", path)


write_3mf(os.path.join(OUT, f"castle_print_1-{SCALE:g}.3mf"))
if "--stl" in args:
    for name, obj in parts.items():
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        path = os.path.join(OUT, name + ".stl")
        bpy.ops.wm.stl_export(filepath=path, export_selected_objects=True,
                              global_scale=MM_PER_M, ascii_format=False)
        print("Exported", path)

print(f"\n=== Print parts at 1:{SCALE:g} (Bambu Lab P1S: 256 x 256 x 256 mm bed, "
      f"18 x 28 mm purge-chute corner excluded) ===")
for name, d, tris, bad in report:
    # the part must clear the excluded corner on one side, with ~3 mm margin
    w, l = sorted(d[:2])
    fits = d[2] <= 250 and l <= 253 and w <= 256 - 18 - 3
    print(f"{name:12s} {d[0]:6.1f} x {d[1]:6.1f} x {d[2]:6.1f} mm  faces={tris:7d}  "
          f"open_edges={bad}  {'fits' if fits else 'TOO BIG'}")

# ---------------------------------------------------------------- preview
for o in bpy.data.objects:
    o.data.materials.clear()
pla = bpy.data.materials.new("PLA")
pla.diffuse_color = (0.75, 0.75, 0.72, 1)
bsdf = pla.node_tree.nodes.get("Principled BSDF")
bsdf.inputs["Base Color"].default_value = (0.62, 0.62, 0.6, 1)
bsdf.inputs["Roughness"].default_value = 0.45
for o in parts.values():
    o.data.materials.append(pla)
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(30))
bpy.ops.object.light_add(type="SUN", rotation=(math.radians(50), 0, math.radians(-40)))
bpy.context.active_object.data.energy = 3.5
scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.25
bpy.ops.object.camera_add(location=(10, -95, 70))
cam = bpy.context.active_object
cam.data.lens = 38
tgt = bpy.data.objects.new("t", None)
scene.collection.objects.link(tgt)
tgt.location = (5, 0, 3)
tc = cam.constraints.new("TRACK_TO")
tc.target = tgt
tc.track_axis = "TRACK_NEGATIVE_Z"
tc.up_axis = "UP_Y"
scene.camera = cam
scene.cycles.samples = 128
scene.render.filepath = os.path.join(OUT, "print_preview.png")
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "print_layout.blend"))
if "--no-preview" not in args:
    bpy.ops.render.render(write_still=True)
