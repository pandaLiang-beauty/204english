Put optional local UI fonts here for manual visual experiments. Font binaries
are intentionally ignored by git and are not referenced by the default CSS.

Current local Claude-like font layout:

- `anthropic-sans/AnthropicSans-Text-*-Static.otf`
- `anthropic-serif/AnthropicSerif-Text-*-Static.otf`

The production frontend uses system font stacks so a clean clone can build the
same UI without these files. If a local font experiment is needed, add temporary
`@font-face` rules locally and do not commit them unless the font license allows
shipping the binaries.
