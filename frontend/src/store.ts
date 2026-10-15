import { create } from 'zustand'
import { api } from './api'
import type { Component, Issue, Project, Workspace } from './types'

const HISTORY_LIMIT = 100

interface Toast { id: number; kind: 'ok' | 'error' | 'info'; text: string }

interface State {
  workspace: Workspace
  project: Project | null
  past: Project[]
  future: Project[]
  dirty: boolean
  saving: boolean
  lastSaved: string | null
  selection: string[] // entity ids highlighted across workspaces (twin-aware)
  issues: Issue[]
  validatedAt: string | null
  library: Record<string, Component>
  toasts: Toast[]
  setWorkspace: (w: Workspace) => void
  open: (id: string) => Promise<void>
  close: () => void
  /** Apply an edit. Every edit is undoable and marks the project dirty (autosaved). */
  edit: (fn: (p: Project) => void, opts?: { merge?: boolean }) => void
  replace: (p: Project) => void
  undo: () => void
  redo: () => void
  save: () => Promise<void>
  select: (ids: string[]) => void
  validate: (stage?: string) => Promise<void>
  loadLibrary: () => Promise<void>
  toast: (kind: Toast['kind'], text: string) => void
}

let saveTimer: ReturnType<typeof setTimeout> | undefined
let lastMergeAt = 0

export const useStore = create<State>((set, get) => ({
  workspace: 'dashboard',
  project: null,
  past: [],
  future: [],
  dirty: false,
  saving: false,
  lastSaved: null,
  selection: [],
  issues: [],
  validatedAt: null,
  library: {},
  toasts: [],
  setWorkspace: (workspace) => set({ workspace }),
  open: async (id) => {
    const p = await api.get<Project>(`/api/projects/${id}`)
    set({ project: p, past: [], future: [], dirty: false, issues: [], selection: [], workspace: 'world' })
    get().validate()
  },
  close: () => set({ project: null, workspace: 'dashboard', past: [], future: [] }),
  edit: (fn, opts) => {
    const cur = get().project
    if (!cur) return
    const next = structuredClone(cur)
    fn(next)
    const now = Date.now()
    // merge rapid successive edits (e.g. dragging a gizmo or a slider) into one undo step
    const merge = opts?.merge && now - lastMergeAt < 600
    lastMergeAt = now
    set((s) => ({
      project: next,
      past: merge ? s.past : [...s.past.slice(-HISTORY_LIMIT + 1), cur],
      future: [],
      dirty: true,
    }))
    clearTimeout(saveTimer)
    saveTimer = setTimeout(() => get().save(), 1200)
  },
  replace: (p) => {
    const cur = get().project
    set((s) => ({ project: p, past: cur ? [...s.past, cur] : s.past, future: [], dirty: true }))
    clearTimeout(saveTimer)
    saveTimer = setTimeout(() => get().save(), 600)
  },
  undo: () => {
    const { past, project, future } = get()
    if (!past.length || !project) return
    set({ project: past[past.length - 1], past: past.slice(0, -1), future: [project, ...future], dirty: true })
    clearTimeout(saveTimer)
    saveTimer = setTimeout(() => get().save(), 1200)
  },
  redo: () => {
    const { past, project, future } = get()
    if (!future.length || !project) return
    set({ project: future[0], future: future.slice(1), past: [...past, project], dirty: true })
    clearTimeout(saveTimer)
    saveTimer = setTimeout(() => get().save(), 1200)
  },
  save: async () => {
    const p = get().project
    if (!p?.id) return
    set({ saving: true })
    try {
      const r = await api.put<{ updated_at: string }>(`/api/projects/${p.id}`, p)
      set({ dirty: false, lastSaved: r.updated_at })
    } catch (e) {
      get().toast('error', `Save failed: ${(e as Error).message}`)
    } finally {
      set({ saving: false })
    }
  },
  select: (selection) => set({ selection }),
  validate: async (stage = 'pre_simulation') => {
    const p = get().project
    if (!p) return
    try {
      const r = await api.post<{ issues: Issue[] }>('/api/validate', p, { stage })
      set({ issues: r.issues, validatedAt: new Date().toISOString() })
    } catch (e) {
      get().toast('error', `Validation failed: ${(e as Error).message}`)
    }
  },
  loadLibrary: async () => {
    if (Object.keys(get().library).length) return
    const all = await api.get<Component[]>('/api/library/full')
    set({ library: Object.fromEntries(all.map((c) => [c.id, c])) })
  },
  toast: (kind, text) => {
    const id = Date.now() + Math.random()
    set((s) => ({ toasts: [...s.toasts, { id, kind, text }] }))
    setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), 5000)
  },
}))

export const uid = (prefix: string) => `${prefix}${Math.random().toString(36).slice(2, 7)}`
