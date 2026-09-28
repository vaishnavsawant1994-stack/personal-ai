from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

COORDINATE_SPACE_VERSION = 2


class CoordinateSpace(str, Enum):
    BROWSER_VIEWPORT = 'browser_viewport'
    BROWSER_DOCUMENT = 'browser_document'
    BROWSER_WINDOW = 'browser_window'
    PHYSICAL_MONITOR = 'physical_monitor'
    VIRTUAL_DESKTOP = 'virtual_desktop'
    SCREENSHOT_IMAGE = 'screenshot_image'


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float
    space: CoordinateSpace

    def valid(self) -> bool:
        values = (self.x, self.y, self.width, self.height)
        return all(_finite(v) for v in values) and float(self.width) > 0 and float(self.height) > 0


@dataclass(frozen=True)
class GeometryContext:
    device_pixel_ratio: float | None = None
    page_zoom: float | None = None
    viewport_width: float | None = None
    viewport_height: float | None = None
    scroll_x: float | None = None
    scroll_y: float | None = None
    browser_window_x: float | None = None
    browser_window_y: float | None = None
    browser_window_width: float | None = None
    browser_window_height: float | None = None
    content_offset_x: float | None = None
    content_offset_y: float | None = None
    monitor_x: float | None = None
    monitor_y: float | None = None
    monitor_width: float | None = None
    monitor_height: float | None = None
    monitor_scale: float | None = None
    virtual_origin_x: float | None = None
    virtual_origin_y: float | None = None
    screenshot_origin_x: float | None = None
    screenshot_origin_y: float | None = None
    screenshot_width: float | None = None
    screenshot_height: float | None = None
    capture_source: str = ''

    def as_dict(self) -> dict:
        return {key: getattr(self, key) for key in self.__dataclass_fields__}

    def validate_image(self) -> None:
        required = (self.screenshot_origin_x, self.screenshot_origin_y, self.screenshot_width, self.screenshot_height)
        if any(v is None or not _finite(v) for v in required):
            raise GeometryError('screenshot geometry is incomplete')
        if float(self.screenshot_width) <= 0 or float(self.screenshot_height) <= 0:
            raise GeometryError('screenshot dimensions are invalid')

    def validate_browser(self) -> None:
        self.validate_image()
        required = (
            self.device_pixel_ratio, self.page_zoom,
            self.browser_window_x, self.browser_window_y,
            self.content_offset_x, self.content_offset_y,
            self.monitor_scale,
        )
        if any(v is None or not _finite(v) for v in required):
            raise GeometryError('browser coordinate mapping inputs are incomplete')
        if float(self.device_pixel_ratio) <= 0 or float(self.page_zoom) <= 0 or float(self.monitor_scale) <= 0:
            raise GeometryError('browser coordinate scale is invalid')


class GeometryError(ValueError):
    pass


def _finite(value: float) -> bool:
    try:
        return float('-inf') < float(value) < float('inf')
    except Exception:
        return False


def clip_rect(rect: Rect, width: float, height: float) -> Rect | None:
    if rect.space is not CoordinateSpace.SCREENSHOT_IMAGE or not rect.valid():
        return None
    if not _finite(width) or not _finite(height) or float(width) <= 0 or float(height) <= 0:
        return None
    left = max(0.0, float(rect.x)); top = max(0.0, float(rect.y))
    right = min(float(width), float(rect.x) + float(rect.width)); bottom = min(float(height), float(rect.y) + float(rect.height))
    if right <= left or bottom <= top:
        return None
    return Rect(left, top, right-left, bottom-top, CoordinateSpace.SCREENSHOT_IMAGE)


def _browser_content_scale(context: GeometryContext) -> float:
    context.validate_browser()
    return float(context.device_pixel_ratio) * float(context.page_zoom) * float(context.monitor_scale)


def _window_scale(context: GeometryContext) -> float:
    context.validate_image()
    if context.monitor_scale is None or not _finite(context.monitor_scale) or float(context.monitor_scale) <= 0:
        raise GeometryError('monitor scale is unavailable')
    return float(context.monitor_scale)


def viewport_rect_to_screenshot(rect: Rect, context: GeometryContext) -> Rect:
    if rect.space is not CoordinateSpace.BROWSER_VIEWPORT:
        raise GeometryError('rectangle is not in browser viewport coordinates')
    if not rect.valid():
        raise GeometryError('rectangle is invalid')
    content_scale = _browser_content_scale(context)
    window_scale = _window_scale(context)
    physical_x = float(context.browser_window_x) * window_scale + (float(context.content_offset_x) + float(rect.x)) * content_scale
    physical_y = float(context.browser_window_y) * window_scale + (float(context.content_offset_y) + float(rect.y)) * content_scale
    return Rect(
        physical_x - float(context.screenshot_origin_x),
        physical_y - float(context.screenshot_origin_y),
        float(rect.width) * content_scale,
        float(rect.height) * content_scale,
        CoordinateSpace.SCREENSHOT_IMAGE,
    )


