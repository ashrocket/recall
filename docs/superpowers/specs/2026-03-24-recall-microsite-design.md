# recall microsite design

## Summary

Rename the repo from `recall-skill` to `recall`. Build a new microsite that positions recall as the anchor of a three-tool family (recall, agent-pb, agent-look) with a shared visual identity rooted in recall's existing warm-pastel aesthetic.

The site uses a physical/analog "filing cabinet" metaphor — index cards, manila folders, sticky notes, paper textures, paper clips — to stand apart from the generic Claude-generated landing page template.

## Goals

1. Rename repo, update all references (plugin.json, README, wrangler.toml, install commands, GitHub URLs)
2. Build a single-page microsite (`docs/index.html`) with the filing cabinet design
3. Establish a shared family nav linking all three agent-* tools
4. Keep the site as a single HTML file — no build tools, no JS frameworks, CSS-only interactions

## Non-goals

- Rebuilding agent-pb or agent-look's sites (they'll adopt the shared nav later)
- Adding JavaScript interactivity
- External CSS/image dependencies (everything inline except Google Fonts)

## Design concept: "The Filing Cabinet"

The site is built around the metaphor of a physical memory system. Not full skeuomorphism — suggestive. Subtle paper grain, cards that feel like index cards (lined, slightly off-white, red margin line), tab dividers as section markers.

The existing recall palette maps naturally to colored index card dividers and sticky note accents.

### What makes it not look like every other Claude-generated site

| Generic pattern | Our approach |
|---|---|
| Gradient rainbow text hero | Clean type with a hand-drawn red-pen circle annotation around "remember" |
| 3-column feature card grid | Index cards pinned at slight angles with colored tab dividers |
| Fake terminal floating in white space | Terminal blocks sitting on a "desk" with sticky note annotations beside them |
| Perfect symmetry everywhere | Slight card rotations (-1deg to 2deg), offset sticky notes, CSS paper clips |
| Dark code block in white void | Code blocks on cream index cards with tab labels |

## Visual identity

### Palette (inherited from recall, now the family palette)

```
--bg:             #fef9f2    (cream paper)
--bg2:            #fef3e6    (warm paper)
--surface:        #ffffff    (card white)
--surface-warm:   #fffaf4    (index card)
--border:         #f0ddd0
--border-strong:  #e0c8b0
--text:           #3d2416    (ink brown)
--text-muted:     #9a7a68
--text-light:     #c4a898
--text-bright:    #1a0800

--pink:           #f9c0d8    (tab divider 1)
--pink-deep:      #d6638a
--lav:            #d4c4f4    (tab divider 2)
--lav-deep:       #8b6ed4
--mint:           #b4e8d0    (tab divider 3)
--mint-deep:      #3a9e78

--accent:         #e07454    (coral — primary action)
--red-pen:        #c0392b    (annotation circle)
--sticky-yellow:  #fff7b3    (sticky notes)
--sticky-shadow:  rgba(0,0,0,0.08)
```

### Typography

- **Headings:** Plus Jakarta Sans, 700-800 weight
- **Body:** Plus Jakarta Sans, 400-500 weight
- **Code/mono:** JetBrains Mono
- **Annotations:** Caveat (Google Font, ~400 weight) for handwritten-feel notes on index cards and sticky notes

### CSS techniques (no JS)

- **Paper texture:** Subtle `background-image` inline SVG noise pattern
- **Index cards:** Cream bg + `repeating-linear-gradient` for lined paper + red margin line via left border
- **Card rotations:** `transform: rotate(-1deg)` to `rotate(2deg)` — asymmetric, not random
- **Sticky notes:** Background color + slight box-shadow + CSS triangle corner fold
- **Red pen circle:** Inline SVG `<ellipse>` with rough stroke (`stroke-dasharray` + slight transforms)
- **Paper clips:** Pure CSS pseudo-elements (rotated rounded rectangles)
- **Tab dividers:** Colored top-edge on cards with a protruding tab shape via pseudo-element
- **Manila folder tabs:** `border-radius` top corners + colored bg, connected by dotted lines

## Page structure

### 0. Family nav (shared across all agent-* sites)

Slim top bar, fixed position. Cream background with blur backdrop.

```
[recall]  [agent-pb]  [agent-look]          GitHub →
```

- Current site name is bold with coral underline
- Other names are muted links
- Monospace font (JetBrains Mono) for the names
- Height: ~52px

### 1. Hero

**Headline:** "Your AI should remember things."
- Large Plus Jakarta Sans, clean weight
- The word "remember" gets a hand-drawn red-pen circle (SVG ellipse, slightly tilted, rough stroke)
- No gradient text, no rainbow

**Subtitle:** Appears on a sticky note element
- "Session memory for Claude Code. Save context, distill it, resume without starting over."
- Sticky note has slight rotation, corner fold, yellow tint

**Install chip:** On a small index card
- Plugin install: `/install recall` in JetBrains Mono
- Card has faint lined-paper texture

**Pill badge:** "open source · MIT · Python 3.8+" — on a small tab divider shape, not a rounded pill

### 2. The Index — "What's in the box"

Three index cards representing the three skills:

| Card | Tab color | Skill | Demo |
|---|---|---|---|
| Card 1 | Pink | /recall | Session save/restart terminal snippet |
| Card 2 | Lavender | /failures | Bash failure tracking snippet |
| Card 3 | Mint | /history | Command history snippet |

