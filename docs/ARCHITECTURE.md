# RoboVerse Studio — architecture and implementation plan

## 1. Environment assessment (what this build was developed and verified on)

| Item | Finding | Consequence |
|---|---|---|
| OS / CPU / RAM | Linux x86-64, 4 cores, 15 GB, no GPU | All engines are CPU-only; GPU paths are detected, never assumed |
| Python | 3.13 | FastAPI, SQLAlchemy 2, NumPy 2 |
| Node | 22 | React 19 + Vite 7 + React Three Fiber 9 |
| `mujoco` (pip wheel) | installs and runs | Used as the 3D physics backend |
| `manifold3d` (pip wheel) | installs and runs | Used as the parametric CAD kernel |
| `pybullet` | no wheel for Python 3.13 | Adapter slot only |
| ngspice, KiCad, FreeCAD, Gazebo, ROS 2, Webots, QEMU, PlatformIO | not installed; system package installs unavailable | Each has an adapter that detects the tool and reports status. Exports target them (SPICE netlist, KiCad netlist, SDF world, ROS 2 package, PlatformIO project) |

## 2. System architecture

```
┌──────────────────────── Browser (React + TypeScript + Vite) ────────────────────────┐
│ Dashboard · World builder (R3F) · CAD · Robot designer · Circuit studio (SVG node      │
│ editor) · Firmware · Digital twin · Validation · Simulation lab · AI lab · Import/Export│
│ Zustand store: one Project document, undo/redo history, debounced autosave            │
└───────────────┬───────────────────────────────────────────────┬──────────────────────┘
          REST (JSON)                                    WebSocket /ws/simulations/{id}
┌───────────────┴───────────────────── FastAPI ─────────────────┴──────────────────────┐
│ Projects · Library · Validation · Circuit · Twin · CAD · Robot · Firmware · Export ·   │
│ Import · Simulation sessions (thread per run, asyncio fan-out) · AI                    │
├───────────────────────────────────── Engines ─────────────────────────────────────────┤
│ schemas/      Project (shared model) · Component (library) · Issue                      │
│ library/      versioned registry, search, import/validation pipeline                    │
│ circuit/      nets (union-find) · compatibility/ERC · power budget · MNA solver ·       │
│               SPICE/KiCad export · ngspice adapter                                      │
│ robot.py      generators + validation     description.py  URDF/Xacro/SDF/MJCF + import  │
│ cad/          Manifold parametric features, mass properties, interference, mesh IO     │
│ power/        battery, DC motor, H-bridge, fuse, thermal                                │
│ world/        collision footprints, ray casting, rasterisation, templates               │
│ nav/          A*, soft inflation, pure pursuit, EKF, scan matching, log-odds mapping    │
│ physics/      PhysicsBackend adapter: builtin_planar · mujoco                           │
│ cosim/        Bus, DelayLine, subsystems, Coordinator, live sessions                    │
│ twin.py       actuator → motor → driver → controller pin → firmware → battery           │
│ firmware/     targets (validated modes), PlatformIO codegen/build, HIL protocol         │
│ export/       .rvproj package, ROS 2 package, Gazebo world                              │
│ integrations  tool detection + resources                                                 │
├──────────────────────────────── Persistence ─────────────────────────────────────────┤
│ SQLAlchemy: projects (JSON document), sim_runs (config, metrics, events, telemetry),   │
│ validation_reports, user_components (versioned), favorites, assets (original files)    │
│ SQLite by default; PostgreSQL via ROBOVERSE_DATABASE_URL                                │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### Why a single project document

Every workspace edits the same `Project` (see `backend/roboverse/schemas/project.py`). Cross-domain links are explicit `twin_id`s on actuators/sensors, circuit instances and firmware channels, and `TwinBinding` records. The twin resolver (`engines/twin.py`) follows **actual wires** (through level shifters that declare pass-through pins). A part placed in the 3D scene, or a motor that is listed but unwired, does not create an electrical connection; the simulator logs `unbound_actuator` and applies zero torque.

### Background work

Simulations run in a worker thread per session; frames are pushed to subscribers through `asyncio` queues (oldest frames are dropped rather than blocking the solver). This keeps the deployment to one process. When runs must survive restarts or scale out, the `SimSession` interface maps directly onto a Redis-backed job queue: the coordinator is already a pure function of `(project, seed)` and results are persisted by the `on_finish` hook.

## 3. Co-simulation strategy

* **Clock** — fixed macro step `dt` (default 5 ms). Physics and electrical run every step; other subsystems run at their own rates on the same clock (encoders 200 Hz, IMU 100 Hz, firmware loop configurable, local controller 20 Hz, LiDAR 10 Hz, mission 10 Hz, planner 2 Hz, mapping 2 Hz, perception 5 Hz).
* **Coupling** — loosely coupled, explicit (Jacobi/Gauss-Seidel by order), zero-order hold. Each subsystem declares `inputs`/`outputs`; at initialisation the coordinator verifies every input has a producer and reports each edge as `same_step` or `one_step_delay` (e.g. sensors read last step's physics state). The report is shown in the UI and stored with the run.
* **Order** — world → encoders → IMU → LiDAR → localisation → mission → planner → local controller → firmware (with communication `DelayLine`) → electrical → physics → mapping → perception.
* **Initialisation** — twin resolution → backend init (+ reflected rotor inertia) → subsystems in order → contract check → t = 0 telemetry snapshot.
* **Errors** — an exception in a required subsystem stops the run with status `error` and a critical event. Optional subsystems (mapping, perception) are disabled with a warning.
* **Determinism** — all randomness comes from one seeded generator; identical configuration + seed reproduces the run (tested).
* **MuJoCo timing** — the MuJoCo timestep is chosen to divide the macro step exactly; otherwise the physics clock drifts from the coordinator clock (found and fixed during development).

The electrical model is an *analytical* co-simulation (average-value H-bridge, quasi-static motor current). The MNA solver is used for static circuit analysis; true transistor-level coupled electro-mechanical co-simulation would require an ngspice shared-library loop and is listed on the roadmap.

## 4. Integration evaluation

| Tool | License | Role in RoboVerse | Integration |
|---|---|---|---|
| MuJoCo | Apache-2.0 | 3D rigid-body physics backend | **In-process** (pip), MJCF generated from the project |
| Manifold (`manifold3d`) | Apache-2.0 | Parametric CAD kernel (extrude, booleans) | **In-process** (pip) |
| Three.js / React Three Fiber / drei | MIT | 3D visualisation | Frontend |
| ngspice | BSD-3 (mostly) | Full SPICE | Subprocess adapter (`-b`, ASCII rawfile parser); netlist export |
| KiCad | GPL-3.0 | Schematic/PCB | Separate process; KiCad netlist (format "E") export for Pcbnew |
| FreeCAD / OCCT | LGPL | B-rep CAD, STEP | Separate process (detected); STEP is not faked from meshes |
| Gazebo Sim | Apache-2.0 | High-fidelity simulation | SDF model + world + ROS 2 launch export |
| ROS 2 / Nav2 / MoveIt 2 | Apache-2.0 / BSD | Middleware, navigation, manipulation | Generated package (URDF + ros2_control + Nav2 params); built-in planner/EKF used when ROS 2 is absent |
| PlatformIO | Apache-2.0 | Firmware builds | Subprocess (`pio run`), diagnostics parsed |
| QEMU / Renode | GPL / MIT | MCU emulation | Not validated for the listed boards → `emulated` mode refused |
| PyBullet, Webots | zlib / Apache-2.0 | Alternative physics | `PhysicsBackend` adapter slot |
| OpenCV, Open3D | Apache-2.0 / MIT | Perception | Detected; optional modules |

GPL tools are only ever invoked as separate processes; nothing GPL is linked into the application.

## 5. Validation coverage

* **Robot** — duplicate names, missing base link, joints referencing missing links, self-joints, zero/un-normalised axes, missing/invalid limits, kinematic loops, disconnected assemblies, unreachable links, mesh without asset, non-positive sizes, massless links, invalid inertia, unit sanity (mm vs m), sensors/actuators on missing links/joints, actuators on fixed joints, REP-103 wheel axes, wheels on both sides, wheel-separation mismatch, speed vs motor no-load speed, torque vs stall torque, traction, tipping.
* **Electrical / compatibility** — shorted rails, supply-to-ground shorts, parallel supplies, supply over/under-voltage (incl. end-of-discharge), unpowered parts, missing grounds, no common ground reference, push-pull contention, logic over-voltage (5 V → 3.3 V), logic-high margin (incl. VIH that depends on the receiver's supply), floating inputs, UART TX↔TX / RX↔RX, I²C SDA↔SCL, missing I²C pull-ups, pull-ups above an input's rating, CAN H↔L, SPI MOSI↔MISO, pin capability (hardware PWM, UART, I²C, CAN), motor driven from GPIO, motor split across channels, stall vs driver peak/continuous, motor over/under-volted, LED without resistor, relay coil on GPIO, rail overload, battery discharge limit, fuse sizing, connector rating, linear-regulator dissipation, missing battery fuse.
* **Twin** — controller missing, firmware pins that don't exist, actuator without motor, motor/actuator part mismatch, motor without driver, driver input not wired to the controller, PWM pin missing from firmware, firmware function mismatch, unpowered driver, encoder not wired, sensors without electrical counterpart.
* **Firmware** — unknown target, unvalidated execution mode, board/target mismatch, duplicate pins, pin lacking the configured function, optimistic loop rates.
* **World / simulation / export** — duplicate ids, bounds, objects outside bounds, start inside an obstacle, goals inside obstacles or outside the world, missing charger for docking, timestep range, controller vs physics rate, backend availability and drive-type support, imported parts without meshes, missing PCB footprints.

## 6. Roadmap (not yet implemented)

1. ngspice shared-library co-simulation loop for transistor-level motor-driver models.
2. FreeCAD worker for STEP import/export, fillets and chamfers; STEP → mesh for simulation.
3. ROS 2 bridge backend (live `/cmd_vel`, `/odom`, `/scan` against Gazebo or real hardware) as a `PhysicsBackend` + sensor source, with data labelled `hardware`.
4. HIL serial bridge service implementing `HIL_PROTOCOL.txt` against the generated firmware.
5. Camera/depth rendering for vision modules (offscreen MuJoCo renderer) and OpenCV detectors.
6. Library expansion through the import pipeline (KiCad symbol/footprint libraries, vendor CSV exports) — parts enter as `imported_unverified` and are promoted only after review.
7. Redis/RQ job queue for batch parameter sweeps; multi-user auth.
8. Mecanum/omni and Ackermann dynamics in the planar engine (currently MuJoCo-only), robotic-arm control (MoveIt 2 export exists via URDF).
