# Blender + Claude

Procedural 3D models built in [Blender](https://www.blender.org/) with Python scripts written
together with Claude. Each project lives in its own directory and is rebuilt from scratch by its
scripts. The repository holds the code and documentation, plus ready-to-print files and
compressed preview images where a project has them. Full renders and `.blend` files are
generated output and are not committed.

## Projects

| Project | Description |
|---|---|
| [castle](castle/) | A medieval castle with hollow towers, a keep, open arrow slits, walkable wall-walks and a moat. Includes a ready-to-print kit for the Bambu Lab P1S ([3MF and STLs](castle/print/)). |
| [dragon](dragon/) | A snarling dragon-head bust with real scale relief, swept-back horns, a spiked mane and chevron belly plates. It is rendered in colour and as an ink drawing in the style of the illustration it is based on. |

## Requirements

- Blender 5.2 or later (developed with 5.2.2 LTS). Scripts run headless with
  `blender --background --python <script>`.
- Rendering uses Cycles on the CPU, so no GPU is needed.
- Optional: Bambu Studio, to slice the 3D-print files.

## Running on macOS

1. Install Blender 5.2 or later, with Homebrew or from
   [blender.org](https://www.blender.org/download/) (pick the Apple Silicon or Intel build to
   match your Mac):

   ```sh
   brew install --cask blender
   ```

2. Make `blender` available in Terminal. On macOS the command-line binary sits inside the app
   bundle and isn't on your `PATH`, so add an alias:

   ```sh
   echo 'alias blender="/Applications/Blender.app/Contents/MacOS/Blender"' >> ~/.zshrc
   source ~/.zshrc
   blender --version
   ```

   **Installed Blender through Steam?** Steam keeps it in its own library folder instead of
   `/Applications`. Check it's there, then alias that copy:

   ```sh
   ls -d $HOME/Library/Application\ Support/Steam/steamapps/common/Blender/Blender.app
   printf '%s\n' 'alias blender="$HOME/Library/Application\ Support/Steam/steamapps/common/Blender/Blender.app/Contents/MacOS/Blender"' >> ~/.zshrc
   source ~/.zshrc
   blender --version
   ```

   Keep the `\` before the space in `Application\ Support`: without it, the alias splits at
   the space and `blender` fails with "no such file or directory".

   If `ls` can't find it (for example, your Steam library is on another drive), search for
   it, then use the path it prints followed by `/Contents/MacOS/Blender`, with a `\` before
   every space:

   ```sh
   mdfind 'kMDItemFSName == "Blender.app"'
   ```

   Steam doesn't need to be running. If `blender --version` shows a version older than 5.2,
   right-click Blender in Steam, open **Properties → Betas**, and make sure no older version
   branch is selected.

3. Clone the repository:

   ```sh
   git clone https://github.com/fitsnips/Blender_Claude.git
   cd Blender_Claude
   ```

4. Run a project. For example, the dragon:

   ```sh
   cd dragon

   # open Blender with the dragon built, ready to orbit and inspect
   blender --python build_dragon.py

   # or headless: render dragon.png and dragon_ink.png, then view them
   blender --background --python build_dragon.py -- --render
   open dragon.png dragon_ink.png

   # validate the model and render close-ups into check/
   blender --background --python build_dragon.py -- --check
   open check/
   ```

   The castle works the same way from `castle/`. To print it, open the kit in Bambu Studio:

   ```sh
   open castle/print/castle_print_1-210.3mf
   ```

Tips:

- In the Blender window, press Numpad 0 to look through the render camera, and press `Z` and
  choose **Material Preview** to see colours.
- The scripts render with Cycles on the CPU, which is fine on Apple Silicon (a few minutes for
  a full render). In the Blender window you can switch to the GPU instead: turn on **Metal**
  under *Preferences → System → Cycles Render Devices*, then set *Render Properties → Device*
  to **GPU Compute**.
- If macOS refuses to open a downloaded Blender ("Apple cannot check it for malicious
  software"), right-click the app in Applications, choose **Open**, and confirm once. The
  Homebrew install doesn't have this problem.

## Adding a project

1. Create a directory named after the project, for example `bridge/`.
2. Put its build scripts there. Scripts should locate files relative to themselves
   (`os.path.dirname(os.path.abspath(__file__))`) and write their output alongside, so they
   run from any working directory.
3. Add a `README.md` covering usage, outputs and design notes.
4. Add a row to the Projects table above.

Generated output (`*.blend`, `*.png`, `*.stl`, `*.3mf`, `*.gcode`) is ignored by the top-level
`.gitignore`. If you add a new output type, add it there too. To publish print files, add a `!`
exception for them in `.gitignore`, as `castle/print/` does. For README images, save compressed
JPEGs in the project's `images/` folder, as `dragon/` does.
