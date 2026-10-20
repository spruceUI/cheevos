"""Wake PyUI's idle input wait when a background worker publishes a visible change."""


def request_redraw() -> None:
    """Request a frame from any thread, leaving older PyUI versions to their normal ticks.

    SpruceOS #1890 added this thread-safe notification. It wakes the UI thread without
    drawing on the worker or disturbing an active screensaver (.agents/pyui.md, "Idle frames").
    """
    from controller.controller import Controller

    redraw = getattr(Controller, "request_redraw", None)
    if redraw is not None:
        redraw()
