# RoboVerse Studio

**Design. Connect. Simulate. Validate. Build.**

RoboVerse Studio is an integrated robotics engineering workspace. A single shared project model connects the 3D environment, the mechanical/robot model, the electronic schematic, the firmware pin map and the co-simulation, so a design goes from concept to a tested virtual prototype — and then to generated firmware, a ROS 2 package and a KiCad netlist for the physical build.

| Workspace | What it does (working today) |
|---|---|
| **Dashboard** | Create/open/import projects, sample digital twins, simulation history, component-library statistics, integration & dependency health, CPU/GPU/memory resources |
| **3D world builder** | Floors, walls, doors, ramps, racks, tables, chargers, moving humans, start/goal markers; move/rotate/scale gizmos with snapping, hierarchy, properties, collision overlay, measuring tool, orbit/top/front/side/first-person (WASD) cameras, undo/redo, six environment templates |
| **Mechanical CAD** | Parametric parts on the Manifold kernel (sketch extrude with holes, union/difference/intersection, named dimensions), mass/volume/COM/inertia, interference & clearance checks, STL/OBJ export, STL/OBJ import clearly flagged as non-parametric meshes |
| **Robot designer** | Differential, 4WD, Ackermann, mecanum, tracked and arm generators; drivetrain sizing (speed, torque, traction, tipping); link/joint/sensor/actuator editing; TF frames; validation report; URDF/Xacro/SDF/MJCF export; URDF import that preserves unsupported elements |
| **Circuit studio** | Drag-and-drop schematic, pin-to-pin wiring, net highlighting, live hardware-compatibility/ERC, power budget, built-in MNA circuit solver (+ ngspice adapter), SPICE and KiCad netlist export |
| **Firmware** | Target/mode selection limited to validated execution modes, pin map, PI gains, generated PlatformIO project (same controller as the simulator), PlatformIO build with parsed diagnostics, HIL serial protocol |
| **Digital twin** | Traces every actuator: joint → motor → driver channel → controller pin → firmware channel → battery/fuse → physics joint. Unwired motors are *not* driven |
| **Design validation** | One engine for robot, electrical, power, twin, firmware, world, scenario and export checks; run history |
| **Simulation & nav lab** | Co-simulation with start/pause/resume/stop/reset, speed control, E-stop, teleop, waypoints/goal/docking, live 2D/3D view (truth vs estimate, LiDAR, path, dynamic obstacles), telemetry charts, events, metrics, CSV export |
| **AI & perception lab** | GPU/CPU detection, LiDAR obstacle detection scored against ground truth, telemetry anomaly detection |
| **Import / export** | Versioned `.rvproj` package (manifest + SHA-256 checksums), URDF/SDF/Xacro/MJCF, Gazebo world, ROS 2 package, SPICE, KiCad netlist, PlatformIO project |

## Quick start

Requirements: Python ≥ 3.11, Node ≥ 20.

```bash
./scripts/dev.sh          # creates the venv, installs deps, builds the UI, serves everything on :8000
```

or manually:

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn roboverse.main:app --reload              # API on http://localhost:8000 (OpenAPI at /docs)

cd ../frontend
npm install
npm run dev                                       # UI on http://localhost:5173 (proxies /api and /ws to :8000)
```

Open the dashboard and choose **Warehouse AMR (complete digital twin)**. Then:

1. *Circuit studio* — the design passes all checks. Open **Warehouse AMR with design errors** to see 5 V encoders driving 3.3 V-only ESP32 pins and an L298N that cannot survive the motors' 5.5 A stall current, each reported with the exact connection, the datasheet values and a fix.
2. *Digital twin* — both wheels are traced from joint to battery.
3. *Simulation & nav lab* → **Run simulation**. The robot visits four waypoints in the warehouse, waits for the walking worker, then returns to the charger (≈ 106 s simulated, ~5 s wall time at max speed).
4. *Firmware* — the generated ESP32 firmware uses the pins from the schematic.
5. *Import / export* — download the ROS 2 package or the full `.rvproj`.

PostgreSQL: set `ROBOVERSE_DATABASE_URL=postgresql+psycopg://user:pass@host/db` (and `pip install psycopg[binary]`). SQLite is the default.

## Tests

```bash
cd backend && pytest                      # 72 tests: engines, co-simulation, export round-trips, API + WebSocket
cd frontend && npm run build              # type-check + production build
cd frontend && npm run test:e2e           # browser smoke test against a running backend (needs Playwright + Chromium)
```

The backend suite includes checks against analytical results (RC time constant, divider, diode drop, box inertia, motor stall/no-load points, fuse I²t), full navigation missions, determinism, E-stop, fuse blow, unwired-motor behaviour, the MuJoCo backend, package tamper detection, and compiling the generated firmware against an Arduino API stub.

## What is real, what is estimated

RoboVerse labels every result with its source and never upgrades an estimate to a measurement:

* **Circuit-solver results** — the built-in MNA solver (R, C, L, V/I sources incl. pulse, diodes, switches, fuses, battery EMF + R). BJTs, MOSFETs, op-amps and ICs are *not* solved; they are listed as "not simulated". Use ngspice for transistor-level work.
* **Analytical models** — battery (Thevenin + OCV curve), DC motor (R/Kt/Ke from datasheet points, copper tempco), H-bridge (duty, R_ds(on)/bipolar drop, over-current shutdown), fuse (I²t), first-order winding temperature. Thermal and battery outputs are estimates, **not** safety validation.
* **Physics** — built-in planar rigid-body dynamics, or MuJoCo 3D contact dynamics.
* **Sensors** — simulated (ray-cast LiDAR with noise, quantised encoders, IMU with bias). Simulated data is never mixed with hardware data; perception outputs are scored against ground truth.
* **Components** — 92 built-in parts, each with a support status (fully modeled / simulation supported / behavioral / schematic only / CAD only / imported-unverified / user-defined) and per-rating provenance (datasheet / assumption / user / unknown). Unknown ratings stay unknown.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the architecture, the integration evaluation (with licenses), the co-simulation strategy, and the roadmap.
