# Blender + Claude

Procedural 3D models built in [Blender](https://www.blender.org/) with Python scripts written
together with Claude. Each project lives in its own directory and is rebuilt from scratch by its
scripts, so the repository holds code and documentation only. Renders, `.blend` files and print
files are generated output and are not committed.

## Projects

| Project | Description |
|---|---|
| [castle](castle/) | A medieval castle with hollow towers, a keep, open arrow slits, walkable wall-walks and a moat. It also exports a single-colour 3D-print kit for the Bambu Lab P1S. |

## Requirements

- Blender 5.2 or later (developed with 5.2.2 LTS). Scripts run headless with
  `blender --background --python <script>`.
- Rendering uses Cycles on the CPU, so no GPU is needed.
- Optional: Bambu Studio, to slice the 3D-print files.

## Adding a project

1. Create a directory named after the project, for example `bridge/`.
2. Put its build scripts there. Scripts should locate files relative to themselves
   (`os.path.dirname(os.path.abspath(__file__))`) and write their output alongside, so they
   run from any working directory.
3. Add a `README.md` covering usage, outputs and design notes.
4. Add a row to the Projects table above.

Generated output (`*.blend`, `*.png`, `*.stl`, `*.3mf`, `*.gcode`) is ignored by the top-level
`.gitignore`. If you add a new output type, add it there too.
