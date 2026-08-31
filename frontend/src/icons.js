// 把真正用到的 25 个 lucide 图标就地定义在这一个文件里，替掉 `@lucide/vue` 那个整库 barrel。
//
// 为什么值得这么干（两笔账，都是被 Cloudflare 隧道放大出来的）：
//   1. 体积：dev 模式下 vite 会把整个 @lucide/vue 预打包成 4.2MB 的一个 chunk，过隧道压缩后
//      仍有 558KB。这条链路实测只有 40~115KB/s，光它一个就要 5~13.5 秒。
//   2. 请求数：这条隧道每个请求要多付约 0.14 秒（25 个小文件走同一条 HTTP/2 连接实测 3.6 秒），
//      所以「改成 25 个深导入」省下的体积会被多出来的 24 个请求吃掉大半。
// 结论就是这个写法：一个文件、一个请求、约 8KB，两笔账同时省下来。
//
// vite.config.js 里把 `@lucide/vue` 精确别名到本文件，所以组件里的 import 一行都不用改。
// ⚠️ 新用一个图标，就得在这里补一行，否则组件里 import 会拿到 undefined。抄法：打开
// node_modules/@lucide/vue/dist/esm/icons/<kebab-case>.mjs，把里面 __iconNode 那个数组
// 复制过来（BarChart3 是个别名，真实文件是 chart-column）。

import createLucideIcon from '@lucide/vue/dist/esm/createLucideIcon.mjs'

