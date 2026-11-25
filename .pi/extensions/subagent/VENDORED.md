# Vendored: Pi subagent extension

Copied unmodified from `@earendil-works/pi-coding-agent` 0.85.1
(`examples/extensions/subagent/{index.ts,agents.ts}`, MIT license).
Pi has no built-in sub-agents; this extension adds the `subagent` tool.

Project agents live in `.pi/agents/` (generated from `.agents/agents/`). Call the tool with
`agentScope: "project"` (or `"both"`) so they are discovered.

Refresh after upgrading Pi:
`cp "$(npm root -g)/@earendil-works/pi-coding-agent/examples/extensions/subagent/"{index,agents}.ts .pi/extensions/subagent/`

## License

The upstream package declares `"license": "MIT"` and `"author": "Mario Zechner"` in its
`package.json` and ships no LICENSE file, so the notice below is the standard MIT text with that
author. These two files remain under MIT; the rest of this repository is Apache-2.0.

```
MIT License

Copyright (c) Mario Zechner

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
