import pytest

from desktop.evidence_geometry import CoordinateSpace, GeometryContext, GeometryError, Rect, clip_rect, document_rect_to_screenshot, transform_sensitive_rectangles, viewport_rect_to_screenshot


def _ctx(**changes):
    values = dict(device_pixel_ratio=1.0, page_zoom=1.0, browser_window_x=100.0, browser_window_y=50.0, browser_window_width=1000.0, browser_window_height=800.0, content_offset_x=8.0, content_offset_y=80.0, monitor_x=0.0, monitor_y=0.0, monitor_width=1920.0, monitor_height=1080.0, monitor_scale=1.0, virtual_origin_x=0.0, virtual_origin_y=0.0, screenshot_origin_x=0.0, screenshot_origin_y=0.0, screenshot_width=1920.0, screenshot_height=1080.0, scroll_x=0.0, scroll_y=0.0)
    values.update(changes)
    return GeometryContext(**values)


@pytest.mark.parametrize('scale', [1.0, 2.0, 3.0])
def test_device_pixel_ratio(scale):
    mapped = viewport_rect_to_screenshot(Rect(10, 20, 30, 40, CoordinateSpace.BROWSER_VIEWPORT), _ctx(device_pixel_ratio=scale))
    assert mapped.width == pytest.approx(30 * scale)


def test_browser_zoom_and_chrome_offset():
    rect = Rect(10, 10, 20, 20, CoordinateSpace.BROWSER_VIEWPORT)
    normal = viewport_rect_to_screenshot(rect, _ctx(page_zoom=1.0, content_offset_y=70))
    zoomed = viewport_rect_to_screenshot(rect, _ctx(page_zoom=1.5, content_offset_y=110))
    assert zoomed.width == pytest.approx(normal.width * 1.5)
    assert zoomed.y != normal.y


def test_scroll_and_clipping():
    mapped = document_rect_to_screenshot(Rect(100, 220, 20, 20, CoordinateSpace.BROWSER_DOCUMENT), _ctx(scroll_x=40, scroll_y=200))
    assert mapped == viewport_rect_to_screenshot(Rect(60, 20, 20, 20, CoordinateSpace.BROWSER_VIEWPORT), _ctx(scroll_x=40, scroll_y=200))
    clipped = clip_rect(Rect(-10, -5, 25, 20, CoordinateSpace.SCREENSHOT_IMAGE), 100, 100)
    assert clipped and (clipped.x, clipped.y, clipped.width, clipped.height) == (0, 0, 15, 15)


def test_negative_and_positive_monitor_origins():
    rect = Rect(10, 10, 20, 20, CoordinateSpace.BROWSER_VIEWPORT)
    left = viewport_rect_to_screenshot(rect, _ctx(browser_window_x=-1800, screenshot_origin_x=-1920, virtual_origin_x=-1920))
    right = viewport_rect_to_screenshot(rect, _ctx(browser_window_x=1950, screenshot_origin_x=1920, virtual_origin_x=-1920))
    assert left.x >= 0 and right.x >= 0


def test_partial_and_cross_monitor_clipping():
    partial = clip_rect(Rect(-10, 20, 25, 20, CoordinateSpace.SCREENSHOT_IMAGE), 100, 100)
    cross = clip_rect(Rect(95, 20, 20, 20, CoordinateSpace.SCREENSHOT_IMAGE), 100, 100)
    assert partial and partial.width == 15
    assert cross and cross.width == 5


@pytest.mark.parametrize('rect', [
    Rect(0, 0, 0, 10, CoordinateSpace.SCREENSHOT_IMAGE),
    Rect(200, 200, 10, 10, CoordinateSpace.SCREENSHOT_IMAGE),
    Rect(float('nan'), 0, 10, 10, CoordinateSpace.SCREENSHOT_IMAGE),
])
def test_malformed_and_out_of_bounds_rectangles(rect):
    assert clip_rect(rect, 100, 100) is None


def test_missing_mapping_rejected():
    with pytest.raises(GeometryError):
        viewport_rect_to_screenshot(Rect(1, 1, 10, 10, CoordinateSpace.BROWSER_VIEWPORT), GeometryContext(screenshot_width=100, screenshot_height=100))


def test_all_declared_coordinate_spaces_have_explicit_transformations():
    ctx = _ctx()
    cases = [
        Rect(1, 1, 10, 10, CoordinateSpace.BROWSER_VIEWPORT),
        Rect(1, 1, 10, 10, CoordinateSpace.BROWSER_DOCUMENT),
        Rect(1, 1, 10, 10, CoordinateSpace.BROWSER_WINDOW),
        Rect(1, 1, 10, 10, CoordinateSpace.PHYSICAL_MONITOR),
        Rect(1, 1, 10, 10, CoordinateSpace.VIRTUAL_DESKTOP),
        Rect(1, 1, 10, 10, CoordinateSpace.SCREENSHOT_IMAGE),
    ]
    mapped = transform_sensitive_rectangles(cases, ctx)
    assert len(mapped) == len(cases)
    assert all(rect.space is CoordinateSpace.SCREENSHOT_IMAGE for rect in mapped)


def test_out_of_bounds_transformation_is_rejected_not_silently_dropped():
    with pytest.raises(GeometryError):
        transform_sensitive_rectangles([Rect(5000, 5000, 10, 10, CoordinateSpace.BROWSER_WINDOW)], _ctx())
