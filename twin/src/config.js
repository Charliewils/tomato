// 拿到真实番茄株 .glb 后: 放到 public/models/tomato.glb, 把 MODEL_ENABLED 改 true,
// 再按模型实际大小/朝向调 MODEL_SCALE / MODEL_ROT / MODEL_Y
export const MODEL_ENABLED = true
export const MODEL_URL = import.meta.env.BASE_URL + 'models/tomato.glb'
export const GREENHOUSE_URL = import.meta.env.BASE_URL + 'models/greenhouse.glb'
export const PLANT_TARGET_H = 1.5 // 模型自动归一化到这个高度(米), 与程序化株一致

// 两条土壤床(模型 earth2): 对 earth2 网格顶点做 PCA(在 Greenhouse TARGET_SPAN=17 归一化下)实测——
// 两床是平行细长条, 长轴与世界轴成 46.9°, 故植株须沿 BED_DIR 排列而非沿 z 轴(否则与床成夹角).
// cx,cz=床几何中心(投影极值法, 与顶点分布无关); halfLen=半长.
export const BED_DIR = [0.683, 0.730]     // 床长轴单位向量(≈46.9°), 两床同向
export const BEDS = [
  { cx: -2.44, cz: 2.33 },
  { cx: 2.5, cz: -2.28 },
]
export const BED_HALF_LEN = 6.61          // 床半长(沿 BED_DIR)
export const BED_TOP_Y = 0.82             // 床面高度(植株根部落点, = earth2 ymax)
export const PER_BED = 4
export const PLANT_COUNT = BEDS.length * PER_BED    // 8

export const DISEASES = [
  'early_blight', 'late_blight', 'bacterial_spot', 'leaf_mold', 'septoria',
  'spider_mites', 'mosaic_virus', 'yellow_leaf_curl_virus', 'leaf_miner',
]

export const DISEASE_CN = {
  bacterial_spot: '细菌性斑点', early_blight: '早疫病', late_blight: '晚疫病',
  leaf_mold: '叶霉病', leaf_miner: '潜叶蝇', mosaic_virus: '花叶病毒',
  septoria: '斑枯病', spider_mites: '红蜘蛛', yellow_leaf_curl_virus: '黄化曲叶病毒',
}
