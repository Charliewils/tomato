import { Suspense, Component, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { useGLTF, Html } from '@react-three/drei'
import * as THREE from 'three'
import { MODEL_ENABLED, MODEL_URL, PLANT_TARGET_H, DISEASE_CN } from './config'

function rng(seed) {
  let s = (seed * 9301 + 49297) % 233280
  return () => {
    s = (s * 9301 + 49297) % 233280
    return s / 233280
  }
}

const GREEN = ['#3f7a36', '#4a8a3e', '#356b2e', '#46813a']
const FRUIT = { green: '#74b03f', breaker: '#e0902a', red: '#d83a2b' }

function Procedural({ seed }) {
  const parts = useMemo(() => {
    const r = rng(seed + 1)
    const H = 1.45 + r() * 0.35
    const clumps = []
    for (let i = 0; i < 8; i++) {
      const t = 0.22 + (i / 8) * 0.74
      const ang = r() * Math.PI * 2
      const rad = 0.16 + r() * 0.16
      clumps.push({
        pos: [Math.cos(ang) * rad, H * t, Math.sin(ang) * rad],
        sc: [0.3 + r() * 0.16, 0.13 + r() * 0.06, 0.3 + r() * 0.16],
        rot: [r() * 0.5 - 0.25, ang, r() * 0.5 - 0.25],
        col: GREEN[i % GREEN.length],
      })
    }
    const trusses = []
    for (let i = 0; i < 3; i++) {
      const ang = r() * Math.PI * 2
      const rad = 0.2 + r() * 0.08
      const y = H * (0.38 + i * 0.18)
      const fruits = []
      const fn = 4 + Math.floor(r() * 3)
      for (let k = 0; k < fn; k++) {
        const kind = r()
        const col = kind < 0.55 ? FRUIT.green : kind < 0.8 ? FRUIT.red : FRUIT.breaker
        fruits.push({ pos: [(r() - 0.5) * 0.14, -0.06 - k * 0.03 - r() * 0.04, (r() - 0.5) * 0.14], col, rad: 0.042 + r() * 0.022 })
      }
      trusses.push({ at: [Math.cos(ang) * rad, y, Math.sin(ang) * rad], fruits })
    }
    return { H, clumps, trusses }
  }, [seed])

  return (
    <group>
      <mesh position={[0.06, parts.H * 0.5 + 0.1, 0.04]}>
        <cylinderGeometry args={[0.012, 0.012, parts.H + 0.25, 6]} />
        <meshStandardMaterial color="#b8a06a" roughness={0.8} />
      </mesh>
      <mesh position={[0, parts.H * 0.5, 0]}>
        <cylinderGeometry args={[0.018, 0.035, parts.H, 6]} />
        <meshStandardMaterial color="#4a6e34" roughness={0.85} />
      </mesh>
      {parts.clumps.map((c, i) => (
        <mesh key={i} position={c.pos} scale={c.sc} rotation={c.rot}>
          <icosahedronGeometry args={[1, 1]} />
          <meshStandardMaterial color={c.col} roughness={0.8} flatShading />
        </mesh>
      ))}
      {parts.trusses.map((t, i) => (
        <group key={i} position={t.at}>
          {t.fruits.map((f, k) => (
            <mesh key={k} position={f.pos}>
              <sphereGeometry args={[f.rad, 8, 8]} />
              <meshStandardMaterial color={f.col} roughness={0.35} />
            </mesh>
          ))}
        </group>
      ))}
    </group>
  )
}

function GltfPlant() {
  const { scene } = useGLTF(MODEL_URL)
  const obj = useMemo(() => {
    const c = scene.clone(true)
    const size = new THREE.Box3().setFromObject(c).getSize(new THREE.Vector3())
    c.scale.setScalar(PLANT_TARGET_H / (size.y || 1))
    const b = new THREE.Box3().setFromObject(c)
    c.position.set(-(b.min.x + b.max.x) / 2, -b.min.y, -(b.min.z + b.max.z) / 2)
    return c
  }, [scene])
  return <primitive object={obj} />
}

class Boundary extends Component {
  state = { err: false }
  static getDerivedStateFromError() {
    return { err: true }
  }
  render() {
    return this.state.err ? this.props.fallback : this.props.children
  }
}

function StatusRing({ active, diseased }) {
  const ref = useRef()
  useFrame((s) => {
    if (!ref.current) return
    const pulse = Math.sin(s.clock.elapsedTime * 4) * 0.5 + 0.5
    ref.current.material.emissiveIntensity = active ? 0.7 + pulse * 0.9 : diseased ? 0.4 + pulse * 0.5 : 0.18
  })
  const color = diseased ? '#ff4d4d' : active ? '#34e3ff' : '#46e06a'
  return (
    <mesh ref={ref} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.03, 0]}>
      <ringGeometry args={[0.42, 0.56, 40]} />
      <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.2} transparent opacity={0.9} side={THREE.DoubleSide} />
    </mesh>
  )
}

