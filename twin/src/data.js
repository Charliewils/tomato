import { useEffect, useState } from 'react'
import { PLANT_COUNT } from './config'

// 板子接通后改 false: useLiveData 走 /api/sensors(板端 sensors.py)
const USE_MOCK = false       // 传感器: 走板端 /api/sensors (光照实测)

function mockSensors() {
  const t = Date.now() / 1000
  return {
    time: new Date().toLocaleString('zh-CN'),
    temp: +(24 + 4 * Math.sin(t / 60)).toFixed(1),
    rh: Math.round(65 + 10 * Math.sin(t / 50 + 1)),
    co2: Math.round(600 + 150 * Math.sin(t / 90)),
    lux: Math.max(0, Math.round(900 + 700 * Math.sin(t / 120))),
    soil: +(50 + 30 * Math.sin(t / 110)).toFixed(1),
    sim_scd: true,
    sim_veml: true,
    sim_soil: true,
  }
}

// 板端 /api/sensors 返回 {ts,lux,co2,temp,rh,sim_scd,sim_veml}
export function useLiveData(intervalMs = 2000) {
  const [data, setData] = useState(mockSensors)
  useEffect(() => {
    const tick = async () => {
      if (USE_MOCK) return setData(mockSensors())
      try {
        const r = await fetch('/api/sensors')
        const d = await r.json()
        if (d && typeof d.temp === 'number') {
          setData({
            time: new Date((d.ts || Date.now() / 1000) * 1000).toLocaleString('zh-CN'),
            temp: d.temp, rh: d.rh, co2: d.co2, lux: d.lux,
            soil: typeof d.soil === 'number' ? d.soil : null,
            sim_scd: !!d.sim_scd, sim_veml: !!d.sim_veml, sim_soil: !!d.sim_soil,
          })
          return
        }
        setData(mockSensors())          // 板端无效数据: 回退动态模拟(已标 模拟)
      } catch { setData(mockSensors()) } // 板端离线: 同上, 保证趋势/读数仍有生命力
    }
    tick()
    const id = setInterval(tick, intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
  return data
}

const emptyPlants = (count) =>
  Array.from({ length: count }, (_, id) => ({ id, green: 0, half: 0, ripe: 0, disease: null, est: 0, scanned: false }))
const emptySummary = { green: 0, half: 0, ripe: 0, est: 0 }

// 镜像板端逐株记录: 轮询 /api/plants (板端 main_camera_live 手动记录后写 plants.json)
// 返回 {plants:16株真实记录, current:板端正在拍的株, count, summary}
export function usePlants(intervalMs = 2000) {
  const [data, setData] = useState(() => ({ plants: emptyPlants(PLANT_COUNT), current: -1, count: 0, summary: emptySummary }))
  useEffect(() => {
    const tick = async () => {
      try {
        const d = await (await fetch('/api/plants')).json()
        if (!d || !Array.isArray(d.plants)) return
        const plants = emptyPlants(PLANT_COUNT).map((p, i) => {
          const s = d.plants.find((x) => x.id === i)
          return s ? { id: i, green: +s.green || 0, half: +s.half || 0, ripe: +s.ripe || 0, disease: s.disease || null, est: +s.est || 0, scanned: !!s.scanned } : p
        })
        setData({ plants, current: typeof d.current === 'number' ? d.current : -1, count: d.count || 0, summary: d.summary || emptySummary })
      } catch {}
    }
    tick()
    const id = setInterval(tick, intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
  return data
}

// 历史检测数据: 轮询 /api/history (crop_log.csv 最近300行)
export function useHistory(intervalMs = 15000) {
  const [rows, setRows] = useState([])
  useEffect(() => {
    const tick = async () => {
      try {
        const d = await (await fetch('/api/history')).json()
        if (Array.isArray(d)) setRows(d)
      } catch {}
    }
    tick()
    const id = setInterval(tick, intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
  return rows
}
