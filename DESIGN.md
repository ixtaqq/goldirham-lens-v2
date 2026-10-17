---
name: Goldirham Lens
description: Numbers before narrative.
colors:
  carbon: "#07110E"
  graphite: "#101A16"
  graphite-high: "#16231E"
  paper: "#F0EEE7"
  fog: "#8D9992"
  mint: "#79D5C2"
  loss: "#E88078"
  rule: "rgb(141 153 146 / 0.22)"
  rule-strong: "rgb(141 153 146 / 0.42)"
typography:
  display:
    fontFamily: "Barlow Condensed, Arial Narrow, sans-serif"
    fontSize: "clamp(3.4rem, 10.5vw, 6rem)"
    fontWeight: 600
    lineHeight: 0.9
    letterSpacing: "-0.01em"
  section:
    fontFamily: "Barlow Condensed, Arial Narrow, sans-serif"
    fontSize: "clamp(2.4rem, 6vw, 3.9rem)"
    fontWeight: 600
    lineHeight: 0.95
  lede:
    fontFamily: "Geist, system-ui, sans-serif"
    fontSize: "clamp(1.125rem, 1.6vw, 1.3rem)"
    fontWeight: 400
    lineHeight: 1.5
  body:
    fontFamily: "Geist, system-ui, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 400
    lineHeight: 1.6
  data:
    fontFamily: "Geist Mono, ui-monospace, monospace"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "0.02em"
rounded:
  none: "0px"
spacing:
  gutter-mobile: "16px"
  gutter: "32px"
  shell: "84rem"
  section: "96px"
components:
  button-primary:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.carbon}"
    rounded: "{rounded.none}"
    padding: "12px 20px"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.paper}"
    rounded: "{rounded.none}"
    padding: "12px 20px"
  message:
    backgroundColor: "{colors.graphite}"
    textColor: "{colors.paper}"
    rounded: "{rounded.none}"
    padding: "16px 20px"
  day-tab-selected:
    backgroundColor: "{colors.graphite}"
    textColor: "{colors.paper}"
    rounded: "{rounded.none}"
    padding: "12px 20px"
---

## Overview

A research ledger at night. The page is carbon ground under a fixed field of faint price traces and a 12-column grid of 1px rules. Content sits in ruled sections, figures are set in mono with their session date and source beside them, and the sample briefing is shown as the actual Telegram text. Nothing is glass, nothing is rounded, nothing glows.

Motion explains in the order the product works. A trace crosses the verification frame and turns mint for a moment. The briefing arrives section by section. The pipeline section pins and steps through collect, check, measure, decide, send. Charts draw once. Everything else stays still.

**Creative North Star: "The checked ledger."**

**Key Characteristics:**

- A fixed signal field behind everything: WebGL2 traces, a Canvas 2D fallback and a build-time SVG poster, all drawn from the same demo fixture.
- Ruled sections on carbon at 70 to 80% opacity, so the field reads strongly in the hero and faintly elsewhere.
- Telegram messages as graphite panels with a 1px strong rule and a mono header row.

**The Evidence Rule.** Mint appears only where something was verified: the trace inside the verification frame, a passed check, a healthy data status. It is never decoration.

## Colors

### Primary

Mint is the single accent and means "checked and passed".

### Secondary

Loss marks failed checks, disputed bars, negative changes and unhealthy data status. It never marks emphasis.

### Neutral

Carbon is the ground. Graphite holds messages, the selected day tab and pinned panels; graphite-high is the hover state for ledger rows on fine pointers. Paper carries text and figures, at 85% for prose. Fog carries secondary text, labels and the background traces. Rule (22% fog) separates rows and sections; rule-strong (42% fog) frames messages, tables and controls.

**The One Accent Rule.** No other hue enters the palette. Charts use paper, fog, mint and loss only.

## Typography

Barlow Condensed for the hero and section headings, Geist for prose and controls, Geist Mono for every figure, ticker, reason code, session date, source and data label. Prose captions and notices use Geist at the data size in fog (the `note` style); mono is not used for sentences.

### Hierarchy

Display (up to 6rem, line-height 0.9) appears once, in the hero. Section headings are 2.4 to 3.9rem condensed. Step and day titles are condensed at 1.9 to 2.25rem. Body copy runs at 17px with a 34 to 62 character measure.

**The Figures Are Mono Rule.** Any number a visitor could compare with another number is set in Geist Mono with tabular figures, and it is the string Python produced. The page never formats a figure itself.

## Layout

One 84rem shell with a 16px gutter on phones and 32px from 768px. Sections are separated by a full-width 1px rule and 64 to 96px of padding, with the heading and its introduction side by side from 768px. The briefing section starts at the hero's bottom edge with the three day tabs. On wide screens the day notes stay sticky beside the message, and the pipeline pins for about four and a half viewports. Nothing scrolls sideways at 360px; wide tables scroll inside a focusable, labelled region.

## Elevation & Depth

Flat. Depth comes from graphite on carbon and from rules. The only layering is the fixed signal field behind translucent carbon sections.

**The No Glass Rule.** No shadows, blur, glow or translucent cards.

## Shapes

Square corners everywhere. Rules are 1px. Status marks are 8px squares. The brand mark is a square verification frame crossed by a stepped trace whose inside segment is mint.

## Components

### Buttons

Primary is a paper-filled rectangle with carbon text; secondary is a rule-strong outline that turns paper on hover. Both press to `scale(0.97)` over 140ms.

### Day tabs

Three equal cells in a ruled strip: date in mono, title in condensed. The selected tab is graphite with a 1px paper rule along its base. Arrow keys, Home and End move between tabs. Without JavaScript the tabs are anchors and CSS `:target` swaps the day.

### Telegram message

A graphite panel with a rule-strong border, a mono header row (bot name, send time) and the briefing sections set in Geist at 15px with pre-wrapped lines, bold for headings and fog for italics.

### Ledger table

Mono header labels in fog, rows separated by 1px rules, first column as row headers in paper, backtick spans from the strategy reference rendered as inline code.

### Signature: verification frame

The brand mark at hero scale with a ruled caption ("verification frame", "verified" in mint). On first visit its frame and trace draw in, and the headline lifts word by word, all within 1.6s.

## Do's and Don'ts

### Do:

- Show the session date and source next to figures.
- Show a failed check with its reason code, struck through or in fog, at full contrast.
- Let a quiet day look quiet.
- Give every moving layer a Pause motion control and a still fallback.

### Don't:

- Use candlestick imagery, neon tickers, bull and bear motifs or trading-floor photography.
- Animate a number counting up through values that were never true.
- Add a status light or "live" badge; the showcase runs on demo data.
- Put a kicker or eyebrow label above a heading.
- Fade withheld data below contrast to show it dropped out.
