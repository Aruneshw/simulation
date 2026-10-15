// Mirrors backend/roboverse/schemas (subset used by the UI).

export type Vec3 = [number, number, number]
export interface Pose { xyz: number[]; rpy: number[] }

export interface WorldObject {
  id: string
  name: string
  kind: string
  shape: 'box' | 'cylinder' | 'plane' | 'mesh' | 'marker'
  size: number[]
  pose: Pose
  color: string
  static: boolean
  collision: { enabled: boolean; friction: number; restitution: number }
  motion?: { type: 'patrol'; waypoints: number[][]; speed: number } | null
  mesh_ref?: string | null
  parent?: string | null
  props: Record<string, unknown>
}

export interface World { template?: string | null; bounds: number[]; gravity: number[]; objects: WorldObject[] }

export interface Geometry { type: 'box' | 'cylinder' | 'sphere' | 'mesh'; size: number[]; mesh_ref?: string | null }
export interface Link { name: string; geometry?: Geometry | null; origin: Pose; mass: number; material: string; inertia?: number[] | null; color: string }
export interface Joint {
  name: string; type: 'fixed' | 'continuous' | 'revolute' | 'prismatic'; parent: string; child: string
  origin: Pose; axis: number[]; limits?: { lower: number; upper: number; effort: number; velocity: number } | null
}
export interface Drivetrain {
  drive_type: string; wheel_radius: number; wheel_width: number; wheel_separation: number; wheel_friction: number
  gear_ratio: number; max_speed: number; max_accel: number; max_decel: number; max_steering_angle: number
  payload_kg: number; rolling_resistance: number
}
export interface Actuator { id: string; twin_id: string; joint: string; component_ref: string; role: string }
export interface Sensor {
  id: string; twin_id: string; type: string; link: string; pose: Pose; rate_hz: number; noise_std: number
  component_ref?: string | null; params: Record<string, number>
}
export interface Robot {
  name: string; base_link: string; links: Link[]; joints: Joint[]; drivetrain: Drivetrain
  actuators: Actuator[]; sensors: Sensor[]
  power: { battery_ref?: string | null; base_load_w?: number | null; driver_efficiency: number }
  controller_ref?: string | null
}

export interface ComponentInstance {
  id: string; component_id: string; position: number[]; rotation: number; params: Record<string, unknown>; twin_id?: string | null
}
export interface PinRef { instance: string; pin: string }
export interface Wire { id: string; a: PinRef; b: PinRef; label?: string | null }
export interface Circuit { instances: ComponentInstance[]; wires: Wire[] }

export interface PinAssignment { channel: string; pin: string; function: string; twin_id?: string | null }
export interface Firmware {
  target: string; mode: string
  controller: { type: string; loop_hz: number; kp: number; ki: number; kd: number; feedforward: number }
  pin_map: PinAssignment[]
  files: { path: string; content: string }[]
}

export interface Feature { id: string; op: string; params: Record<string, unknown>; sketch?: { type: string; params: Record<string, unknown> }[] | null; operands: string[] }
export interface CadPart {
  id: string; name: string; kind: 'parametric' | 'imported_mesh'; material: string
  parameters: Record<string, number>; features: Feature[]; result?: string | null; mesh_ref?: string | null; twin_id?: string | null
}
export interface Cad { parts: CadPart[]; assembly: { id: string; part: string; pose: Pose; link?: string | null }[]; mates: unknown[] }

export interface Scenario {
  mode: 'goal' | 'waypoints' | 'teleop' | 'dock' | 'open_loop'
  waypoints: number[][]; goal?: number[] | null; return_to_dock: boolean; dock_object?: string | null
  estop_at?: number | null; open_loop_cmd: number[]
}
export interface SimulationConfig {
  physics_backend: 'builtin_planar' | 'mujoco'; dt: number; duration: number; seed: number; real_time_factor: number
  sensor_noise: boolean; comm_latency_ms: number; ambient_c: number; scenario: Scenario; telemetry_hz: number
  localization_scan_matching: boolean
}
export interface TwinBinding { twin_id: string; label: string; mechanical?: string | null; electrical?: string | null; firmware_channels: string[]; sim_entity?: string | null }

export interface Project {
  schema_version: number; id?: string | null; name: string; type: string; description: string
  world: World; robot: Robot; circuit: Circuit; firmware: Firmware; cad: Cad; simulation: SimulationConfig
  bindings: TwinBinding[]; preserved: Record<string, unknown>
}

export interface SpecRef { component: string; field: string; value?: number | string | null; unit: string; source: string; url?: string | null }
export interface Issue {
  code: string; severity: 'critical' | 'error' | 'warning' | 'info'; domain: string; title: string; message: string
  connection?: string | null; refs: string[]; specs: SpecRef[]; fix: string
}

export interface Pin {
  id: string; name: string; type: string; v_min?: number | null; v_max?: number | null; v_nominal?: number | null
  i_max?: number | null; logic_v?: number | null; vih_min?: number | null; v_abs_max?: number | null
  five_v_tolerant?: boolean | null; required: boolean; capabilities: string[]; group?: string | null
}
export interface Rated { value?: number | null; unit: string; source: string; note: string }
export interface Component {
  id: string; version: string; name: string; category: string; tags: string[]; manufacturer?: string | null
  part_number?: string | null; description: string; symbol: string; footprint?: string | null; pins: Pin[]
  interfaces: string[]; ratings: Record<string, Rated>; params: Record<string, unknown>; sim_model?: string | null
  support_status: string; datasheet?: string | null; compatibility: string[]; dependencies: string[]
  provenance: { source: string; author: string; license: string; url?: string | null; verified: boolean; notes: string }
}

export type Workspace = 'dashboard' | 'world' | 'cad' | 'robot' | 'circuit' | 'twin' | 'firmware' | 'sim' | 'ai' | 'library' | 'validation' | 'export'
