# Personal AI — Master UI/UX Design Constitution

**Version:** 1.0  
**Status:** Global product contract  
**Applies to:** PWA, companion web surfaces, desktop UI, iOS/Android clients, and all future product surfaces.

This constitution freezes the approved Personal AI visual and interaction language. Reference images define appearance and hierarchy; canonical application state and APIs define content. The current approved screen is the baseline: centralizing this system must not redesign screens or weaken existing behavior.

## 1. Governing rule

Every screen is composed from this chain:

`tokens → primitives → shared components → page pattern → real data → state → responsive behavior → accessibility → motion`

Before creating a component or choosing a value, search the existing shared system. Reuse an existing component or extend a variant. A one-off style is justified only by a real product or accessibility need. Future screens inherit this contract without repeating design decisions.

## 2. Product identity and visual hierarchy

Personal AI is dark-first, intelligent, calm, premium, precise, modern, minimal, and owner-controlled. Keep the hierarchy **content first, interaction second, decoration third**. Use dark/navy foundations, cool blue for interaction, thin borders, restrained translucency, generous space, crisp system typography, and semantic status colors. Avoid excessive gradients, blur, glow, shadows, nested cards, and decorative controls.

The existing Personal AI particle sphere is a protected identity asset. Reuse its canonical renderer and variants. Scale and placement may change; geometry, particles, animation concept, and recognizable appearance may not be casually replaced. Respect reduced motion and keep it from blocking interaction.

## 3. Semantic tokens

The canonical web tokens live in `pwa/design-system.css` under the `--pa-*` namespace. `pwa/primitives.css` consumes them. Existing token names remain compatibility aliases during gradual migration; do not bulk-replace them in a way that changes approved page appearance. Companion web token parity is generated and checked by `tests/test_ui_design_system.py`. Native clients keep their platform components and map the same semantic roles in their theme layers.

| Token family | Contract |
| --- | --- |
| Background/surface | `--pa-bg-*`, `--pa-surface-*` |
| Borders/text | `--pa-border-*`, `--pa-text-*` |
| Semantic color | blue = selected/action/focus; green = healthy/success; amber = pending/caution; red = danger/failure; purple/cyan/pink only for restrained classification |
| Typography | `--pa-font-family`, `--pa-text-*` |
| Spacing/radius | `--pa-space-*`, `--pa-radius-*` on a 4px spacing grid |
| Elevation/motion | `--pa-shadow-*`, `--pa-motion-*`, `--pa-ease` |
| Interaction/layout | `--pa-touch-min`, `--pa-z-*`, `--pa-page-*` |

The V1 token values are implemented in code, not documentation alone. Prefer tokens for every new shared or page-level rule. Do not add arbitrary colors, font sizes, radii, spacing, z-index, or transition durations where a token applies.

## 4. Typography and layout

Use the system font stack (`-apple-system`, SF Pro when available, Inter, system UI). The scale is 11/12/13/14/16/17/20/24/30/34px from micro through display. Page titles are normally 28–30px, section headings 20–22px, body text 16px, descriptions 14px, and metadata at least 11px. Keep line heights comfortable: body 1.45–1.55, headings about 1.15–1.25. Avoid competing text sizes within a row.

Use the 4px spacing scale. Main mobile insets are 14–20px by viewport; section gaps are generally 24–32px, headings to content 8–14px, and list-card gaps 8–10px. Cards use restrained surfaces and 14–18px corners; major containers use 18–22px; modal surfaces 22–28px. Borders provide structure; bright blue borders are for selected/focused state. Use shadows sparingly and blur only on floating layers where it remains performant.

## 5. Shared component contract

The current PWA shared classes and functions remain the functional source for existing controls. The `pa-*` classes in `pwa/primitives.css` are composable building blocks for new/updated pages: page, page/identity headers, section, card/group, row, icon tile, button variants, icon button, field/search/textarea, tabs/segmented/filter chips, status, metrics, switch/checkbox, empty/error, skeleton, toast/backdrop, bottom sheet, and popup surface. Existing `.ui-button`, `.ui-primary`, `.ui-icon`, `.data-card`, `.settings-row`, `.ui-empty`, `.ui-skeleton`, `.toast`, and native `uiDialog` remain supported during migration.

Button variants are primary, secondary, ghost, danger, compact, and icon. Rows may be standard, compact, selected, danger, disabled, or loading when needed. Avoid synonymous one-off classes. Components must use native HTML semantics first and expose a clear accessible name and state.

The global movable popup is the approved compact create/edit/review/move pattern where suitable. Its established behavior must keep it within the visible viewport and safe areas, respond to `visualViewport`/keyboard changes, preserve form state, and allow dragging from its handle/header only. Inputs and actions must never initiate dragging. A confirmation dialog is for focused confirmation; a mobile bottom sheet is for contextual options; a complex workflow belongs on a page. Do not claim drag/keyboard behavior merely because a popup surface style exists.

## 6. Product patterns and domain boundaries

