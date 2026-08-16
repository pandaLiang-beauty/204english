export const englishNavigation = {
  entryView: 'review',
  nav: [
    { value: 'review', label: '复习', icon: 'BookOpenCheck' },
    { value: 'library', label: '句库', icon: 'Map' },
    { value: 'passages', label: '阅读', icon: 'LayoutList' },
    { value: 'stats', label: '统计', icon: 'BarChart3' }
  ],
  pathViews: {
    '/english': 'review',
    '/english/review': 'review',
    '/english/library': 'library',
    '/english/passages': 'passages',
    '/english/create': 'create',
    '/english/stats': 'stats'
  },
  viewPaths: {
    review: '/english',
    library: '/english/library',
    passages: '/english/passages',
    create: '/english/create',
    stats: '/english/stats'
  },
  activeNav(view) {
    return view === 'create' ? 'passages' : view
  }
}

export function viewFromPath(path) {
  const normalized = String(path || '/').replace(/\/+$/, '') || '/'
  return englishNavigation.pathViews[normalized] || englishNavigation.entryView
}

export function pathForView(view) {
  return englishNavigation.viewPaths[view] || englishNavigation.viewPaths[englishNavigation.entryView]
}
