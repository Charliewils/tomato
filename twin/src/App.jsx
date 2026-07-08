import { useState, useMemo, useEffect, useRef } from 'react'
import { Canvas, useThree, useFrame } from '@react-three/fiber'
import { Sky, ContactShadows, OrbitControls } from '@react-three/drei'
import { EffectComposer, Bloom } from '@react-three/postprocessing'
import * as THREE from 'three'
import Greenhouse from './Greenhouse'
import Plants from './Plants'
import { useLiveData, usePlants, useHistory } from './data'
import { PLANT_COUNT, DISEASE_CN } from './config'

function Diag() {
  const { scene } = useThree()
  const done = useRef(false)
  useFrame(() => {
    if (done.current) return
    const groups = {}
    scene.traverse((o) => {
      if (!o.isMesh) return
      const m = Array.isArray(o.material) ? o.material[0] : o.material
      const nm = m?.name || '?'
      const b = new THREE.Box3().setFromObject(o)
      if (!groups[nm]) groups[nm] = { x0: 1e9, x1: -1e9, z0: 1e9, z1: -1e9, ymax: -1e9, n: 0 }
      const g = groups[nm]
      g.x0 = Math.min(g.x0, b.min.x); g.x1 = Math.max(g.x1, b.max.x)
      g.z0 = Math.min(g.z0, b.min.z); g.z1 = Math.max(g.z1, b.max.z)
      g.ymax = Math.max(g.ymax, b.max.y); g.n++
    })
    if (!groups['earth2'] && !groups['Material #25']) return
    done.current = true
    const fmt = (g) => ({ cx: +((g.x0 + g.x1) / 2).toFixed(2), x: [+g.x0.toFixed(1), +g.x1.toFixed(1)], z: [+g.z0.toFixed(1), +g.z1.toFixed(1)], ymax: +g.ymax.toFixed(2), n: g.n })
    const mats = {}; for (const k in groups) mats[k] = fmt(groups[k])
    const plants = []
    scene.traverse((o) => { if (o.userData?.plant !== undefined) { const p = new THREE.Vector3(); o.getWorldPosition(p); plants.push({ id: o.userData.plant, x: +p.x.toFixed(2), z: +p.z.toFixed(2) }) } })
    window.__diag = { mats, plants }
  })
  return null
}

const C = {
  ink: '#1c2b24', ink2: '#54665d', ink3: '#869389', ink4: '#a7b6ad',
  accent: '#1f9d57', accentDeep: '#147a44', accentSoft: 'rgba(31,157,87,0.12)', accentGlow: 'rgba(31,157,87,0.28)',
  sky: '#2f9bd6', skyDeep: '#1f7a8c', skySoft: 'rgba(47,155,214,0.13)', skyRing: 'rgba(47,155,214,0.30)',
  temp: '#e07b39', tempSoft: 'rgba(224,123,57,0.12)',
  humid: '#2f9bb8', humidSoft: 'rgba(47,155,184,0.12)',
  co2: '#7a5cc0', co2Soft: 'rgba(122,92,192,0.12)',
  light: '#d99a1e', lightSoft: 'rgba(217,154,30,0.13)',
  soil: '#1f9d57', soilSoft: 'rgba(31,157,87,0.12)',
  danger: '#e2564f', dangerSoft: 'rgba(226,86,79,0.10)', dangerBorder: 'rgba(226,86,79,0.30)',
  hair: 'rgba(31,60,44,0.08)', track: 'rgba(31,60,44,0.10)',
}

const luxToIntensity = (lux) => 0.55 + Math.min(1, (lux || 0) / 3000) * 2.2
const fmtKg = (g) => (g >= 1000 ? (g / 1000).toFixed(2) + ' kg' : Math.round(g || 0) + ' g')

function useCaptures(ms = 15000) {
  const [fs, setFs] = useState([])
  useEffect(() => {
    const tick = async () => {
      try { const d = await (await fetch('/api/captures')).json(); if (Array.isArray(d)) setFs(d) } catch {}
    }
    tick(); const id = setInterval(tick, ms); return () => clearInterval(id)
  }, [ms])
  return fs
}

