import { http } from './client'

export interface ShipperAddress {
  id: number
  shipper_id: number
  receiver_name: string
  phone: string
  detail_address: string
  remark: string
  is_default: boolean
  address_lat: string | number | null
  address_lng: string | number | null
  created_at: string
}

export interface AddressPayload {
  receiver_name?: string
  phone?: string
  detail_address?: string
  remark?: string
  is_default?: boolean
  address_lat?: string | number | null
  address_lng?: string | number | null
}

export async function fetchAddresses() {
  const { data } = await http.get<ShipperAddress[]>('/shipper/addresses')
  return data
}

export async function createAddress(body: AddressPayload) {
  const { data } = await http.post<ShipperAddress>('/shipper/addresses', body)
  return data
}

export async function updateAddress(id: number, body: AddressPayload) {
  const { data } = await http.patch<ShipperAddress>(`/shipper/addresses/${id}`, body)
  return data
}

export async function deleteAddress(id: number) {
  await http.delete(`/shipper/addresses/${id}`)
}

export async function setDefaultAddress(id: number) {
  const { data } = await http.post<ShipperAddress>(`/shipper/addresses/${id}/set-default`)
  return data
}

export async function upsertContact(phone: string, display_name = '') {
  const { data } = await http.post<{ id: number }>('/shipper/contacts', { phone, display_name })
  return data
}
