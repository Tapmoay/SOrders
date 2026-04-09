<script setup lang="ts">
import { useVirtualizer } from '@tanstack/vue-virtual'
import { computed, ref } from 'vue'

const props = withDefaults(
  defineProps<{
    items: unknown[]
    estimateSize?: number
    overscan?: number
  }>(),
  {
    estimateSize: 200,
    overscan: 6,
  },
)

const parentRef = ref<HTMLElement | null>(null)

const virtualizer = useVirtualizer(
  computed(() => ({
    count: props.items.length,
    getScrollElement: () => parentRef.value,
    estimateSize: () => props.estimateSize,
    overscan: props.overscan,
  })),
)
</script>

<template>
  <div ref="parentRef" class="vs-root">
    <div
      class="vs-inner"
      :style="{
        height: `${virtualizer.getTotalSize()}px`,
        position: 'relative',
        width: '100%',
      }"
    >
      <div
        v-for="v in virtualizer.getVirtualItems()"
        :key="v.index"
        class="vs-row"
        :style="{
          position: 'absolute',
          top: 0,
          left: 0,
          width: '100%',
          transform: `translateY(${v.start}px)`,
        }"
      >
        <slot :item="props.items[v.index]" :index="v.index" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.vs-root {
  position: relative;
  width: 100%;
  max-height: calc(100vh - 140px);
  min-height: 200px;
  overflow: auto;
  -webkit-overflow-scrolling: touch;
}
</style>
