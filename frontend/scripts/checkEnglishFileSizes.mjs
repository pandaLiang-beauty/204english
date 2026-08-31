import { readdir, readFile } from 'node:fs/promises'
import { join, relative } from 'node:path'

const root = 'src/english'
const maxLines = 600
const sourceExtensions = new Set(['.js', '.vue'])
const violations = []

async function collect(directory) {
  const entries = await readdir(directory, { withFileTypes: true })
  for (const entry of entries) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) {
      await collect(path)
      continue
    }
    if (!sourceExtensions.has(entry.name.slice(entry.name.lastIndexOf('.')))) continue
    const text = await readFile(path, 'utf8')
    const lines = text ? text.split('\n').length : 0
    if (lines > maxLines) violations.push({ path: relative('.', path), lines })
  }
}

await collect(root)

if (violations.length) {
  console.error(`English source files must stay within ${maxLines} lines:`)
  for (const item of violations) console.error(`- ${item.path}: ${item.lines}`)
  process.exitCode = 1
} else {
  console.log(`English file-size check passed (max ${maxLines} lines).`)
}
