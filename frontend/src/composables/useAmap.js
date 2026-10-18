// 动态加载高德 JS API（key/securityCode 由后端 /api/config 下发，不硬编码）
// plugin 显式加载 PlaceSearch（地理编码）与 Driving（驾车路线）

let loadingPromise = null

export function loadAmap(key, securityCode) {
  if (window.AMap) return Promise.resolve(window.AMap)
  if (loadingPromise) return loadingPromise
  // 安全密钥必须在加载 JS API 之前设置（键名是 securityJsCode）
  if (securityCode) window._AMapSecurityConfig = { securityJsCode: securityCode }

  loadingPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${key}&plugin=AMap.PlaceSearch,AMap.Driving`
    script.onload = () => resolve(window.AMap)
    script.onerror = () => reject(new Error('高德 JS API 加载失败'))
    document.head.appendChild(script)
  })
  return loadingPromise
}

// 景点名 → 坐标（PlaceSearch 地理编码），返回 { name: [lng, lat] }
export function geocodeSpots(AMap, names, city) {
  const place = new AMap.PlaceSearch({ city: city || '全国', pageSize: 1 })
  const result = {}
  const uniq = [...new Set((names || []).filter(Boolean))]
  return Promise.all(
    uniq.map(
      (name) =>
        new Promise((resolve) => {
          place.search(name, (st, res) => {
            const poi = res?.poiList?.pois?.[0]
            if (poi) result[name] = [poi.location.lng, poi.location.lat]
            resolve()
          })
        }),
    ),
  ).then(() => result)
}
