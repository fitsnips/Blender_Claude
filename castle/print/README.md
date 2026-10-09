# Castle print kit — Bambu Lab P1S, single colour, 1:210

Regenerate with: `blender --background --python print_castle.py` (add `-- --scale N` for another scale).

| Part | Size (mm) | Orientation | Supports | Time | PLA |
|---|---|---|---|---|---|
| `castle_base.stl` | 229.5 × 230.5 × 88.6 | as exported (flat base down) | **none** | 15 h 28 m | 384 g |
| `keep_half_A.stl` | 114.3 × 89.5 × 44.8 | as exported (cut face down) | tree, everywhere | 6 h 21 m | 97 g |
| `keep_half_B.stl` | 114.3 × 89.5 × 44.8 | as exported (cut face down) | tree, everywhere | 6 h 24 m | 97 g |
| `roofs.stl` (8 roofs) | 125.7 × 82.4 × 28.6 | as exported (upright) | none | 1 h 18 m | 18 g |
| **Total** | | | | **≈ 29.5 h** | **≈ 595 g** |

Times and weights are Bambu Studio 2.8 estimates with: Bambu Lab P1S 0.4 nozzle,
"0.12mm Fine" process, Bambu PLA Basic. `bambu/*.3mf` are those sliced projects.

## Slicer notes
- **Base: brim off.** At 230 mm it only just clears the P1S purge-chute corner
  (18 × 28 mm, front-left); a brim pushes it off the plate. Use a glue stick / clean PEI.
- **Base: no supports.** Every overhang is a bridge or a 45° slope (tower tops are
  vaulted, corbels bevelled). If you do enable supports, set *On build plate only*,
  or supports will be sealed inside the hollow towers.
- **Keep halves:** tree supports carry the turret tops, which hang out sideways in this
  orientation. The interiors open onto the plate, so anything printed inside comes out.
- 0.12 mm layers keep the merlons and 1.4 mm arrow slits crisp; 0.20 mm takes about 40% less time.

## Assembly
- Glue the keep halves face to face (or display them apart as a cutaway) and stand the
  keep behind the stone steps in the courtyard.
- The roofs drop onto the corner-tower drums (4 larger) and keep turrets (4 smaller).
  Leave them unglued to lift off and look inside.

## Changed from the render model for printing
Removed: flags, ladders, chains, torches, trees, moat, drawbridge, keep door leaf, gate paving.
Thickened: arrow slits 1.4 mm, floors 1.2 mm, portcullis bars 1.2 mm (lowered onto the floor), well posts.
Reshaped: tower top ledges bevelled at 45°, tower ceilings vaulted at 45°, hall roofs solid without eaves.