function useLatest(ms = 4000) {
  const [d, setD] = useState({})
  useEffect(() => {
    const tick = async () => { try { setD(await (await fetch('/api/latest')).json()) } catch {} }
    tick(); const id = setInterval(tick, ms); return () => clearInterval(id)
  }, [ms])
  return d
}

function Panel({ title, extra, children, flex, style, className = '' }) {
  return (
    <div className={`glass lift ${className}`} style={{
      display: 'flex', flexDirection: 'column', overflow: 'hidden', flex: flex || 'none', minHeight: 0, ...style,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '10px 14px', borderBottom: `1px solid ${C.hair}`, position: 'relative', zIndex: 2 }}>
        <span style={{ width: 3, height: 13, borderRadius: 980, background: 'linear-gradient(180deg,#1f9d57,#147a44)', boxShadow: '0 0 6px rgba(31,157,87,0.35)' }} />
        <span style={{ fontSize: 13, fontWeight: 650, color: C.ink, letterSpacing: .3 }}>{title}</span>
        {extra && <span style={{ marginLeft: 'auto', fontSize: 11, color: C.ink3 }}>{extra}</span>}
      </div>
      <div style={{ padding: 13, flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', position: 'relative', zIndex: 2 }}>{children}</div>
    </div>
  )
}

function SimTag({ sim }) { return null }

function Kpi({ icon, label, value, unit, sim, accent, soft }) {
  const show = value !== undefined && value !== null && value !== ''
  return (
    <div className="glass-inset press" style={{ padding: '10px 12px' }}>
      <div style={{ fontSize: 11.5, color: C.ink2, display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ width: 22, height: 22, borderRadius: 8, background: soft, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 12 }}>{icon}</span>
        {label}{sim !== undefined && <SimTag sim={sim} />}
      </div>
      <div className="tnum" style={{ fontSize: 21, fontWeight: 700, color: show ? accent : C.ink4, lineHeight: 1.3, letterSpacing: -0.2, marginTop: 4 }}>
        {show ? value : '—'}<span style={{ fontSize: 11, color: C.ink3, fontWeight: 600, letterSpacing: 0 }}> {unit}</span>
      </div>
    </div>
  )
}

function Gauge({ gid, label, value, unit, min, max, color, sim }) {
  const has = typeof value === 'number'
  const v = has ? value : 0
  const pct = Math.max(0, Math.min(1, (v - min) / (max - min)))
  const cx = 50, cy = 50, r = 38
  const pt = (p) => { const phi = Math.PI + p * Math.PI; return [cx + r * Math.cos(phi), cy + r * Math.sin(phi)] }
  const [sx, sy] = pt(0), [mx, my] = pt(1), [ex, ey] = pt(pct)
  const arc = Math.PI * r
  return (
    <div style={{ flex: '1 1 0', display: 'flex', flexDirection: 'column', alignItems: 'center', minWidth: 78 }}>
      <svg viewBox="0 0 100 60" style={{ width: '100%', maxWidth: 126 }}>
        <defs>
          <linearGradient id={`gg${gid}`} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor={color} stopOpacity="0.6" /><stop offset="1" stopColor={color} />
          </linearGradient>
          <filter id={`gf${gid}`} x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="1.2" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>
        <path d={`M ${sx} ${sy} A ${r} ${r} 0 0 1 ${mx} ${my}`} fill="none" stroke={C.track} strokeWidth="8" strokeLinecap="round" />
        {has && pct > 0.002 && (
          <path className="draw" d={`M ${sx} ${sy} A ${r} ${r} 0 0 1 ${mx} ${my}`} fill="none" stroke={`url(#gg${gid})`} strokeWidth="8" strokeLinecap="round"
            filter={`url(#gf${gid})`} strokeDasharray={arc} strokeDashoffset={arc * (1 - pct)} />
        )}
        {has && <circle cx={ex} cy={ey} r="4.5" fill="#fff" stroke={color} strokeWidth="2.5" />}
        <text className="tnum" x="50" y="44" textAnchor="middle" fontSize="15" fontWeight="700" fill={has ? C.ink : C.ink4}>{has ? (value % 1 ? value.toFixed(1) : value) : '—'}</text>
        <text x="50" y="56" textAnchor="middle" fontSize="8" fill={C.ink3}>{unit}</text>
      </svg>
      <div style={{ fontSize: 12, color: C.ink2, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 5 }}>
        {label}{sim !== undefined && <SimTag sim={sim} />}
      </div>
    </div>
  )
}

function Trend({ pts, color, label, unit }) {
  const W = 260, H = 78, pad = 6
  if (pts.length < 2) return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 9, padding: '20px 4px', color: C.ink3, fontSize: 12 }}>
      <span>采集中…需 {2 - pts.length} 个采样点</span>
      <span style={{ display: 'flex', gap: 6 }}>
        {[0, 1, 2].map((i) => <i key={i} className="breathe" style={{ width: 5, height: 5, borderRadius: 980, background: color, animationDelay: `${i * 0.18}s` }} />)}
      </span>
    </div>
  )
  const lo = Math.min(...pts), hi = Math.max(...pts), span = hi - lo || 1
  const x = (i) => pad + (i / (pts.length - 1)) * (W - 2 * pad)
  const y = (val) => pad + (1 - (val - lo) / span) * (H - 2 * pad)
  const d = pts.map((p, i) => `${i ? 'L' : 'M'} ${x(i).toFixed(1)} ${y(p).toFixed(1)}`).join(' ')
  const area = `${d} L ${x(pts.length - 1).toFixed(1)} ${H - pad} L ${x(0).toFixed(1)} ${H - pad} Z`
  const lx = x(pts.length - 1), ly = y(pts[pts.length - 1])
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', display: 'block' }}>
        <defs><linearGradient id={`g${label}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={color} stopOpacity="0.28" /><stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient></defs>
        <line x1={pad} y1={H / 2} x2={W - pad} y2={H / 2} stroke="rgba(31,60,44,0.05)" strokeWidth="1" />
        <path d={area} fill={`url(#g${label})`} />
        <path d={d} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" style={{ filter: `drop-shadow(0 1px 3px ${color}38)` }} />
        <circle cx={lx} cy={ly} r="6.5" fill={color} opacity="0.16" />
        <circle cx={lx} cy={ly} r="3" fill={color} />
      </svg>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: C.ink3, marginTop: 3 }}>
        <span>{label}近 {pts.length} 点</span>
        <span>当前 <b className="tnum" style={{ color }}>{pts[pts.length - 1].toFixed(1)}{unit}</b> · 峰 <span className="tnum">{hi.toFixed(1)}</span></span>
      </div>
    </div>
  )
}

