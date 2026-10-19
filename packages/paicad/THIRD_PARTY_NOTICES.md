# Third-party notices — paicad

paicad (runtime) depends on the following third-party software. Versions are pinned in
`pyproject.toml`. Test-only tools (the `test` extra) are listed separately; they are not part of
the deployment bundle.

## Runtime

| Component | Use | License |
|---|---|---|
| Open CASCADE Technology (OCCT) 7.8 | B-rep kernel (via OCP), used only in `paicad.kernel` | GNU LGPL 2.1 with the Open CASCADE exception — https://dev.opencascade.org/resources/licensing |
| cadquery-ocp (OCP) 7.8.1.1.post1 | Python bindings for OCCT | Apache License 2.0 (bindings); bundles OCCT (LGPL 2.1 + exception) and VTK (BSD 3-Clause) |
| VTK 9.3.1 | pulled in by cadquery-ocp (not used by paicad code) | BSD 3-Clause |
| NumPy | arrays | BSD 3-Clause |
| SciPy | KD-tree, sparse solvers | BSD 3-Clause |

LGPL note: OCCT is used as unmodified shared libraries loaded dynamically from the
cadquery-ocp wheel. Users may replace those libraries with a compatible build. The OCCT
source is available from https://github.com/Open-Cascade-SAS/OCCT.

## Test only (`pip install paicad[test]`, not distributed)

| Component | License |
|---|---|
| build123d 0.10.0 | Apache License 2.0 |
| ocp_gordon 0.1.18 | Apache License 2.0 |
| gmsh 4.x (Python wheel) | GNU GPL 2 or later (with linking exception) — used only to generate test meshes; never imported by runtime code |
| pytest | MIT |
