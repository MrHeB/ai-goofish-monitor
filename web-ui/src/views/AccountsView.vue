<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { listAccounts, getAccount, createAccount, updateAccount, deleteAccount, createQrSession, getQrSessionStatus, type AccountItem } from '@/api/accounts'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { toast } from '@/components/ui/toast'
const { t } = useI18n()

const accounts = ref<AccountItem[]>([])
const isLoading = ref(false)
const isSaving = ref(false)
const router = useRouter()

const isCreateDialogOpen = ref(false)
const isEditDialogOpen = ref(false)
const isDeleteDialogOpen = ref(false)
const isQrDialogOpen = ref(false)

const newName = ref('')
const newContent = ref('')
const editName = ref('')
const editContent = ref('')
const deleteName = ref('')

const qrName = ref('')
const qrImage = ref('')
const qrStatus = ref('') // generating / waiting / scanned / success / expired / cancelled / verification_required
const qrError = ref('')
const qrSessionId = ref('')
const isQrPolling = ref(false)
let qrPollTimer: ReturnType<typeof setInterval> | null = null

function stopQrPolling() {
  if (qrPollTimer) {
    clearInterval(qrPollTimer)
    qrPollTimer = null
  }
  isQrPolling.value = false
}

function openQrDialog(name?: string) {
  qrName.value = name || ''
  qrImage.value = ''
  qrStatus.value = ''
  qrError.value = ''
  qrSessionId.value = ''
  stopQrPolling()
  isQrDialogOpen.value = true
}

async function startQrLogin() {
  if (!qrName.value.trim()) {
    toast({ title: t('accounts.toasts.incomplete'), description: t('accounts.toasts.nameRequired'), variant: 'destructive' })
    return
  }
  qrError.value = ''
  qrImage.value = ''
  qrStatus.value = 'generating'
  try {
    const res = await createQrSession(qrName.value.trim())
    if (!res.success) {
      qrStatus.value = ''
      qrError.value = res.message || t('accounts.qr.createFailed')
      return
    }
    qrSessionId.value = res.session_id
    qrImage.value = res.qr_code_url
    qrStatus.value = 'waiting'
    isQrPolling.value = true
    qrPollTimer = setInterval(pollQrStatus, 1000)
  } catch (e) {
    qrStatus.value = ''
    qrError.value = (e as Error).message
  }
}

async function pollQrStatus() {
  if (!qrSessionId.value) return
  let st
  try {
    st = await getQrSessionStatus(qrSessionId.value)
  } catch (e) {
    return // 轮询请求失败则稍后重试，不打断扫码
  }
  const status = st.status
  if (status === 'success') {
    stopQrPolling()
    qrStatus.value = 'success'
    toast({ title: t('accounts.toasts.authorized'), description: st.message })
    setTimeout(() => {
      isQrDialogOpen.value = false
      fetchAccounts()
    }, 1200)
  } else if (status === 'expired' || status === 'cancelled') {
    stopQrPolling()
    qrStatus.value = status
    qrError.value = st.message || (status === 'expired' ? t('accounts.qr.expired') : t('accounts.qr.cancelled'))
  } else if (status === 'verification_required') {
    stopQrPolling()
    qrStatus.value = status
    qrError.value = st.message || t('accounts.qr.verificationRequired')
  } else if (status === 'scanned' || status === 'waiting') {
    qrStatus.value = status
  } else if (status === 'not_found') {
    stopQrPolling()
    qrStatus.value = ''
    qrError.value = t('accounts.qr.sessionLost')
  }
}

async function fetchAccounts() {
  isLoading.value = true
  try {
    accounts.value = await listAccounts()
  } catch (e) {
    toast({ title: t('accounts.toasts.loadFailed'), description: (e as Error).message, variant: 'destructive' })
  } finally {
    isLoading.value = false
  }
}

function openCreateDialog() {
  newName.value = ''
  newContent.value = ''
  isCreateDialogOpen.value = true
}

async function openEditDialog(name: string) {
  isSaving.value = true
  try {
    const detail = await getAccount(name)
    editName.value = detail.name
    editContent.value = detail.content
    isEditDialogOpen.value = true
  } catch (e) {
    toast({ title: t('accounts.toasts.loadContentFailed'), description: (e as Error).message, variant: 'destructive' })
  } finally {
    isSaving.value = false
  }
}

function openDeleteDialog(name: string) {
  deleteName.value = name
  isDeleteDialogOpen.value = true
}

function goCreateTask(name: string) {
  router.push({ path: '/tasks', query: { account: name, create: '1' } })
}

async function handleCreateAccount() {
  if (!newName.value.trim() || !newContent.value.trim()) {
    toast({ title: t('accounts.toasts.incomplete'), description: t('accounts.toasts.createDescriptionRequired'), variant: 'destructive' })
    return
  }
  isSaving.value = true
  try {
    await createAccount({ name: newName.value.trim(), content: newContent.value.trim() })
    toast({ title: t('accounts.toasts.created') })
    isCreateDialogOpen.value = false
    await fetchAccounts()
  } catch (e) {
    toast({ title: t('accounts.toasts.createFailed'), description: (e as Error).message, variant: 'destructive' })
  } finally {
    isSaving.value = false
  }
}

