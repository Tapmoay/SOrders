import { http } from './client'

export interface PriceRule {
  id: number
  shipper_id: number
  product_id: number
  special_unit_price: string | number
  shipper_name?: string | null
  product_name?: string | null
}

export async function fetchPriceRules(shipperId?: number) {
  const { data } = await http.get<PriceRule[]>('/price-rules', {
    params: shipperId != null ? { shipper_id: shipperId } : {},
  })
  return data
}

export async function createPriceRule(body: {
  shipper_id: number
  product_id: number
  special_unit_price: number | string
}) {
  const { data } = await http.post<PriceRule>('/price-rules', body)
  return data
}

export async function updatePriceRule(
  id: number,
  payload: { special_unit_price?: number | string; shipper_id?: number },
) {
  const { data } = await http.patch<PriceRule>(`/price-rules/${id}`, payload)
  return data
}

export async function deletePriceRule(id: number) {
  await http.delete(`/price-rules/${id}`)
}
