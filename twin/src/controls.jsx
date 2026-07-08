import { useEffect, useRef } from 'react'
import { useThree, useFrame } from '@react-three/fiber'
import * as THREE from 'three'

const keys = {}

export function Movement({ enabled, speed = 3.5, eye = 1.6 }) {
  const { camera } = useThree()
  const fwd = useRef(new THREE.Vector3())
  const right = useRef(new THREE.Vector3())
  const move = useRef(new THREE.Vector3())

  useEffect(() => {
    camera.position.y = eye
    const down = (e) => (keys[e.code] = true)
    const up = (e) => (keys[e.code] = false)
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
    }
  }, [camera, eye])

  useFrame((_, dt) => {
    if (!enabled) return
    camera.getWorldDirection(fwd.current)
    fwd.current.y = 0
    fwd.current.normalize()
    right.current.crossVectors(fwd.current, camera.up).normalize()
    move.current.set(0, 0, 0)
    if (keys.KeyW || keys.ArrowUp) move.current.add(fwd.current)
    if (keys.KeyS || keys.ArrowDown) move.current.sub(fwd.current)
    if (keys.KeyD || keys.ArrowRight) move.current.add(right.current)
    if (keys.KeyA || keys.ArrowLeft) move.current.sub(right.current)
    if (move.current.lengthSq() > 0) {
      move.current.normalize().multiplyScalar(speed * Math.min(dt, 0.05))
      camera.position.x += move.current.x
      camera.position.z += move.current.z
    }
    camera.position.y = eye
    camera.position.x = THREE.MathUtils.clamp(camera.position.x, -7.4, 7.4)
    camera.position.z = THREE.MathUtils.clamp(camera.position.z, -4.6, 4.6)
  })

  return null
}
