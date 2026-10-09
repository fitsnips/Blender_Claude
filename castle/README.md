# Medieval castle

A procedurally built medieval castle, designed to be structurally plausible rather than just a
silhouette. Every tower and building is hollow, every opening is cut through the masonry, and
people could walk the defences.

## Usage

Run from any directory; output is written next to the scripts.

```sh
# build castle.blend and render the exterior plus three cross-sections (~10 min on CPU)
blender --background --python build_castle.py -- --render

# build castle.blend only
blender --background --python build_castle.py

# export the 3D-print kit (STL files in print/)
blender --background --python print_castle.py
```

| Output | Contents |
|---|---|
| `castle.blend` | the full scene, including cross-section cameras named `section_*` |
| `castle.png` | exterior render, 1920 × 1080 |
| `section_keep.png`, `section_towers.png`, `section_gate.png` | cut-away views that show the interiors |
| `print/*.stl` | 3D-print kit; see [print/README.md](print/README.md) |

## What is modelled

- **Curtain walls:** 3 m thick, with a 2 m clear wall-walk between the battlements and the
  inner parapet. A stone stair rises from the courtyard to the east wall-walk.
- **Corner towers:** hollow masonry shells with a door to the courtyard, timber floors on beams
  set into the walls, ladders through hatches, and doors out onto both wall-walks. Arrow loops
  are narrow slits with a wide splay on the inside. On top there is a stone roof walk behind
  the battlements, with a 1.4 m path around a stair-head drum under a hollow conical roof.
- **Gatehouse:** an arched passage with a portcullis that hangs from a windlass in the chamber
  above. The flanking gate towers open onto the passage, the chamber and the south wall-walk.
- **Keep:** a ground-floor store and a raised entrance hall reached by stone steps, then a great
  hall and a solar on timber floors. The floors rest on beams and a central stone pier. A stone
  roof slab forms a walkable roof. Full-height corner stair turrets open onto every floor.
- **Courtyard:** timber halls with a door, windows and a roof frame, plus a well whose shaft
  goes down to water.
- **Setting:** a moat, a drawbridge on chains, an approach road and trees.

Nothing floats or overhangs without support. Overhanging rings on the towers sit on corbels, and
roofs bear on the wall tops.

## How it is built

`build_castle.py` uses only Blender primitives and boolean modifiers. A few notes:

- Hollow interiors, doors, windows and arrow loops are boolean differences. Booleans use the
  Exact solver with self-intersection enabled; cutters that overlap themselves break the
  default settings.
- Stone uses a coursed-ashlar shader: a brick texture projected three ways on flat walls and
  unwrapped around round towers, with weathering noise and mortar bump.
- The section renders use a camera whose near clipping plane slices the model. An area light
  sits on the cut plane, and the back faces exposed by the cut are filled with flat red (poché),
  as in an architectural section drawing.
- Passing `--print` builds a printable variant: wider slits, thicker floors, bevelled corbels,
  vaulted tower ceilings and solid hall roofs. `print_castle.py` uses this variant.