function YieldBar({ label, value, total, color, offline }) {
  const pct = total > 0 ? (value / total) * 100 : 0
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, color: C.ink2, marginBottom: 4 }}>
        <span>{label}</span><span className="tnum" style={{ fontWeight: 700, color: offline ? C.ink4 : color }}>{offline ? '—' : value}</span>
      </div>
      <div style={{ height: 7, background: C.hair, borderRadius: 980, overflow: 'hidden' }}>
        <div className="bar-fill" style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 980 }} />
      </div>
    </div>
  )
}

function plantCell(state, current, focus) {
  let bg = 'rgba(255,255,255,0.45)', border = '1px dashed rgba(120,150,134,0.34)', color = C.ink4, ring
  if (state?.scanned) { bg = C.accentSoft; border = '1px solid rgba(31,157,87,0.30)'; color = C.accentDeep }
  if (state?.scanned && state?.disease) { bg = C.dangerSoft; border = `1px solid ${C.dangerBorder}`; color = C.danger }
  if (focus) { border = `1px solid ${C.sky}`; color = C.skyDeep }
  if (current) { bg = C.skySoft; border = `1px solid ${C.sky}`; color = C.skyDeep; ring = `0 0 0 3px ${C.skyRing}` }
  return {
    aspectRatio: '1', background: bg, color, border, borderRadius: 12, fontSize: 13, fontWeight: 600,
    cursor: 'pointer', padding: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontFamily: 'inherit', boxShadow: ring,
  }
}

