export const englishNavigation = {
  entryView: 'review',
  nav: [
    { value: 'review', label: '句子复习', shortLabel: '复习', icon: 'BookOpenCheck' },
    { value: 'passages', label: '真题阅读', shortLabel: '阅读', icon: 'BookOpen' },
    { value: 'library', label: '我的句库', shortLabel: '句库', icon: 'Library' },
    { value: 'stats', label: '学习记录', shortLabel: '记录', icon: 'BarChart3' }
  ],
  pathViews: {
    '/': 'review',
    '/review': 'review',
    '/library': 'library',
    '/passages': 'passages',
    '/create': 'create',
    '/stats': 'stats'
  },
  viewPaths: {
    review: '/',
    library: '/library',
    passages: '/passages',
    create: '/create',
    stats: '/stats'
  },
  activeNav(view) {
    return view === 'create' ? 'library' : view
  }
}

export function viewFromPath(path) {
  const normalized = String(path || '/').replace(/\/+$/, '') || '/'
  return englishNavigation.pathViews[normalized] || englishNavigation.entryView
}

export function pathForView(view) {
  return englishNavigation.viewPaths[view] || englishNavigation.viewPaths[englishNavigation.entryView]
}
