# Eggie DocuFlow Home UI Reference

Date: 2026-07-09

Reference image: `docs/ui/home_ui_reference_20260709.png`

Runtime check image: `docs/ui/all_pages_runtime_check_20260709.png`

Confirmed direction:
- Use the real Eggie logo in the upper-left sidebar.
- Home layout: left navigation, main two-column tool cards, fixed right information panel.
- Tool cards keep one clear action button: open the tool.
- Avoid fake recent files or fake processing counts in the real app.
- Keep OCR as a settings-level entry later, not as a forced step on every tool page.

Current implementation scope:
- Home page and all tool pages now share the same light workspace style.
- Tool pages use the same page background, card border, button, input and table style.
- Packaged app includes the homepage logo asset used by the left sidebar.
- Existing processing logic stays unchanged.