export default function App() {
  const s = useLiveData()
  const { plants, current, count, summary } = usePlants()
  const latest = useLatest()
  const caps = useCaptures()
  const history = useHistory()
  const [liveTs, setLiveTs] = useState(0)
  const [camOk, setCamOk] = useState(false)
  const [focus, setFocus] = useState(-1)
  const [auto, setAuto] = useState(false)
  const [isNarrow, setIsNarrow] = useState(typeof window !== 'undefined' && window.innerWidth < 1180)
  const tHist = useRef([]); const lHist = useRef([])
  const [, force] = useState(0)

  useEffect(() => {
    const id = setInterval(() => setLiveTs(Date.now()), 2000)
    const onResize = () => setIsNarrow(window.innerWidth < 1180)
    window.addEventListener('resize', onResize)
    return () => { clearInterval(id); window.removeEventListener('resize', onResize) }
  }, [])

  useEffect(() => {
    if (typeof s.temp === 'number') { tHist.current = [...tHist.current, s.temp].slice(-50) }
    if (typeof s.lux === 'number') { lHist.current = [...lHist.current, s.lux].slice(-50) }
    force((n) => n + 1)
  }, [s.time])

  useEffect(() => {
    if (!auto) return
    let i = -1
    const h = setInterval(() => { i = (i + 1) % PLANT_COUNT; setFocus(i) }, 1800)
    return () => clearInterval(h)
  }, [auto])

  const t = useMemo(() => {
    const dis = {}
    for (const p of plants) if (p.scanned && p.disease) dis[p.disease] = (dis[p.disease] || 0) + 1
    const total = (summary.green || 0) + (summary.half || 0) + (summary.ripe || 0)
    return { g: summary.green || 0, h: summary.half || 0, r: summary.ripe || 0, total, est: summary.est || 0, dis }
  }, [plants, summary])

  const pick = (id) => { setAuto(false); setFocus(id) }
  const intensity = luxToIntensity(s.lux)
  const luxK = (v) => (v >= 1000 ? (v / 1000).toFixed(1) : (v || 0).toFixed(0))
  const yieldOffline = t.total === 0

  const LiveCam = (
    <Panel title="实时检测画面" extra={current >= 0 ? `第 ${current + 1} 株` : 'YOLOv8'} flex="0 0 auto">
      <div className="glass-inset" style={{ position: 'relative', aspectRatio: '4/3' }}>
        <div style={{
          position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 4,
          background: 'linear-gradient(160deg, rgba(255,255,255,0.55), rgba(236,246,240,0.55))',
        }}>
          <div style={{ fontSize: 30, opacity: 0.32 }}>📷</div>
          <div style={{ fontSize: 12, color: C.ink3, fontWeight: 600 }}>摄像头离线 · 等待板端推流</div>
          <div style={{ fontSize: 11, color: C.ink4 }}>上线后自动回传画面</div>
          <div className="shimmer" style={{ position: 'absolute', left: 0, right: 0, height: 2, top: '50%', animation: 'scan 3s ease-in-out infinite alternate' }} />
        </div>
        <img src={`/live_cam.jpg?t=${liveTs}`} alt="live" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', display: 'block', opacity: camOk ? 1 : 0, transition: 'opacity .4s' }}
          onError={() => setCamOk(false)} onLoad={(e) => setCamOk(e.currentTarget.naturalWidth > 1)} />
        <div style={{ position: 'absolute', top: 8, left: 9, background: 'rgba(255,255,255,.70)', backdropFilter: 'blur(14px)', WebkitBackdropFilter: 'blur(14px)', color: C.accentDeep, fontSize: 11.5, fontWeight: 700, padding: '2px 9px', borderRadius: 980, border: `1px solid ${C.hair}` }}>🎥 真实摄像头</div>
        {camOk && (
          <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, padding: '14px 9px 7px', display: 'flex', justifyContent: 'space-between', fontSize: 11.5, color: '#fff', textShadow: '0 1px 4px #000', background: 'linear-gradient(transparent, rgba(12,30,18,.55))' }}>
            <span className="tnum">🍅 红{t.r} 半{t.h} 青{t.g}</span>
            <span style={{ color: Object.keys(t.dis).length ? '#ffb4b4' : '#bdf3cf' }}>{Object.keys(t.dis).length ? '⚠ 病害' : '✓ 健康'}</span>
          </div>
        )}
      </div>
    </Panel>
  )

  const PlantGrid = (
    <Panel title="逐株记录" extra={count > 0 ? `${count}/${PLANT_COUNT} 株` : `0/${PLANT_COUNT} 株 · 待板端`} flex="0 0 auto">
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 9 }}>
        <button className="press" onClick={() => setAuto((a) => !a)} style={{
          fontSize: 11.5, fontWeight: 700, padding: '4px 11px', borderRadius: 980, cursor: 'pointer', fontFamily: 'inherit',
          background: auto ? C.skySoft : 'rgba(255,255,255,0.5)', color: auto ? C.skyDeep : C.ink2,
          border: `1px solid ${auto ? C.sky : C.hair}`, boxShadow: auto ? '0 0 10px rgba(47,155,214,0.20)' : 'none',
        }}>{auto ? '⏸ 巡览中' : '▶ 自动巡览'}</button>
        <span style={{ fontSize: 11, color: C.ink3 }}>点格子聚焦 · 数据由板端记录</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(8,1fr)', gap: 5 }}>
        {plants.map((p) => (
          <button key={p.id} className="glass-inset press" onClick={() => pick(p.id)} title={`第 ${p.id + 1} 株`}
            style={plantCell(p, current === p.id, focus === p.id)}>{p.id + 1}</button>
        ))}
      </div>
      <div style={{ marginTop: 10, fontSize: 11.5, color: C.ink3, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <span><i style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 3, background: C.accentSoft, border: '1px solid rgba(31,157,87,0.30)', marginRight: 4, verticalAlign: 'middle' }} />已记录</span>
        <span><i style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 3, background: C.dangerSoft, border: `1px solid ${C.dangerBorder}`, marginRight: 4, verticalAlign: 'middle' }} />有病害</span>
        <span><i style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 3, background: C.skySoft, border: `1px solid ${C.sky}`, marginRight: 4, verticalAlign: 'middle' }} />板端在拍</span>
      </div>
    </Panel>
  )

  const disList = Object.entries(t.dis)
  const DiseasePanel = (
    <Panel title="病害预警 · 抓拍" extra={disList.length ? `${disList.length} 类` : '正常'} flex="0 0 auto">
      {disList.length ? disList.map(([k, n]) => (
        <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 11px', marginBottom: 6, borderRadius: 11, background: C.dangerSoft, border: `1px solid ${C.dangerBorder}`, color: C.danger, fontWeight: 650, fontSize: 12.5 }}>
          ⚠ {DISEASE_CN[k] || k}<span className="tnum" style={{ marginLeft: 'auto' }}>{n} 株</span>
        </div>
      )) : <div style={{ display: 'flex', alignItems: 'center', gap: 7, padding: '9px 12px', borderRadius: 11, background: C.accentSoft, border: '1px solid rgba(31,157,87,0.25)', color: C.accentDeep, fontWeight: 650, fontSize: 12.5 }}>🌿 当前未发现病害</div>}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 6, marginTop: 9 }}>
        {caps.length ? caps.slice(0, 4).map((f) => (
          <img key={f} className="glass-inset" src={`/cap/${f}`} alt="cap" onClick={() => window.open(`/cap/${f}`)}
            style={{ width: '100%', aspectRatio: '1', objectFit: 'cover', borderRadius: 10, cursor: 'pointer' }} />
        )) : [0, 1, 2, 3].map((i) => (
          <div key={i} className="glass-inset" style={{ aspectRatio: '1', borderRadius: 10, opacity: 0.55, display: 'flex', alignItems: 'center', justifyContent: 'center', position: 'relative' }}>
            <div style={{ position: 'absolute', inset: 5, borderRadius: 8, border: '1px dashed rgba(120,150,134,0.34)' }} />
            <span style={{ fontSize: 16, opacity: 0.28 }}>🌱</span>
            {i === 0 && <span style={{ position: 'absolute', bottom: 4, fontSize: 9, color: C.ink4 }}>暂无抓拍</span>}
          </div>
        ))}
      </div>
    </Panel>
  )

  const Scene = (
    <Panel title="3D 数字孪生温室" extra="光照/湿度实时驱动 · 拖动漫游" flex="1 1 0" className="glass--float" style={{ minHeight: isNarrow ? 360 : 0 }}>
      <div className="canvas-bezel" style={{ position: 'relative', flex: 1, minHeight: isNarrow ? 320 : 0, background: 'linear-gradient(#cfeaff,#eaf6ee)' }}>
        <Canvas camera={{ position: [10.5, 7.2, 14.5], fov: 44 }} dpr={[1, 1.8]}>
          <fog attach="fog" args={['#dcebd9', 26, 60]} />
          <Sky sunPosition={[8, 6, 4]} turbidity={3} rayleigh={1.2} mieCoefficient={0.004} />
          <hemisphereLight args={['#eaf6ff', '#6a5a3a', 0.65 * (intensity / 1.5)]} />
          <ambientLight intensity={0.45 * (intensity / 1.5)} />
          <directionalLight position={[12, 18, 9]} intensity={intensity} />
          <Greenhouse />
          <Plants plants={plants} current={current} focus={focus} onSelect={pick} />
          <Diag />
          <ContactShadows position={[0, 0.02, 0]} opacity={0.3} scale={30} blur={2.4} far={5} />
          <OrbitControls target={[0, 1.2, 0]} maxPolarAngle={Math.PI / 2.1} minDistance={6} maxDistance={55} enablePan={false} />
          <EffectComposer><Bloom intensity={0.35} luminanceThreshold={0.9} mipmapBlur /></EffectComposer>
        </Canvas>
        <div style={{ position: 'absolute', bottom: 10, left: 11, zIndex: 3, fontSize: 11.5, fontWeight: 600, color: C.accentDeep, background: 'rgba(255,255,255,.70)', backdropFilter: 'blur(14px)', WebkitBackdropFilter: 'blur(14px)', padding: '3px 11px', borderRadius: 980, border: `1px solid ${C.hair}` }}>
          🎥 板端记录 {count}/{PLANT_COUNT}{current >= 0 ? ` · 当前第 ${current + 1} 株` : ''}{focus >= 0 ? ` · 查看第 ${focus + 1} 株` : ''}
        </div>
      </div>
    </Panel>
  )

  return (
    <div style={{ position: 'fixed', inset: 0, display: 'flex', flexDirection: 'column', overflowY: 'auto', overflowX: 'hidden', color: C.ink }}>
      <header className="glass glass--chrome" style={{ display: 'flex', alignItems: 'center', gap: 13, padding: '0 18px', height: 56, margin: '11px 11px 9px', borderRadius: 18, flexShrink: 0, position: 'sticky', top: 11, zIndex: 20 }}>
        <span style={{ width: 30, height: 30, borderRadius: 9, background: C.accentSoft, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 17 }}>🍅</span>
        <div style={{ fontSize: 18, fontWeight: 700, color: C.ink, letterSpacing: .4 }}>作物AI智慧温室 · 数字孪生监测大屏</div>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: C.accentDeep, background: C.accentSoft, border: '1px solid rgba(31,157,87,0.30)', padding: '3px 11px', borderRadius: 980, fontWeight: 700 }}>
          <i className="dot-pulse" style={{ width: 6, height: 6, borderRadius: 980, background: C.accent, boxShadow: '0 0 8px rgba(31,157,87,0.28)' }} />在线
        </span>
        <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 12 }}>
          <i style={{ width: 1, height: 18, background: C.hair }} />
          <span className="tnum" style={{ fontSize: 13, color: C.ink2, fontFamily: 'ui-monospace, SFMono-Regular, monospace' }}>{s.time}</span>
        </span>
      </header>

      <div style={{ flex: 1, display: 'flex', flexDirection: isNarrow ? 'column' : 'row', gap: 12, padding: '0 11px', minHeight: 0 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, width: isNarrow ? 'auto' : 332, flexShrink: 0 }}>
          <Panel title="环境监测" extra={s.time?.split(' ')[1] || ''}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 7 }}>
              <Kpi icon="🌡️" label="温度" value={s.temp} unit="°C" sim={s.sim_scd} accent={C.temp} soft={C.tempSoft} />
              <Kpi icon="💧" label="湿度" value={s.rh} unit="%" sim={s.sim_scd} accent={C.humid} soft={C.humidSoft} />
              <Kpi icon="🫁" label="CO₂" value={s.co2} unit="ppm" sim={s.sim_scd} accent={C.co2} soft={C.co2Soft} />
              <Kpi icon="☀️" label="光照" value={luxK(s.lux)} unit={s.lux >= 1000 ? 'klux' : 'lux'} sim={s.sim_veml} accent={C.light} soft={C.lightSoft} />
              <Kpi icon="🌱" label="土壤湿度" value={s.soil ?? null} unit="%" sim={s.sim_soil} accent={C.soil} soft={C.soilSoft} />
              <Kpi icon="🍅" label="估产" value={yieldOffline ? null : (t.est / 1000).toFixed(2)} unit="kg" accent={C.accentDeep} soft={C.accentSoft} />
            </div>
          </Panel>
          <Panel title="温度趋势" flex="0 0 auto"><Trend pts={tHist.current} color={C.temp} label="温度" unit="°C" /></Panel>
        <Panel title="检测历史" extra={history.length ? `${history.length} 条` : ''} flex="0 0 auto">
          {!history.length ? (
            <div style={{ fontSize: 12, color: C.ink3, padding: '8px 4px' }}>历史数据收集中…</div>
          ) : (
            <>
              <div style={{ marginBottom: 7 }}>
                <Trend
                  pts={history.slice(-50).map((r) => +r.fruit_total || 0)}
                  color={C.danger} label="果实总数" unit="个" />
              </div>
              <Trend
                pts={history.slice(-50).map((r) => +r.disease_total || 0)}
                color={C.danger} label="病害数" unit="个" />
            </>
          )}
        </Panel>
          <Panel title="产量估算" flex="1 1 0">
            <YieldBar label="青果" value={t.g} total={t.total} color={C.sky} offline={yieldOffline} />
            <YieldBar label="半熟" value={t.h} total={t.total} color={C.light} offline={yieldOffline} />
            <YieldBar label="红果(可采收)" value={t.r} total={t.total} color={C.danger} offline={yieldOffline} />
            <div style={{ marginTop: 'auto', paddingTop: 9, borderTop: `1px solid ${C.hair}`, display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', fontSize: 13 }}>
              <span style={{ color: C.ink2 }}>预计总产</span><b className="tnum" style={{ color: yieldOffline ? C.ink4 : C.accentDeep, fontSize: 15 }}>{yieldOffline ? '— kg' : fmtKg(t.est)}</b>
            </div>
            {yieldOffline ? (
              <div style={{ fontSize: 11, color: C.ink3, marginTop: 4 }}>待板端逐株记录</div>
            ) : (latest && latest.f7d_g !== undefined && latest.f7d_g !== '' && (
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, marginTop: 4 }}>
                <span style={{ color: C.ink2 }}>未来7天可采</span><b className="tnum" style={{ color: C.sky }}>{fmtKg(+latest.f7d_g)}</b>
              </div>
            ))}
          </Panel>
        </div>

        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, minHeight: isNarrow ? 380 : 470 }}>{Scene}</div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, width: isNarrow ? 'auto' : 358, flexShrink: 0 }}>
          {LiveCam}{PlantGrid}{DiseasePanel}
        </div>
      </div>
    </div>
  )
}
