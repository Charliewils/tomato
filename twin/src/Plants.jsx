import { useMemo } from 'react'
import Plant from './Plant'
import { BEDS, BED_DIR, BED_HALF_LEN, PER_BED, BED_TOP_Y } from './config'

const MARGIN = 1.55          // 床两端留边, 植株不顶到床头
const ROW_JITTER = 0.18      // 沿床宽方向(垂直长轴)的轻微错位, 看起来自然

export default function Plants({ plants, current, focus, onSelect }) {
  const layout = useMemo(() => {
    const [dx, dz] = BED_DIR
    const px = -dz, pz = dx            // 垂直长轴方向(床宽方向)
    const usable = BED_HALF_LEN - MARGIN
    const yawDeg = Math.atan2(dx, dz)  // 让植株朝向沿床一致(对程序化株无影响, 对 GLTF 有)
    const arr = []
    let id = 0
    for (const bed of BEDS) {
      for (let i = 0; i < PER_BED; i++) {
        const f = PER_BED === 1 ? 0 : i / (PER_BED - 1) - 0.5   // -0.5..0.5
        const t = f * 2 * usable
        const j = (Math.random() - 0.5) * ROW_JITTER
        arr.push({
          id: id++,
          x: bed.cx + dx * t + px * j,
          z: bed.cz + dz * t + pz * j,
          yaw: yawDeg,
          scale: 1.12 + Math.random() * 0.2,
        })
      }
    }
    return arr
  }, [])

  return (
    <group>
      {layout.map((p) => (
        <Plant
          key={p.id}
          id={p.id}
          seed={p.id + 1}
          position={[p.x, BED_TOP_Y, p.z]}
          rotation={[0, p.yaw, 0]}
          scale={p.scale}
          state={plants[p.id]}
          current={current === p.id}
          focus={focus === p.id}
          onSelect={onSelect}
        />
      ))}
    </group>
  )
}