async function handleUpdateAccount() {
  if (!editContent.value.trim()) {
    toast({ title: t('accounts.toasts.contentRequired'), description: t('accounts.toasts.updateDescriptionRequired'), variant: 'destructive' })
    return
  }
  isSaving.value = true
  try {
    await updateAccount(editName.value, editContent.value.trim())
    toast({ title: t('accounts.toasts.updated') })
    isEditDialogOpen.value = false
    await fetchAccounts()
  } catch (e) {
    toast({ title: t('accounts.toasts.updateFailed'), description: (e as Error).message, variant: 'destructive' })
  } finally {
    isSaving.value = false
  }
}

async function handleDeleteAccount() {
  isSaving.value = true
  try {
    await deleteAccount(deleteName.value)
    toast({ title: t('accounts.toasts.deleted') })
    isDeleteDialogOpen.value = false
    await fetchAccounts()
  } catch (e) {
    toast({ title: t('accounts.toasts.deleteFailed'), description: (e as Error).message, variant: 'destructive' })
  } finally {
    isSaving.value = false
  }
}

onMounted(fetchAccounts)
</script>

<template>
  <div>
    <div class="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h1 class="text-2xl font-bold text-gray-800">{{ t('accounts.title') }}</h1>
        <p class="text-sm text-gray-500 mt-1">{{ t('accounts.description') }}</p>
      </div>
      <div class="flex gap-2">
        <Button variant="outline" class="w-full sm:w-auto" @click="openCreateDialog">{{ t('accounts.addManual') }}</Button>
        <Button class="w-full sm:w-auto" @click="openQrDialog()">{{ t('accounts.add') }}</Button>
      </div>
    </div>

    <Card class="app-surface mb-6 border-none">
      <CardHeader>
        <CardTitle>{{ t('accounts.cookieGuide.title') }}</CardTitle>
      </CardHeader>
      <CardContent class="text-sm text-gray-600">
        <ol class="list-decimal list-inside space-y-1">
          <li>{{ t('accounts.cookieGuide.step1') }}</li>
          <li>{{ t('accounts.cookieGuide.step2') }}</li>
          <li>{{ t('accounts.cookieGuide.step3') }}</li>
        </ol>
        <p class="mt-4 text-xs text-gray-400">{{ t('accounts.cookieGuide.fallbackHint') }}</p>
      </CardContent>
    </Card>

    <Card class="app-surface border-none">
      <CardHeader>
        <CardTitle>{{ t('accounts.list.title') }}</CardTitle>
        <CardDescription>{{ t('accounts.list.description') }}</CardDescription>
      </CardHeader>
      <CardContent>
        <div class="space-y-4 md:hidden">
          <div v-if="isLoading" class="py-10 text-center text-sm text-muted-foreground">{{ t('common.loading') }}</div>
          <div v-else-if="accounts.length === 0" class="py-10 text-center text-sm text-muted-foreground">{{ t('accounts.list.empty') }}</div>
          <article
            v-else
            v-for="account in accounts"
            :key="account.name"
            class="app-surface-subtle p-4"
          >
            <div class="space-y-2">
              <div class="flex items-center justify-between gap-3">
                <h3 class="truncate text-base font-semibold text-slate-900">{{ account.name }}</h3>
                <Button size="sm" variant="outline" @click="goCreateTask(account.name)">{{ t('accounts.list.createTask') }}</Button>
              </div>
              <p class="break-all text-sm text-slate-500">{{ account.path }}</p>
            </div>
            <div class="mt-4 flex flex-wrap gap-2">
              <Button size="sm" variant="outline" class="flex-1 min-w-[120px]" @click="openQrDialog(account.name)">{{ t('accounts.list.reauthorize') }}</Button>
              <Button size="sm" variant="outline" class="flex-1 min-w-[120px]" @click="openEditDialog(account.name)">{{ t('accounts.list.update') }}</Button>
              <Button size="sm" variant="destructive" class="flex-1 min-w-[120px]" @click="openDeleteDialog(account.name)">{{ t('accounts.list.delete') }}</Button>
            </div>
          </article>
        </div>

        <div class="hidden md:block">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{{ t('accounts.list.name') }}</TableHead>
                <TableHead>{{ t('accounts.list.file') }}</TableHead>
                <TableHead class="text-right">{{ t('accounts.list.actions') }}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-if="isLoading">
                <TableCell colspan="3" class="h-20 text-center text-muted-foreground">{{ t('common.loading') }}</TableCell>
              </TableRow>
              <TableRow v-else-if="accounts.length === 0">
                <TableCell colspan="3" class="h-20 text-center text-muted-foreground">{{ t('accounts.list.empty') }}</TableCell>
              </TableRow>
              <TableRow v-else v-for="account in accounts" :key="account.name">
                <TableCell class="font-medium">{{ account.name }}</TableCell>
                <TableCell class="text-sm text-gray-500">{{ account.path }}</TableCell>
                <TableCell class="text-right">
                  <div class="flex justify-end gap-2">
                    <Button size="sm" variant="outline" @click="goCreateTask(account.name)">{{ t('accounts.list.createTask') }}</Button>
                    <Button size="sm" variant="outline" @click="openQrDialog(account.name)">{{ t('accounts.list.reauthorize') }}</Button>
                    <Button size="sm" variant="outline" @click="openEditDialog(account.name)">{{ t('accounts.list.update') }}</Button>
                    <Button size="sm" variant="destructive" @click="openDeleteDialog(account.name)">{{ t('accounts.list.delete') }}</Button>
                  </div>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>

    <Dialog v-model:open="isCreateDialogOpen">
      <DialogContent class="sm:max-w-[700px]">
        <DialogHeader>
          <DialogTitle>{{ t('accounts.createDialog.title') }}</DialogTitle>
          <DialogDescription>{{ t('accounts.createDialog.description') }}</DialogDescription>
        </DialogHeader>
        <div class="space-y-4">
          <div class="grid gap-2">
            <Label>{{ t('accounts.createDialog.name') }}</Label>
            <Input v-model="newName" :placeholder="t('accounts.createDialog.namePlaceholder')" />
          </div>
          <div class="grid gap-2">
            <Label>{{ t('accounts.createDialog.jsonContent') }}</Label>
            <Textarea v-model="newContent" class="min-h-[200px]" :placeholder="t('accounts.createDialog.jsonPlaceholder')" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="isCreateDialogOpen = false">{{ t('common.cancel') }}</Button>
          <Button :disabled="isSaving" @click="handleCreateAccount">
            {{ isSaving ? t('common.saving') : t('common.save') }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="isEditDialogOpen">
      <DialogContent class="sm:max-w-[700px]">
        <DialogHeader>
          <DialogTitle>{{ t('accounts.editDialog.title', { name: editName }) }}</DialogTitle>
          <DialogDescription>{{ t('accounts.editDialog.description') }}</DialogDescription>
        </DialogHeader>
        <div class="space-y-4">
          <div class="grid gap-2">
            <Label>{{ t('accounts.createDialog.jsonContent') }}</Label>
            <Textarea v-model="editContent" class="min-h-[200px]" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="isEditDialogOpen = false">{{ t('common.cancel') }}</Button>
          <Button :disabled="isSaving" @click="handleUpdateAccount">
            {{ isSaving ? t('common.saving') : t('common.save') }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="isDeleteDialogOpen">
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{{ t('accounts.deleteDialog.title') }}</DialogTitle>
          <DialogDescription>{{ t('accounts.deleteDialog.description', { name: deleteName }) }}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" @click="isDeleteDialogOpen = false">{{ t('common.cancel') }}</Button>
          <Button variant="destructive" :disabled="isSaving" @click="handleDeleteAccount">
            {{ isSaving ? t('accounts.deleteDialog.deleting') : t('accounts.list.delete') }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="isQrDialogOpen">
      <DialogContent class="sm:max-w-[420px]">
        <DialogHeader>
          <DialogTitle>{{ t('accounts.qr.title') }}</DialogTitle>
          <DialogDescription>{{ t('accounts.qr.description') }}</DialogDescription>
        </DialogHeader>
        <div class="flex flex-col items-center gap-4">
          <div class="grid w-full gap-2">
            <Label>{{ t('accounts.qr.name') }}</Label>
            <Input v-model="qrName" :placeholder="t('accounts.qr.namePlaceholder')" :disabled="isQrPolling || qrStatus === 'generating'" />
          </div>

          <template v-if="qrStatus === 'generating'">
            <div class="py-8 text-sm text-muted-foreground">{{ t('accounts.qr.generating') }}</div>
          </template>

          <template v-else-if="qrImage">
            <div class="rounded-lg border p-3">
              <img :src="qrImage" class="h-56 w-56 object-contain" alt="QR" />
            </div>
            <div class="text-sm">
              <span v-if="qrStatus === 'waiting'" class="text-gray-600">{{ t('accounts.qr.waiting') }}</span>
              <span v-else-if="qrStatus === 'scanned'" class="text-blue-600">{{ t('accounts.qr.scanned') }}</span>
              <span v-else-if="qrStatus === 'success'" class="text-green-600">{{ t('accounts.qr.success') }}</span>
            </div>
          </template>

          <div v-if="qrError" class="text-sm text-red-600">{{ qrError }}</div>
          <div class="text-xs text-gray-400">{{ t('accounts.qr.hint') }}</div>
        </div>
        <DialogFooter>
          <div class="flex w-full items-center justify-between gap-2">
            <Button v-if="isQrPolling" variant="outline" @click="stopQrPolling(); qrStatus = ''">{{ t('accounts.qr.regenerate') }}</Button>
            <span v-else></span>
            <Button variant="outline" @click="isQrDialogOpen = false" :disabled="isQrPolling">{{ t('common.cancel') }}</Button>
            <Button v-if="!isQrPolling" :disabled="qrStatus === 'generating'" @click="startQrLogin">
              {{ qrStatus === 'generating' ? t('accounts.qr.generating') : t('accounts.qr.start') }}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
