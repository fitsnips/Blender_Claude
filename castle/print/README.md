# Castle print kit: Bambu Lab P1S, single colour, 1:210

Ready to print, no Blender needed. This folder has the Bambu Studio project
`castle_print_1-210.3mf`, plus the same parts as separate STLs for other slicers:
`castle_base.stl`, `keep_half_A.stl`, `keep_half_B.stl` and `roofs.stl`.

Regenerate with `blender --background --python print_castle.py`. Add `-- --scale N` for another
scale, or `-- --stl` to also write each part as a separate STL for other slicers.

The output is one Bambu Studio project, `castle_print_1-210.3mf`, with two plates. Open it, pick
the Bambu Lab P1S 0.4 nozzle printer and a PLA filament, then slice all plates. The per-object
settings below are stored in the file.

| Plate | Part | Size (mm) | Orientation | Settings stored in the file | Time | PLA |
|---|---|---|---|---|---|---|
| 1 | `castle_base` | 229.5 × 230.5 × 88.6 | flat base down | no brim, no supports | 15 h 17 m | 371 g |
| 2 | `keep_half_A`, `keep_half_B` | 114.3 × 89.5 × 44.8 each | cut face down | tree supports | 14 h 6 m (whole plate) | 211 g (whole plate) |
| 2 | `roofs` (8 roofs) | 125.7 × 82.4 × 28.6 | upright | none | | |
| | **Total** | | | | **≈ 29.4 h** | **≈ 582 g** |

The base plate follows the castle's outline: a strip 2 mm wide outside the walls, with round
pads under the towers. Its overall size is set by the corner and gate towers.

Times and weights are Bambu Studio 2.8 estimates for a Bambu Lab P1S 0.4 nozzle with the
"0.12mm Fine" process and Bambu PLA Basic.

## Slicer notes
- **Base: no brim.** At 230 mm the base only just clears the P1S purge-chute corner
  (18 × 28 mm, front-left), and a brim would push it off the plate. Use a glue stick or a
  clean PEI plate instead.
- **Base: no supports.** Every overhang is a bridge or a 45° slope: tower tops are vaulted and
  corbels are bevelled. If you do enable supports, set *On build plate only*, or supports will
  be sealed inside the hollow towers.
- **Keep halves:** tree supports carry the turret tops, which hang out sideways in this
  orientation. The interiors open onto the plate, so anything printed inside comes out.
- **Don't auto-arrange plate 1:** the base is placed to clear the excluded corner, and
  re-arranging can move it off the plate.
- 0.12 mm layers keep the merlons and 1.4 mm arrow slits crisp. 0.20 mm layers take about 40%
  less time.

## Assembly
- Glue the keep halves face to face, or display them apart as a cutaway. Stand the keep behind
  the stone steps in the courtyard.
- The roofs drop onto the corner-tower drums (the 4 larger roofs) and the keep turrets (the 4
  smaller ones). Leave them unglued so they lift off to show the inside.

## Changed from the render model for printing
- **Removed:** flags, ladders, chains, torches, trees, moat, drawbridge, keep door leaf and gate
  paving.
- **Thickened:** arrow slits to 1.4 mm, floors to 1.2 mm, portcullis bars to 1.2 mm (lowered
  onto the floor) and well posts.
- **Reshaped:** tower-top ledges bevelled at 45°, tower ceilings vaulted at 45°, and hall roofs
  solid without eaves.
