# Personal AI interface system

The shared web styling contract is `pwa/design-system.css`. It owns semantic colors,
spacing, radii, elevation, motion, layering, readable widths, interaction states,
and the optional light-theme token architecture. `pwa/layout.css` contains feature
layout and responsive geometry; it has no independent color palette. Superseded
same-selector declarations were removed, retaining media-query order and CSS priority.
The original canvas sphere geometry and drawing functions remain unchanged.

Use the accent for state and identity. Primary actions use the darker semantic
`--action-primary` tone so small white text meets contrast requirements. The orb
alone has a separate identity palette. Ordinary content is solid; blur is limited
to floating layers with a solid fallback. Respect reduced motion and visible focus.

## Shared controls and surfaces

- Buttons: `.ui-button`, `.ui-primary`, `.ui-danger`, `.ui-icon`.
- Forms: shared search/input families with 44px controls and 16px input text.
- Content: `.data-card`, `.settings-row`, `.module-toolbar`, `.ui-empty`.
- Dialogs: the native `uiDialog` focus/inert/Escape contract, queued confirmation
  and text entry helpers, and a mobile sheet presentation.
- Loading: `renderModuleLoading` and `.ui-skeleton`; retry and permission states
  disclose useful next steps without exposing server traces.
- Chat: open assistant responses, content-sized user bubbles, canonical time/date
  metadata, real supported actions, code-copy headers, selectable Markdown,
  bounded composer growth, and a scroll-to-latest control.
- Attachments: upload progress/status explicitly describes Knowledge ingestion;
  dismissing status does not delete an uploaded document.

The main navigation, left conversation history/search, and right chronological
Timeline remain independent. Mobile panels use edge overlays, focus containment,
backdrops, safe areas, and a documented z-index scale. Mobile Settings opens a
category list, then detail, with an All settings return control. Desktop keeps
categories alongside detail.

## Other clients

`web-companion/design-system.css` is generated from the token preamble of the
canonical PWA stylesheet. The contract test detects drift. Companion layout consumes
those tokens, retains its Pulse Core, and preserves session-only credentials.
`ui/design_system.py` owns the Qt stylesheet and stroke icons shared by the desktop
window and its dialogs. SwiftUI's `PersonalAITheme` and Android's `PersonalAITheme`
map the same identity palette to native controls, safe platform navigation and
scrollable forms; neither replaces the original PWA sphere or desktop Pulse renderer.

## Verification and release gate

The web runners test all eleven specified widths with application API fixtures,
not replacement production data. Axe scans cover the shell, both histories,
Timeline, chat, dialogs, graph/tree, modules, Settings categories, authentication,
and permission/error states. Companion checks cover its four pages and actual
pairing/command/memory handlers with isolated fixtures. Desktop checks render all
eight routes and verify voice controls. CI builds/packages the native applications
and runs existing integration/security suites.

Browser emulation does not establish physical iPhone/Android microphone, keyboard,
PWA safe areas, touch, external identity-provider login, or camera/file behavior.
Those remain a separate owner/device acceptance gate. No merge or deployment is
performed by this UI finishing workflow. The draft PR remains stacked on the
existing UI work, preserving other open PRs and backend/security changes.
