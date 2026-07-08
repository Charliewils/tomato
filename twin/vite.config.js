import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 板子接通后: 取消下面 proxy 注释填入板子IP, 并把 src/data.js 的 USE_MOCK 改为 false
export default defineConfig({
  base: '/twin/', // 部署在 crop_web 的 /twin/ 子路径
  plugins: [react()],
})