Layout:
- Cards overlap slightly at edges, like a spread-out stack
- Each rotated -1 to 2 degrees
- Each has a colored tab at the top (protruding above the card)
- Card surface has lined-paper texture (horizontal lines)
- Red margin line on the left
- Terminal demos use cream background (not dark) to match the card surface
- A CSS paper clip holds the stack together (top-left area)

### 3. How it works — "Save. Distill. Resume."

Three manila folder tabs in a horizontal row, connected by a dotted line.

Each folder:
- Tab has rounded top corners, colored background
- Below the tab: a brief description + a terminal example
- The terminal example is on the folder surface (cream/manila, not dark)

Steps:
1. **Save** — `/recall save` captures messages, commands, decisions
2. **Distill** — Noise stripped, conclusions kept
3. **Resume** — `/recall restart 1` picks up mid-thought

### 4. Platforms — "Works wherever you code"

A corkboard-textured strip with three sticky notes pinned to it.

Each sticky note = one platform:
- **Claude Code** (yellow sticky) — SessionStart hook, auto-loads
- **Codex** (pink sticky) — AGENTS.md integration
- **Gemini CLI** (blue sticky) — GEMINI.md integration
- **Claude Desktop** (mint sticky) — MCP filesystem bridge

Four stickies in a 2x2 grid on mobile, horizontal row on desktop.

Each sticky has:
- Slight rotation and shadow
- Corner fold (CSS triangle)
- 2-3 bullet points
- Small terminal snippet

### 5. The agent-* family — "The toolkit"

Darker cream background ("desk surface").

Three items on the desk, each as a simple card with an icon and tagline:
- **recall** — An index card (current tool, subtle coral border highlight)
- **agent-pb** — Card with a butter-yellow accent bar and knife icon. Links to `https://agent-pb.pages.dev`
- **agent-look** — Card with a white border-bottom (polaroid style) and camera icon. Links to `https://agent-look.raiteri.net`

No complex CSS art — keep the metaphor in the card styling (accent colors, border treatments) rather than trying to illustrate butter pats or polaroids.

Tagline: "Small tools that stop you dragging things around."

### 6. Install

A large index card with lined paper texture containing install commands.

Content shows the actual install method (plugin marketplace):
```
# Claude Code (plugin)
$ /plugin marketplace add ashrocket/recall
$ /install recall

# Or clone and configure manually
$ git clone https://github.com/ashrocket/recall
$ cd recall
# follow README for settings.json hook config
```

A sticky note next to the card: "Requires Python 3.8+ · MIT licensed"

Note: `install.sh` does not currently exist. The install section shows the plugin marketplace flow as primary, with manual clone as secondary. If `install.sh` is created later, the site can be updated.

### 7. Footer

Clean, minimal. Paper-textured background.

- "Made by Ashley Raiteri"
- Links: recall · agent-pb · agent-look · GitHub
- Small paper clip decorative element

## Rename scope

Files to update when renaming from `recall-skill` to `recall`:

1. `.claude-plugin/plugin.json` — name, repository URL
2. `wrangler.toml` — change `name = "recall"` to `name = "recall"`
3. `README.md` — all references, clone URL, badges
4. `docs/index.html` — replaced entirely by new build
5. `docs/blog.html` — nav links, references
6. `docs/examples.html` — nav links, references
7. `docs/linkedin-post.md` — 2 GitHub URLs
8. `docs/comparison-vs-builtin-memory.md` — 14 occurrences of old name
9. `AGENTS.md` — repo references
10. `SKILL.md` — repo references
11. `skills/recall/SKILL.md` — repo references
12. `commands/recall.md` — plugin context references
13. All files under `docs/plans/` — sweep for old GitHub URLs (low priority, not public-facing)
14. Git remote URL (user action, not automated)

**Dependency:** The GitHub repo must be renamed to `ashrocket/recall` before deploying the site. Old GitHub URLs will redirect automatically after rename.

## Single file constraint

The entire site is one HTML file (`docs/index.html`). All CSS is inline in a `<style>` block. SVG elements (paper clip, red pen circle, noise texture) are inline. Minimal external dependencies: Google Fonts (JetBrains Mono, Plus Jakarta Sans, Caveat). Font stack includes system fallbacks for graceful degradation.

## Mobile responsive

Breakpoint at ~860px:
- Cards stack vertically, rotations removed on mobile
- Sticky notes stack in single column
- Folder tabs become vertical list
- Family nav wraps or collapses to horizontal scroll
- Padding reduces from 48px to 24px
- No horizontal overflow from rotated elements (parent `overflow: hidden` where needed)

## Red pen circle SVG reference

The hero annotation is design-critical. Reference implementation:
```svg
<svg viewBox="0 0 120 50" style="position:absolute; ...">
  <ellipse cx="60" cy="25" rx="56" ry="20"
    stroke="#c0392b" stroke-width="2.5" fill="none"
    stroke-dasharray="8 3" transform="rotate(-3 60 25)"
    opacity="0.75"/>
</svg>
```

## Deployment

Cloudflare Pages via `wrangler.toml` pointing at `docs/` directory. The rename changes the project name in wrangler.toml from `name = "recall"` to `name = "recall"`.
