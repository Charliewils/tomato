import { Suspense, Component, useMemo } from 'react'
import { useGLTF } from '@react-three/drei'
import * as THREE from 'three'
import { GREENHOUSE_URL } from './config'

const TARGET_SPAN = 17        // 温室最大水平尺寸(米), 归一化目标

function Model() {
  const { scene } = useGLTF(GREENHOUSE_URL)
  const obj = useMemo(() => {
    const c = scene.clone(true)
    let box = new THREE.Box3().setFromObject(c)
    const size = box.getSize(new THREE.Vector3())
    const s = TARGET_SPAN / Math.max(size.x, size.z || 1)
    c.scale.setScalar(s)
    box = new THREE.Box3().setFromObject(c)
    c.position.set(-(box.min.x + box.max.x) / 2, -box.min.y, -(box.min.z + box.max.z) / 2)
    c.traverse((o) => {                 // 贴图转换时丢失, 按材质名赋纯色; 仅覆盖板半透明
      if (!o.isMesh || !o.material) return
      const mats = Array.isArray(o.material) ? o.material : [o.material]
      mats.forEach((m) => {
        const n = (m.name || '').toLowerCase()
        m.side = THREE.DoubleSide
        m.transparent = false; m.opacity = 1; m.depthWrite = true
        if (n.includes('zinc')) { m.color.set('#b3bcc3'); m.metalness = 0.7; m.roughness = 0.35 }
        else if (n.includes('steel')) { m.color.set('#929da4'); m.metalness = 0.7; m.roughness = 0.4 }
        else if (n.includes('earth')) { m.color.set('#735a42'); m.metalness = 0; m.roughness = 1 }
        else if (n.includes('#25')) { m.color.set('#9c7d59'); m.metalness = 0.1; m.roughness = 0.75 }
        else { m.color.set('#d8edf7'); m.transparent = true; m.opacity = 0.15; m.depthWrite = false; m.roughness = 0.1; m.metalness = 0 }
      })
    })
    return c
  }, [scene])
  return <primitive object={obj} />
}

class Boundary extends Component {
  state = { err: false }
  static getDerivedStateFromError() { return { err: true } }
  render() { return this.state.err ? this.props.fallback : this.props.children }
}

// ---- 程序化 fallback (模型加载失败时) ----
const HALF_W = 8, HALF_D = 5, EAVE = 2.6, RIDGE = 4.3, FRAME = '#e6ecee'
const TRUSS_Z = [-5, -3.33, -1.67, 0, 1.67, 3.33, 5]
const slopeLen = Math.hypot(HALF_W, RIDGE - EAVE)
const slopeAngle = Math.atan2(RIDGE - EAVE, HALF_W)

function Strut({ a, b, r = 0.045 }) {
  const start = new THREE.Vector3(...a), end = new THREE.Vector3(...b)
  const mid = start.clone().add(end).multiplyScalar(0.5)
  const len = start.distanceTo(end)
  const quat = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), end.clone().sub(start).normalize())
  return (
    <mesh position={mid.toArray()} quaternion={quat.toArray()}>
      <cylinderGeometry args={[r, r, len, 8]} />
      <meshStandardMaterial color={FRAME} metalness={0.5} roughness={0.4} />
    </mesh>
  )
}

function Glass({ position, args, rotation }) {
  return (
    <mesh position={position} rotation={rotation}>
      <boxGeometry args={args} />
      <meshStandardMaterial color="#cfeefc" transparent opacity={0.16} roughness={0.06} side={THREE.DoubleSide} />
    </mesh>
  )
}

function Procedural() {
  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]}>
        <planeGeometry args={[2 * HALF_W, 2 * HALF_D]} />
        <meshStandardMaterial color="#7d6450" roughness={1} />
      </mesh>
      {[-4.5, -1.5, 1.5, 4.5].map((x) => (
        <mesh key={x} position={[x, 0.09, 0]}>
          <boxGeometry args={[1.05, 0.18, 7.2]} />
          <meshStandardMaterial color="#5b4632" roughness={1} />
        </mesh>
      ))}
      {TRUSS_Z.map((z, i) => (
        <group key={i}>
          <Strut a={[HALF_W, 0, z]} b={[HALF_W, EAVE, z]} />
          <Strut a={[-HALF_W, 0, z]} b={[-HALF_W, EAVE, z]} />
          <Strut a={[HALF_W, EAVE, z]} b={[0, RIDGE, z]} />
          <Strut a={[-HALF_W, EAVE, z]} b={[0, RIDGE, z]} />
        </group>
      ))}
      <Strut a={[0, RIDGE, -HALF_D]} b={[0, RIDGE, HALF_D]} r={0.06} />
      <Glass position={[HALF_W, EAVE / 2, 0]} args={[0.04, EAVE, 2 * HALF_D]} />
      <Glass position={[-HALF_W, EAVE / 2, 0]} args={[0.04, EAVE, 2 * HALF_D]} />
      <Glass position={[HALF_W / 2, (EAVE + RIDGE) / 2, 0]} args={[slopeLen, 0.03, 2 * HALF_D]} rotation={[0, 0, -slopeAngle]} />
      <Glass position={[-HALF_W / 2, (EAVE + RIDGE) / 2, 0]} args={[slopeLen, 0.03, 2 * HALF_D]} rotation={[0, 0, slopeAngle]} />
    </group>
  )
}

export default function Greenhouse() {
  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.03, 0]}>
        <planeGeometry args={[90, 70]} />
        <meshStandardMaterial color="#9cc06f" roughness={1} />
      </mesh>
      <Boundary fallback={<Procedural />}>
        <Suspense fallback={<Procedural />}>
          <Model />
        </Suspense>
      </Boundary>
    </group>
  )
}

useGLTF.preload(GREENHOUSE_URL)