- Main navigation remains Home, Today, Conversations, Memory, Knowledge, Activities, Tools, and Workflows. No bottom navigation without approval.
- Home, Chat, and the secondary-page identity header retain their approved distinct patterns. Do not add a giant glass header or an `ACTIVE` label under the sphere.
- Assistant chat messages remain open surfaces; user messages remain compact blue surfaces. Time separators are centered against the conversation content area. Message actions are icon-only, with 44px target areas.
- Memory remains separated into Ambient capture/review, Graph relationships, Tree hierarchy, and canonical Memory Detail. Knowledge remains approved documents/sources. Activities is audit history, not system telemetry.
- Apps, providers, devices, workflow states, counts, and recommendations must reflect real canonical state. Never seed reference-image examples into production.

## 7. States and action behavior

Data lifecycle is `loading → content | empty | error | offline`; partial failure must leave successful sections usable. Use structure-matching skeletons for known loading content, short inline progress for actions, polished empty states with useful next steps, and retryable concise errors. Never render raw objects, stack traces, `null`, `undefined`, or a generic permanent “Loading…”.

Meaningful actions follow `idle → pressed → pending → success | failure`. Disable duplicate submission while pending. Show success only after canonical acceptance, and roll back failed optimistic changes. Critical security/destructive operations wait for server confirmation. Deletion, account reset, session revocation, and permanent memory forgetting require explicit consequence and confirmation. Do not use browser alerts.

## 8. Motion and overlays

Use 120/180/240/320ms motion tokens and the shared ease curve. Motion communicates state: subtle press feedback, short opacity/translation page entrance, restrained expand/collapse, no bounce. Prefer transform and opacity over layout/large-blur animation. Reduce decorative motion under `prefers-reduced-motion` without removing functionality. Sidebar, backdrop, modal, popover, toast layers use the documented `--pa-z-*` scale, never arbitrary extreme z-index values. Manage focus, background interaction, Escape where safe, and focus restoration for dialogs.

## 9. Responsive and mobile requirements

Mobile-first acceptance widths are 320, 360, 375, 390/393, and 430px; tablet widths 768/820/1024px; desktop 1280/1440px. 390–393px is the primary visual target, but all supported screens must function at 320px. Tablet adapts layout rather than simply stretching mobile. Desktop uses page-appropriate max widths; text and cards must not expand indefinitely.

Use safe-area insets and `100dvh` with fallback for full-height surfaces. Inputs generally remain 16px or larger on iOS. The normal mobile page has one vertical scroll; only intentional carousels/filter rows and constrained overlays scroll internally. Avoid unintended horizontal page overflow. Preserve route, draft, selection, expansion, and filter state across orientation changes when practical. Test keyboard-open layouts and the physical iPhone/Safari/PWA separately where available.

## 10. Accessibility and security

Target WCAG 2.2 AA where applicable. Interactive targets are at least 44×44px. Provide visible focus, readable contrast, state text/icons in addition to color, flexible text sizes, keyboard operation, and screen-reader labels. Use landmarks and native buttons/links/inputs. Tree uses tree semantics and arrow navigation where practical; Graph has an equivalent accessible List view. Do not truncate security consequences or critical errors.

Respect server authorization and privacy boundaries. Never expose credentials, tokens, secrets, embeddings, hidden prompts/reasoning, or private internal metadata. UI visibility is not authorization. Do not fake unsupported controls or offline success.

## 11. Performance and implementation layers

Use the repository’s actual architecture, not a forced framework migration. The intended web layering is `tokens → base → primitives/shared components → page composition → responsive overrides`. Lazy-load major modules; paginate/window long lists; lazy-load Tree branches; bound and cluster Graph queries; avoid continuously running simulations; keep the sphere non-blocking. Use CSS animation for simple skeletons. Keep overlay geometry independent from arbitrary parent positioning.

Native clients keep platform-appropriate controls, safe-area behavior, and accessibility, while their theme layers map the same semantic roles. Do not replace the PWA sphere with native generic artwork or the desktop renderer with a web approximation.

## 12. QA and acceptance

Every major page is reviewed in normal, loading, empty, error, offline, partial-failure, long/short-content, keyboard, reduced-motion, small-mobile, tablet, and desktop states as applicable. Every action is checked idle, pending, success, and failure. Visual review compares alignment, margins, type, row/card heights, radii, icon size, section rhythm, safe areas, scroll extent, and overflow—not just subjective similarity.

Use repository-supported lint, type, unit/integration/E2E, accessibility, responsive/overflow, visual, and production-build checks. Do not claim physical device verification when only browser emulation ran. Document known limitations. A page is complete only when visual, functional, responsive, accessible, performant, secure, data-correct, and state-complete criteria pass.

## 13. Future-page brief

Every new screen specifies: purpose and route; header; title/description; primary action; search/filters; sections; real data and permission source; loading/empty/error/offline/partial states; responsive behavior; accessibility; motion; and verification. The agent must inherit established tokens/components automatically and only ask for a design decision when the system has a genuine gap.

## 14. No-regression rule

Do not redesign an already-approved screen while centralizing this system. Migrate incrementally, compare screenshots at the established viewports, and preserve APIs, authentication, permissions, domain boundaries, state behavior, and the protected sphere. Reference appearance never justifies fake data, dead controls, broken semantics, or weakened security.