function badgeStyle(active, diseased, scanned) {
  if (!scanned) return {
    background: '#0b1a14aa', color: '#8ba398', padding: '3px 7px', borderRadius: 6, fontSize: 10,
    whiteSpace: 'nowrap', border: '1px dashed #4a655a', pointerEvents: 'none',
    fontFamily: 'system-ui,Microsoft YaHei', textAlign: 'center',
  }
  const edge = diseased ? '#ff6b6b' : active ? '#34e3ff' : '#46e06a'
  return {
    background: diseased ? '#7a1414ee' : active ? '#0b3a4aee' : '#0b2a1aee',
    color: '#fff', padding: '5px 9px', borderRadius: 7, fontSize: 12, lineHeight: 1.5,
    whiteSpace: 'nowrap', border: `1px solid ${edge}`, pointerEvents: 'none',
    fontFamily: 'system-ui,Microsoft YaHei', textAlign: 'center',
    boxShadow: active ? '0 0 14px #34e3ff88' : 'none',
  }
}

export default function Plant({ id, position, rotation, scale = 1, seed = 0, state, current, focus, onSelect }) {
  const diseased = state?.disease
  const scanned = state?.scanned
  const showBadge = true

  return (
    <group
      position={position}
      rotation={rotation}
      userData={{ plant: id }}
      onClick={(e) => { e.stopPropagation(); onSelect && onSelect(id) }}
      onPointerOver={() => { document.body.style.cursor = 'pointer' }}
      onPointerOut={() => { document.body.style.cursor = 'auto' }}
    >
      <group scale={scale}>
        {MODEL_ENABLED ? (
          <Boundary fallback={<Procedural seed={seed} />}>
            <Suspense fallback={<Procedural seed={seed} />}>
              <GltfPlant />
            </Suspense>
          </Boundary>
        ) : (
          <Procedural seed={seed} />
        )}
      </group>

      {scanned && <StatusRing active={current} diseased={!!diseased} />}

      {showBadge && (
        <Html position={[0, PLANT_TARGET_H * scale + 0.25, 0]} center distanceFactor={9}>
          <div style={badgeStyle(current, !!diseased, scanned)}>
            <div>
              {current ? '🎥 ' : ''}#{id + 1}{scanned ? ` · 🍅 ${state.ripe}红 ${state.half}半 ${state.green}青` : ''}
            </div>
            {diseased && <div style={{ color: '#ffd2d2' }}>⚠ {DISEASE_CN[diseased] || diseased}</div>}
            {scanned && <div style={{ color: '#bfe3ff', fontSize: 11 }}>
              ≈ {state.est >= 1000 ? (state.est / 1000).toFixed(2) + ' kg' : Math.round(state.est || 0) + ' g'}{current ? ' · 记录中' : ''}
            </div>}
          </div>
        </Html>
      )}
    </group>
  )
}

if (MODEL_ENABLED) useGLTF.preload(MODEL_URL)
