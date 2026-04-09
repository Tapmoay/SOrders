import { http } from './client'
import { cacheGet, cacheRemove, cacheSet } from '@/utils/localCache'

export interface Product {
  id: number
  name: string
  /** 展示用，如 #323233 */
  name_color?: string | null
  default_unit_price: string | number
  is_active: boolean
  image_url?: string | null
}

const PRODUCTS_KEY = 'products_active'
const PRODUCTS_TTL_MS = 5 * 60 * 1000

export async function fetchProducts(forceRefresh = false) {
  if (!forceRefresh) {
    const hit = cacheGet<Product[]>(PRODUCTS_KEY)
    if (hit?.length) return hit
  }
  const { data } = await http.get<Product[]>('/products')
  cacheSet(PRODUCTS_KEY, data, PRODUCTS_TTL_MS)
  return data
}

/** 下单选品：含已下架（下架项仅展示，不可选） */
export async function fetchProductsCatalog() {
  const { data } = await http.get<Product[]>('/products', { params: { include_inactive: true } })
  return data
}

/** 派单员价格管理：含已下架商品 */
export async function fetchProductsAll() {
  const { data } = await http.get<Product[]>('/products', { params: { include_inactive: true } })
  return data
}

export function invalidateProductsCache() {
  cacheRemove(PRODUCTS_KEY)
}

export async function createProduct(body: {
  name: string
  default_unit_price: number | string
  image_url?: string | null
  name_color?: string | null
}) {
  const payload: Record<string, unknown> = {
    name: body.name,
    default_unit_price: body.default_unit_price,
  }
  if (body.image_url != null) payload.image_url = body.image_url
  if (body.name_color != null && body.name_color !== '') payload.name_color = body.name_color
  const { data } = await http.post<Product>('/products', payload)
  invalidateProductsCache()
  return data
}

/** 价格管理编辑：固定带上 name_color（可为 null 以清除），配合后端 model_fields_set 写入 */
export async function updateProduct(
  id: number,
  body: {
    name: string
    default_unit_price: number | string
    is_active: boolean
    name_color: string | null
  },
) {
  const { data } = await http.patch<Product>(`/products/${id}`, body)
  invalidateProductsCache()
  return data
}

export async function uploadProductImage(productId: number, file: File) {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post<Product>(`/products/${productId}/image`, form)
  invalidateProductsCache()
  return data
}

/** 永久删除商品（非「下架」；下架请 PATCH is_active=false） */
export async function deleteProduct(id: number) {
  await http.delete(`/products/${id}`)
  invalidateProductsCache()
}