def document_rect_to_screenshot(rect: Rect, context: GeometryContext) -> Rect:
    if rect.space is not CoordinateSpace.BROWSER_DOCUMENT:
        raise GeometryError('rectangle is not in browser document coordinates')
    if context.scroll_x is None or context.scroll_y is None or not _finite(context.scroll_x) or not _finite(context.scroll_y):
        raise GeometryError('document scroll offsets are unavailable')
    viewport = Rect(
        float(rect.x) - float(context.scroll_x),
        float(rect.y) - float(context.scroll_y),
        rect.width,
        rect.height,
        CoordinateSpace.BROWSER_VIEWPORT,
    )
    return viewport_rect_to_screenshot(viewport, context)


def browser_window_rect_to_screenshot(rect: Rect, context: GeometryContext) -> Rect:
    if rect.space is not CoordinateSpace.BROWSER_WINDOW:
        raise GeometryError('rectangle is not in browser window coordinates')
    if not rect.valid():
        raise GeometryError('rectangle is invalid')
    scale = _window_scale(context)
    if context.browser_window_x is None or context.browser_window_y is None:
        raise GeometryError('browser window origin is unavailable')
    physical_x = (float(context.browser_window_x) + float(rect.x)) * scale
    physical_y = (float(context.browser_window_y) + float(rect.y)) * scale
    return Rect(
        physical_x - float(context.screenshot_origin_x),
        physical_y - float(context.screenshot_origin_y),
        float(rect.width) * scale,
        float(rect.height) * scale,
        CoordinateSpace.SCREENSHOT_IMAGE,
    )


def physical_monitor_rect_to_screenshot(rect: Rect, context: GeometryContext) -> Rect:
    if rect.space is not CoordinateSpace.PHYSICAL_MONITOR:
        raise GeometryError('rectangle is not in physical monitor coordinates')
    if not rect.valid():
        raise GeometryError('rectangle is invalid')
    context.validate_image()
    if context.monitor_x is None or context.monitor_y is None:
        raise GeometryError('monitor origin is unavailable')
    return Rect(
        float(context.monitor_x) + float(rect.x) - float(context.screenshot_origin_x),
        float(context.monitor_y) + float(rect.y) - float(context.screenshot_origin_y),
        float(rect.width),
        float(rect.height),
        CoordinateSpace.SCREENSHOT_IMAGE,
    )


def virtual_desktop_rect_to_screenshot(rect: Rect, context: GeometryContext) -> Rect:
    if rect.space is not CoordinateSpace.VIRTUAL_DESKTOP:
        raise GeometryError('rectangle is not in virtual desktop coordinates')
    if not rect.valid():
        raise GeometryError('rectangle is invalid')
    context.validate_image()
    if context.virtual_origin_x is None or context.virtual_origin_y is None:
        raise GeometryError('virtual desktop origin is unavailable')
    absolute_x = float(context.virtual_origin_x) + float(rect.x)
    absolute_y = float(context.virtual_origin_y) + float(rect.y)
    return Rect(
        absolute_x - float(context.screenshot_origin_x),
        absolute_y - float(context.screenshot_origin_y),
        float(rect.width),
        float(rect.height),
        CoordinateSpace.SCREENSHOT_IMAGE,
    )


def transform_sensitive_rectangles(rectangles: Iterable[Rect], context: GeometryContext) -> list[Rect]:
    context.validate_image()
    transformed: list[Rect] = []
    for rect in rectangles:
        if rect.space is CoordinateSpace.BROWSER_VIEWPORT:
            mapped = viewport_rect_to_screenshot(rect, context)
        elif rect.space is CoordinateSpace.BROWSER_DOCUMENT:
            mapped = document_rect_to_screenshot(rect, context)
        elif rect.space is CoordinateSpace.BROWSER_WINDOW:
            mapped = browser_window_rect_to_screenshot(rect, context)
        elif rect.space is CoordinateSpace.PHYSICAL_MONITOR:
            mapped = physical_monitor_rect_to_screenshot(rect, context)
        elif rect.space is CoordinateSpace.VIRTUAL_DESKTOP:
            mapped = virtual_desktop_rect_to_screenshot(rect, context)
        elif rect.space is CoordinateSpace.SCREENSHOT_IMAGE:
            mapped = rect
        else:
            raise GeometryError(f'unsupported redaction coordinate space: {rect.space.value}')
        clipped = clip_rect(mapped, float(context.screenshot_width), float(context.screenshot_height))
        if clipped is None:
            raise GeometryError('redaction rectangle is outside screenshot bounds')
        transformed.append(clipped)
    return transformed
