import { Edges } from '@react-three/drei'
import type { ThreeEvent } from '@react-three/fiber'
import { useMemo } from 'react'
import * as THREE from 'three'
import type { Link, Robot, WorldObject } from '../types'

/** World objects are authored in Z-up (ROS REP-103); the scene root is rotated so three.js (Y-up) shows them correctly. */
export const ZUP = new THREE.Euler(-Math.PI / 2, 0, 0)

export function WorldObjectMesh({ o, selected, showCollision, onSelect, wireframe }: {
  o: WorldObject; selected?: boolean; showCollision?: boolean; onSelect?: (e: ThreeEvent<MouseEvent>) => void; wireframe?: boolean
}) {
  const [x, y, z] = o.pose.xyz
  const [rx, ry, rz] = o.pose.rpy
  const transparent = o.kind === 'loading_zone' || o.kind === 'floor'
  if (o.shape === 'marker') {
    return (
      <group position={[x, y, 0.01]} onClick={onSelect}>
        <mesh rotation={[Math.PI / 2, 0, 0]}><cylinderGeometry args={[0.18, 0.18, 0.02, 32]} /><meshStandardMaterial color={o.color} emissive={o.color} emissiveIntensity={0.4} /></mesh>
        <mesh position={[0, 0, 0.35]}><coneGeometry args={[0.08, 0.25, 16]} /><meshStandardMaterial color={o.color} /></mesh>
        {selected && <mesh rotation={[Math.PI / 2, 0, 0]}><torusGeometry args={[0.26, 0.015, 8, 48]} /><meshBasicMaterial color="#ffd166" /></mesh>}
      </group>
    )
  }
  const h = o.size[2]
  return (
    <group position={[x, y, z + (o.shape === 'plane' ? 0 : h / 2)]} rotation={[rx, ry, rz]} onClick={onSelect}>
      <mesh castShadow={!transparent} receiveShadow rotation={o.shape === 'cylinder' ? [Math.PI / 2, 0, 0] : [0, 0, 0]}>
        {o.shape === 'cylinder'
          ? <cylinderGeometry args={[o.size[0], o.size[0], h, 32]} />
          : <boxGeometry args={[o.size[0], o.size[1], Math.max(h, 0.005)]} />}
        <meshStandardMaterial color={o.color} transparent={transparent} opacity={o.kind === 'loading_zone' ? 0.45 : 1}
          wireframe={wireframe} roughness={0.75} metalness={0.05} />
        {selected && <Edges color="#ffd166" lineWidth={2} />}
      </mesh>
      {showCollision && o.collision.enabled && o.shape !== 'plane' && (
        <mesh rotation={o.shape === 'cylinder' ? [Math.PI / 2, 0, 0] : [0, 0, 0]}>
          {o.shape === 'cylinder' ? <cylinderGeometry args={[o.size[0] * 1.01, o.size[0] * 1.01, h * 1.01, 24]} /> : <boxGeometry args={[o.size[0] * 1.01, o.size[1] * 1.01, h * 1.01]} />}
          <meshBasicMaterial color="#ff4d6d" wireframe transparent opacity={0.6} />
        </mesh>
      )}
    </group>
  )
}

// ---------- robot kinematics (mirror of backend link_world_poses) ----------

export function linkPoses(robot: Robot): Record<string, THREE.Matrix4> {
  const out: Record<string, THREE.Matrix4> = {}
  const childOf = new Set(robot.joints.map((j) => j.child))
  const roots = robot.links.filter((l) => !childOf.has(l.name)).map((l) => l.name)
  const stack: [string, THREE.Matrix4][] = roots.map((r) => [r, new THREE.Matrix4()])
  while (stack.length) {
    const [name, m] = stack.pop()!
    if (out[name]) continue
    out[name] = m
    for (const j of robot.joints.filter((jj) => jj.parent === name)) {
      const local = new THREE.Matrix4().compose(
        new THREE.Vector3(...(j.origin.xyz as [number, number, number])),
        new THREE.Quaternion().setFromEuler(new THREE.Euler(j.origin.rpy[0], j.origin.rpy[1], j.origin.rpy[2], 'ZYX')),
        new THREE.Vector3(1, 1, 1))
      stack.push([j.child, m.clone().multiply(local)])
    }
  }
  return out
}

function LinkMesh({ link, m, selected, onSelect }: { link: Link; m: THREE.Matrix4; selected?: boolean; onSelect?: () => void }) {
  const g = link.geometry
  const local = useMemo(() => new THREE.Matrix4().compose(
    new THREE.Vector3(...(link.origin.xyz as [number, number, number])),
    new THREE.Quaternion().setFromEuler(new THREE.Euler(link.origin.rpy[0], link.origin.rpy[1], link.origin.rpy[2], 'ZYX')),
    new THREE.Vector3(1, 1, 1)), [link.origin])
  const world = useMemo(() => m.clone().multiply(local), [m, local])
  if (!g || g.type === 'mesh') return null
  return (
    <mesh matrix={world} matrixAutoUpdate={false} castShadow onClick={(e) => { e.stopPropagation(); onSelect?.() }}>
      {g.type === 'box' && <boxGeometry args={[g.size[0], g.size[1], g.size[2]]} />}
      {/* URDF cylinders are along z; three cylinders along y -> rotate geometry */}
      {g.type === 'cylinder' && <cylinderGeometry args={[g.size[0], g.size[0], g.size[2], 32]} onUpdate={(geo) => geo.rotateX(Math.PI / 2)} />}
      {g.type === 'sphere' && <sphereGeometry args={[g.size[0], 24, 16]} />}
      <meshStandardMaterial color={selected ? '#ffd166' : link.color} roughness={0.55} metalness={0.2} />
    </mesh>
  )
}

export function RobotModel({ robot, selectedLink, onSelectLink, frames }: {
  robot: Robot; selectedLink?: string | null; onSelectLink?: (n: string) => void; frames?: boolean
}) {
  const poses = useMemo(() => linkPoses(robot), [robot])
  return (
    <group>
      {robot.links.map((l) => poses[l.name] && (
        <LinkMesh key={l.name} link={l} m={poses[l.name]} selected={selectedLink === l.name} onSelect={() => onSelectLink?.(l.name)} />
      ))}
      {frames && Object.entries(poses).map(([n, m]) => <axesHelper key={n} args={[0.06]} matrix={m} matrixAutoUpdate={false} />)}
    </group>
  )
}

/** Text label rendered as a camera-facing sprite (pure WebGL, no DOM overlay to tear down). */
export function Label({ text, position, color = '#e8ecf1', bg = 'rgba(22,27,34,0.85)', size = 0.35 }: {
  text: string; position: [number, number, number]; color?: string; bg?: string; size?: number
}) {
  const tex = useMemo(() => {
    const c = document.createElement('canvas')
    const g = c.getContext('2d')!
    const font = '600 40px Inter, system-ui, sans-serif'
    g.font = font
    const w = Math.ceil(g.measureText(text).width) + 28
    c.width = w; c.height = 60
    g.font = font
    g.fillStyle = bg
    g.beginPath(); g.roundRect(0, 0, w, 60, 14); g.fill()
    g.fillStyle = color; g.textBaseline = 'middle'; g.fillText(text, 14, 31)
    const t = new THREE.CanvasTexture(c)
    t.colorSpace = THREE.SRGBColorSpace
    return { t, aspect: w / 60 }
  }, [text, color, bg])
  return (
    <sprite position={position} scale={[size * tex.aspect, size, 1]} renderOrder={10}>
      <spriteMaterial map={tex.t} depthTest={false} transparent />
    </sprite>
  )
}