export const BarChart3 = /* @__PURE__ */ createLucideIcon('chart-column', [ ["path", { d: "M3 3v16a2 2 0 0 0 2 2h16", key: "c24i48" }], ["path", { d: "M18 17V9", key: "2bz60n" }], ["path", { d: "M13 17V5", key: "1frdt8" }], ["path", { d: "M8 17v-3", key: "17ska0" }] ])
export const Bold = /* @__PURE__ */ createLucideIcon('bold', [ [ "path", { d: "M6 12h9a4 4 0 0 1 0 8H7a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h7a4 4 0 0 1 0 8", key: "mg9rjx" } ] ])
export const BookOpenCheck = /* @__PURE__ */ createLucideIcon('book-open-check', [ ["path", { d: "M12 5v16", key: "1f6ucr" }], ["path", { d: "m16 12 2 2 4-4", key: "mdajum" }], [ "path", { d: "M22 6V5a2 2 0 0 0-1.999-2L16 3.002A5 5 0 0 0 12 5a5 5 0 0 0-4-2H4a2 2 0 0 0-2 2v12a2 2 0 0 0 1.999 2H8a5 5 0 0 1 4 2 5 5 0 0 1 4-2h4.001A2 2 0 0 0 22 17v-1.344", key: "144kbk" } ] ])
export const Check = /* @__PURE__ */ createLucideIcon('check', [["path", { d: "M20 6 9 17l-5-5", key: "1gmf2c" }]])
export const ChevronLeft = /* @__PURE__ */ createLucideIcon('chevron-left', [["path", { d: "m15 18-6-6 6-6", key: "1wnfg3" }]])
export const ChevronRight = /* @__PURE__ */ createLucideIcon('chevron-right', [["path", { d: "m9 18 6-6-6-6", key: "mthhwq" }]])
export const Eye = /* @__PURE__ */ createLucideIcon('eye', [ [ "path", { d: "M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0", key: "1nclc0" } ], ["circle", { cx: "12", cy: "12", r: "3", key: "1v7zrd" }] ])
export const EyeOff = /* @__PURE__ */ createLucideIcon('eye-off', [ [ "path", { d: "M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696 10.747 10.747 0 0 1-1.444 2.49", key: "ct8e1f" } ], ["path", { d: "M14.084 14.158a3 3 0 0 1-4.242-4.242", key: "151rxh" }], [ "path", { d: "M17.479 17.499a10.75 10.75 0 0 1-15.417-5.151 1 1 0 0 1 0-.696 10.75 10.75 0 0 1 4.446-5.143", key: "13bj9a" } ], ["path", { d: "m2 2 20 20", key: "1ooewy" }] ])
export const Languages = /* @__PURE__ */ createLucideIcon('languages', [ ["path", { d: "m5 8 6 6", key: "1wu5hv" }], ["path", { d: "m4 14 6-6 2-3", key: "1k1g8d" }], ["path", { d: "M2 5h12", key: "or177f" }], ["path", { d: "M7 2h1", key: "1t2jsx" }], ["path", { d: "m22 22-5-10-5 10", key: "don7ne" }], ["path", { d: "M14 18h6", key: "1m8k6r" }] ])
export const LayoutList = /* @__PURE__ */ createLucideIcon('layout-list', [ ["rect", { width: "7", height: "7", x: "3", y: "3", rx: "1", key: "1g98yp" }], ["rect", { width: "7", height: "7", x: "3", y: "14", rx: "1", key: "1bb6yr" }], ["path", { d: "M14 4h7", key: "3xa0d5" }], ["path", { d: "M14 9h7", key: "1icrd9" }], ["path", { d: "M14 15h7", key: "1mj8o2" }], ["path", { d: "M14 20h7", key: "11slyb" }] ])
export const LogOut = /* @__PURE__ */ createLucideIcon('log-out', [ ["path", { d: "m16 17 5-5-5-5", key: "1bji2h" }], ["path", { d: "M21 12H9", key: "dn1m92" }], ["path", { d: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4", key: "1uf3rs" }] ])
export const Map = /* @__PURE__ */ createLucideIcon('map', [ [ "path", { d: "M14.106 5.553a2 2 0 0 0 1.788 0l3.659-1.83A1 1 0 0 1 21 4.619v12.764a1 1 0 0 1-.553.894l-4.553 2.277a2 2 0 0 1-1.788 0l-4.212-2.106a2 2 0 0 0-1.788 0l-3.659 1.83A1 1 0 0 1 3 19.381V6.618a1 1 0 0 1 .553-.894l4.553-2.277a2 2 0 0 1 1.788 0z", key: "169xi5" } ], ["path", { d: "M15 5.764v15", key: "1pn4in" }], ["path", { d: "M9 3.236v15", key: "1uimfh" }] ])
export const Moon = /* @__PURE__ */ createLucideIcon('moon', [ [ "path", { d: "M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803a6 6 0 0 0 8.268 8.268c.344-.215.825-.004.803.401", key: "kfwtm" } ] ])
export const Pause = /* @__PURE__ */ createLucideIcon('pause', [ ["rect", { x: "14", y: "3", width: "5", height: "18", rx: "1", key: "kaeet6" }], ["rect", { x: "5", y: "3", width: "5", height: "18", rx: "1", key: "1wsw3u" }] ])
export const Pencil = /* @__PURE__ */ createLucideIcon('pencil', [ [ "path", { d: "M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z", key: "1a8usu" } ], ["path", { d: "m15 5 4 4", key: "1mk7zo" }] ])
export const Play = /* @__PURE__ */ createLucideIcon('play', [ [ "path", { d: "M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z", key: "10ikf1" } ] ])
export const Plus = /* @__PURE__ */ createLucideIcon('plus', [ ["path", { d: "M5 12h14", key: "1ays0h" }], ["path", { d: "M12 5v14", key: "s699le" }] ])
export const RefreshCw = /* @__PURE__ */ createLucideIcon('refresh-cw', [ ["path", { d: "M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8", key: "v9h5vc" }], ["path", { d: "M21 3v5h-5", key: "1q7to0" }], ["path", { d: "M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16", key: "3uifl3" }], ["path", { d: "M8 16H3v5", key: "1cv678" }] ])
export const RotateCcw = /* @__PURE__ */ createLucideIcon('rotate-ccw', [ ["path", { d: "M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8", key: "1357e3" }], ["path", { d: "M3 3v5h5", key: "1xhq8a" }] ])
export const Search = /* @__PURE__ */ createLucideIcon('search', [ ["path", { d: "m21 21-4.34-4.34", key: "14j7rj" }], ["circle", { cx: "11", cy: "11", r: "8", key: "4ej97u" }] ])
export const Sparkles = /* @__PURE__ */ createLucideIcon('sparkles', [ [ "path", { d: "M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594z", key: "1s2grr" } ], ["path", { d: "M20 2v4", key: "1rf3ol" }], ["path", { d: "M22 4h-4", key: "gwowj6" }], ["circle", { cx: "4", cy: "20", r: "2", key: "6kqj1y" }] ])
export const Sun = /* @__PURE__ */ createLucideIcon('sun', [ ["circle", { cx: "12", cy: "12", r: "4", key: "4exip2" }], ["path", { d: "M12 2v2", key: "tus03m" }], ["path", { d: "M12 20v2", key: "1lh1kg" }], ["path", { d: "m4.93 4.93 1.41 1.41", key: "149t6j" }], ["path", { d: "m17.66 17.66 1.41 1.41", key: "ptbguv" }], ["path", { d: "M2 12h2", key: "1t8f8n" }], ["path", { d: "M20 12h2", key: "1q8mjw" }], ["path", { d: "m6.34 17.66-1.41 1.41", key: "1m8zz5" }], ["path", { d: "m19.07 4.93-1.41 1.41", key: "1shlcs" }] ])
export const Trash2 = /* @__PURE__ */ createLucideIcon('trash-2', [ ["path", { d: "M10 11v6", key: "nco0om" }], ["path", { d: "M14 11v6", key: "outv1u" }], ["path", { d: "M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6", key: "miytrc" }], ["path", { d: "M3 6h18", key: "d0wm0j" }], ["path", { d: "M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2", key: "e791ji" }] ])
export const Upload = /* @__PURE__ */ createLucideIcon('upload', [ ["path", { d: "M12 3v12", key: "1x0j5s" }], ["path", { d: "m17 8-5-5-5 5", key: "7q97r8" }], ["path", { d: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4", key: "ih7n3h" }] ])
export const Volume2 = /* @__PURE__ */ createLucideIcon('volume-2', [ [ "path", { d: "M11 4.702a.705.705 0 0 0-1.203-.498L6.413 7.587A1.4 1.4 0 0 1 5.416 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.416a1.4 1.4 0 0 1 .997.413l3.383 3.384A.705.705 0 0 0 11 19.298z", key: "uqj9uw" } ], ["path", { d: "M16 9a5 5 0 0 1 0 6", key: "1q6k2b" }], ["path", { d: "M19.364 18.364a9 9 0 0 0 0-12.728", key: "ijwkga" }] ])
