<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { showConfirmDialog, showFailToast, showSuccessToast } from 'vant'

import {
  createAddress,
  deleteAddress,
  fetchAddresses,
  setDefaultAddress,
  updateAddress,
  type ShipperAddress,
} from '@/api/addresses'

const list = ref<ShipperAddress[]>([])
const showPopup = ref(false)
const editing = ref<ShipperAddress | null>(null)

const form = ref({
  receiver_name: '',
  phone: '',
  detail_address: '',
  remark: '',
  is_default: false,
})

async function load() {
  try {
    list.value = await fetchAddresses()
  } catch {
    showFailToast('加载失败')
  }
}

onMounted(load)

function openAdd() {
  editing.value = null
  form.value = { receiver_name: '', phone: '', detail_address: '', remark: '', is_default: false }
  showPopup.value = true
}

function openEdit(a: ShipperAddress) {
  editing.value = a
  form.value = {
    receiver_name: a.receiver_name,
    phone: a.phone,
    detail_address: a.detail_address,
    remark: a.remark,
    is_default: a.is_default,
  }
  showPopup.value = true
}

async function save() {
  if (!form.value.detail_address.trim()) {
    showFailToast('请填写详细地址')
    return
  }
  try {
    if (editing.value) {
      await updateAddress(editing.value.id, {
        receiver_name: form.value.receiver_name,
        phone: form.value.phone,
        detail_address: form.value.detail_address,
        remark: form.value.remark,
        is_default: form.value.is_default,
      })
    } else {
      await createAddress({
        receiver_name: form.value.receiver_name,
        phone: form.value.phone,
        detail_address: form.value.detail_address,
        remark: form.value.remark,
        is_default: form.value.is_default,
      })
    }
    showSuccessToast('已保存')
    showPopup.value = false
    await load()
  } catch (e) {
    const err = e as { response?: { data?: { detail?: string } } }
    showFailToast(err.response?.data?.detail || '保存失败')
  }
}

async function remove(a: ShipperAddress) {
  try {
    await showConfirmDialog({ title: '删除地址', message: '确定删除该地址？' })
    await deleteAddress(a.id)
    showSuccessToast('已删除')
    await load()
  } catch (e) {
    if (e !== 'cancel') showFailToast('删除失败')
  }
}

async function makeDefault(a: ShipperAddress) {
  try {
    await setDefaultAddress(a.id)
    showSuccessToast('已设为默认')
    await load()
  } catch {
    showFailToast('操作失败')
  }
}
</script>

<template>
  <div class="addr-page">
    <van-empty v-if="!list.length" description="暂无地址" />

    <van-cell-group v-for="a in list" :key="a.id" inset class="mb">
      <van-cell :title="a.receiver_name || '收货人'" :label="a.detail_address">
        <template #value>
          <van-tag v-if="a.is_default" type="success" plain>默认</van-tag>
        </template>
      </van-cell>
      <van-cell title="电话" :value="a.phone || '—'" />
      <van-cell title="备注" :value="a.remark || '—'" />
      <van-cell title="操作">
        <template #value>
          <van-button size="mini" type="primary" plain @click="openEdit(a)">编辑</van-button>
          <van-button v-if="!a.is_default" size="mini" plain @click="makeDefault(a)">默认</van-button>
          <van-button size="mini" type="danger" plain @click="remove(a)">删除</van-button>
        </template>
      </van-cell>
    </van-cell-group>

    <div class="fab">
      <van-button type="primary" round block icon="plus" @click="openAdd">新增地址</van-button>
    </div>

    <van-popup v-model:show="showPopup" position="bottom" round :style="{ padding: '12px 0 max(16px, env(safe-area-inset-bottom))' }">
      <div class="pop-title">{{ editing ? '编辑地址' : '新增地址' }}</div>
      <van-field v-model="form.receiver_name" label="收货人" />
      <van-field v-model="form.phone" label="电话" type="tel" />
      <van-field v-model="form.detail_address" label="地址" type="textarea" rows="3" />
      <van-field v-model="form.remark" label="备注" />
      <van-cell title="默认地址">
        <template #right-icon>
          <van-switch v-model="form.is_default" size="20" />
        </template>
      </van-cell>
      <div class="pop-actions">
        <van-button block round type="primary" @click="save">保存</van-button>
        <van-button block round plain class="mt8" @click="showPopup = false">取消</van-button>
      </div>
    </van-popup>
  </div>
</template>

<style scoped>
.addr-page {
  padding-bottom: 88px;
}
.mb {
  margin-bottom: 10px;
}
.fab {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 12px 16px max(12px, env(safe-area-inset-bottom));
  background: linear-gradient(transparent, var(--van-background));
}
.pop-title {
  text-align: center;
  font-weight: 600;
  padding: 8px 0 12px;
}
.pop-actions {
  padding: 12px 16px 0;
}
.mt8 {
  margin-top: 8px;
}
</style>
