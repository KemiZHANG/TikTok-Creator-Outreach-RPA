import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Tuple

import cv2
import keyboard
import numpy as np
import pyautogui
import pyperclip


pyautogui.FAILSAFE = True

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = BASE_DIR / "logs"
IMAGES_DIR = BASE_DIR / "images"
CONFIG_PATH = BASE_DIR / "config.json"


class UserAbortException(Exception):
    """Raised when the operator presses ESC."""


class StepFailedException(Exception):
    """Raised when a critical automation step cannot be completed."""


def ensure_runtime_dirs() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    ensure_runtime_dirs()
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def check_abort() -> None:
    if keyboard.is_pressed("esc"):
        raise UserAbortException("检测到 ESC，脚本已按要求终止。")


def controlled_sleep(seconds: float, reason: str = "") -> None:
    del reason
    safe_seconds = max(0.0, float(seconds or 0.0))
    if safe_seconds <= 0:
        return

    end_time = time.time() + safe_seconds
    while True:
        remaining = max(0.0, end_time - time.time())
        if remaining <= 0:
            break
        check_abort()
        time.sleep(max(0.0, min(0.2, remaining)))


def get_log_file_path() -> Path:
    ensure_runtime_dirs()
    return LOGS_DIR / f"run_{datetime.now().strftime('%Y%m%d')}.log"


def log(message: str, level: str = "INFO", also_print: bool = True) -> None:
    ensure_runtime_dirs()
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [{level}] {message}"
    with get_log_file_path().open("a", encoding="utf-8") as file:
        file.write(line + "\n")
    if also_print:
        print(line)


def save_failure_screenshot(name_prefix: str) -> Optional[Path]:
    ensure_runtime_dirs()
    file_path = LOGS_DIR / f"{name_prefix}_{timestamp()}.png"
    try:
        screenshot = pyautogui.screenshot()
        screenshot.save(file_path)
        log(f"失败截图已保存: {file_path}", level="ERROR")
        return file_path
    except Exception as exc:
        log(f"截图保存失败: {exc}", level="ERROR")
        return None


def get_coordinate(config: dict, key: str) -> Tuple[int, int]:
    points = config.get("coords") or config.get("coordinates") or {}
    point = points[key]
    return int(point["x"]), int(point["y"])


def move_to_point(
    point: Tuple[int, int],
    duration: float,
    before_sleep: float,
    after_sleep: float,
) -> None:
    controlled_sleep(before_sleep)
    check_abort()
    pyautogui.moveTo(point[0], point[1], duration=duration)
    controlled_sleep(after_sleep)


def click_point(
    point: Tuple[int, int],
    config: dict,
    clicks: int = 1,
    interval: Optional[float] = None,
    button: str = "left",
    reason: str = "",
) -> None:
    timing = config["timing"]
    click_interval = interval if interval is not None else timing["between_clicks"]
    if reason:
        log(f"点击坐标 {point}，目标: {reason}")
    move_to_point(
        point,
        duration=timing["move_duration"],
        before_sleep=timing["before_click_sleep"],
        after_sleep=timing["after_move_sleep"],
    )
    check_abort()
    pyautogui.click(point[0], point[1], clicks=clicks, interval=click_interval, button=button)
    controlled_sleep(timing["after_click_sleep"])


def load_image_unicode(path: Path) -> Optional[np.ndarray]:
    if not path.exists():
        log(f"模板文件不存在: {path}", level="ERROR")
        return None

    try:
        image_bytes = np.fromfile(str(path), dtype=np.uint8)
    except Exception as exc:
        log(f"读取模板文件字节失败: {path} | {exc}", level="ERROR")
        return None

    if image_bytes.size == 0:
        log(f"模板文件为空或无法读取: {path}", level="ERROR")
        return None

    try:
        image = cv2.imdecode(image_bytes, cv2.IMREAD_COLOR)
    except Exception as exc:
        log(f"模板文件解码失败: {path} | {exc}", level="ERROR")
        return None

    if image is None:
        log(f"模板文件存在但 OpenCV 无法解码: {path}", level="ERROR")
        return None

    return image


def capture_screen_image(
    grayscale: bool = False,
    region: Optional[Tuple[int, int, int, int]] = None,
) -> np.ndarray:
    screenshot = pyautogui.screenshot(region=region)
    rgb_array = np.array(screenshot)
    bgr_array = cv2.cvtColor(rgb_array, cv2.COLOR_RGB2BGR)
    if grayscale:
        return cv2.cvtColor(bgr_array, cv2.COLOR_BGR2GRAY)
    return bgr_array


def locate_template(
    template_name: str,
    config: dict,
    confidence: Optional[float] = None,
    grayscale: Optional[bool] = None,
    region: Optional[Tuple[int, int, int, int]] = None,
    wait_before: Optional[float] = None,
) -> Optional[Tuple[int, int]]:
    template_path = IMAGES_DIR / template_name
    matching = config["matching"]
    wait_time = matching["pre_search_sleep"] if wait_before is None else wait_before
    use_grayscale = grayscale if grayscale is not None else matching["grayscale"]
    if confidence is not None:
        threshold = confidence
    else:
        template_stem = Path(template_name).stem
        if template_stem == "browser_crash_marker1":
            threshold = matching.get("browser_crash_reload_confidence", 0.95)
        elif template_stem.startswith("browser_crash_marker"):
            threshold = matching.get("browser_crash_confidence", 0.55)
        else:
            threshold = matching["default_confidence"]

    controlled_sleep(wait_time)
    check_abort()

    template = load_image_unicode(template_path)
    if template is None:
        return None

    if use_grayscale:
        template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

    try:
        screen_image = capture_screen_image(grayscale=use_grayscale, region=region)
    except Exception as exc:
        log(f"屏幕截图失败，无法识别模板 {template_name}: {exc}", level="ERROR")
        return None

    if screen_image.shape[0] < template.shape[0] or screen_image.shape[1] < template.shape[1]:
        log(
            f"模板尺寸大于截图区域，无法匹配: {template_name} | "
            f"template={template.shape[:2]} screen={screen_image.shape[:2]}",
            level="ERROR",
        )
        return None

    try:
        result = cv2.matchTemplate(screen_image, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
    except Exception as exc:
        log(f"OpenCV 模板匹配失败 {template_name}: {exc}", level="ERROR")
        return None

    if max_val < threshold:
        return None

    template_height, template_width = template.shape[:2]
    offset_x = region[0] if region else 0
    offset_y = region[1] if region else 0
    center_x = offset_x + max_loc[0] + template_width // 2
    center_y = offset_y + max_loc[1] + template_height // 2
    return center_x, center_y


def wait_for_template(
    template_name: str,
    config: dict,
    timeout: float,
    confidence: Optional[float] = None,
    interval: Optional[float] = None,
    description: str = "",
    region: Optional[Tuple[int, int, int, int]] = None,
    abort_checker: Optional[Callable[[], None]] = None,
) -> Optional[Tuple[int, int]]:
    matching = config["matching"]
    poll_interval = interval if interval is not None else matching["search_retry_interval"]
    end_time = time.time() + max(0.0, timeout)
    while time.time() < end_time:
        if abort_checker is not None:
            abort_checker()
        location = locate_template(
            template_name=template_name,
            config=config,
            confidence=confidence,
            region=region,
            wait_before=matching["pre_search_sleep"],
        )
        if location:
            label = description or template_name
            log(f"识别成功: {label} -> {location}")
            return location
        controlled_sleep(poll_interval)
    label = description or template_name
    log(f"等待模板超时: {label}", level="WARNING")
    return None


def click_template_or_fallback(
    template_name: str,
    fallback_key: str,
    config: dict,
    description: str,
    timeout: Optional[float] = None,
    abort_checker: Optional[Callable[[], None]] = None,
) -> Tuple[int, int]:
    timeout_value = timeout if timeout is not None else config["timeouts"]["template_wait"]
    location = wait_for_template(
        template_name=template_name,
        config=config,
        timeout=timeout_value,
        description=description,
        abort_checker=abort_checker,
    )
    if location:
        click_point(location, config, reason=f"{description}(模板)")
        return location

    fallback_point = get_coordinate(config, fallback_key)
    log(f"{description} 模板未命中或读取失败，改用后备坐标 {fallback_point}", level="WARNING")
    click_point(fallback_point, config, reason=f"{description}(后备坐标)")
    return fallback_point


def retry_step(
    action: Callable[[], bool],
    attempts: int,
    step_name: str,
    retry_sleep: float,
) -> bool:
    for attempt in range(1, attempts + 1):
        check_abort()
        log(f"{step_name} 第 {attempt}/{attempts} 次尝试")
        try:
            if action():
                log(f"{step_name} 成功")
                return True
        except UserAbortException:
            raise
        except Exception as exc:
            log(f"{step_name} 第 {attempt} 次异常: {exc}", level="ERROR")
        if attempt < attempts:
            controlled_sleep(retry_sleep)
    log(f"{step_name} 最终失败", level="ERROR")
    return False


def paste_text(text: str, config: dict) -> None:
    pyperclip.copy(text)
    controlled_sleep(config["timing"]["after_paste_sleep"])
    check_abort()
    pyautogui.hotkey("ctrl", "v")
    controlled_sleep(config["timing"]["after_paste_sleep"])


def scroll_once(config: dict, amount: int) -> None:
    area = get_coordinate(config, "scroll_area")
    log(f"准备滚动列表，滚轮值: {amount}")
    move_to_point(
        area,
        duration=config["timing"]["move_duration"],
        before_sleep=config["timing"]["before_scroll_sleep"],
        after_sleep=config["timing"]["after_move_sleep"],
    )
    check_abort()
    pyautogui.scroll(amount)
    controlled_sleep(config["timing"]["after_scroll_sleep"])


def close_creator_page(config: dict, reason: str = "") -> None:
    point = get_coordinate(config, "close_creator_page")
    click_point(point, config, reason=reason or "关闭达人详情页")
    controlled_sleep(config["timing"]["page_close_sleep"])


def recover_to_creator_list(config: dict, reason: str, creator_index: Optional[int] = None) -> None:
    prefix = f"达人 #{creator_index} " if creator_index is not None else ""
    log(f"{prefix}触发收尾返回列表: {reason}", level="WARNING")
    close_creator_page(config, reason="异常时统一关闭达人详情页")


def wait_after_page_change(config: dict, extra_seconds: float = 0.0) -> None:
    controlled_sleep(config["timing"]["after_enter_creator_wait"] + extra_seconds)


def wait_for_chat_window(
    config: dict,
    timeout: Optional[float] = None,
    abort_checker: Optional[Callable[[], None]] = None,
) -> bool:
    timeout_value = timeout if timeout is not None else config["timeouts"]["chat_window"]
    location = wait_for_template(
        template_name=config["templates"]["send_message_marker"],
        config=config,
        timeout=timeout_value,
        description="聊天输入框标记 Send a message",
        abort_checker=abort_checker,
    )
    return location is not None


def _get_active_window_title() -> str:
    try:
        window = pyautogui.getActiveWindow()
    except Exception:
        return ""
    if window is None:
        return ""
    try:
        return (window.title or "").strip()
    except Exception:
        return ""


def _looks_like_file_dialog(title: str) -> bool:
    lowered = title.lower()
    keywords = ["open", "打开", "选择", "select", "文件上传", "upload", "file"]
    return any(keyword in lowered for keyword in keywords)


def wait_for_file_dialog_ready(
    config: dict,
    abort_checker: Optional[Callable[[], None]] = None,
) -> bool:
    controlled_sleep(config["timing"]["after_open_file_dialog_wait"])
    end_time = time.time() + config["timeouts"]["file_dialog"]
    while time.time() < end_time:
        if abort_checker is not None:
            abort_checker()
        title = _get_active_window_title()
        if title and _looks_like_file_dialog(title):
            log(f"已确认文件选择窗口出现: {title}")
            return True
        controlled_sleep(config["matching"]["search_retry_interval"])
    log("未确认到文件选择窗口出现", level="WARNING")
    return False


def _is_file_dialog_closed() -> bool:
    title = _get_active_window_title()
    if not title:
        return True
    return not _looks_like_file_dialog(title)


def select_file_and_confirm_dialog_closed(
    config: dict,
    abort_checker: Optional[Callable[[], None]] = None,
) -> bool:
    image_item = get_coordinate(config, "file_image_item")
    open_button = get_coordinate(config, "file_open_button")

    if abort_checker is not None:
        abort_checker()
    click_point(image_item, config, reason="点击文件选择窗口中的图片")
    controlled_sleep(config["timing"]["after_select_file_wait"])

    if abort_checker is not None:
        abort_checker()
    click_point(open_button, config, reason="点击文件选择窗口中的打开按钮")
    controlled_sleep(config["timing"]["after_click_open_wait"])
    if abort_checker is not None:
        abort_checker()
    if _is_file_dialog_closed():
        log("已确认文件选择窗口关闭")
        return True

    log("第一次点击打开后文件窗口仍未关闭，补点一次打开按钮", level="WARNING")
    if abort_checker is not None:
        abort_checker()
    click_point(open_button, config, reason="补点文件选择窗口中的打开按钮")
    controlled_sleep(config["timing"]["after_click_open_wait"])
    if abort_checker is not None:
        abort_checker()
    if _is_file_dialog_closed():
        log("第二次点击打开后文件选择窗口已关闭")
        return True

    log("文件选择窗口未能关闭，判定本次发图失败", level="ERROR")
    return False


def confirm_ok_popup_disappeared(
    config: dict,
    abort_checker: Optional[Callable[[], None]] = None,
) -> bool:
    ok_template = config["templates"]["ok_btn"]
    ok_location = wait_for_template(
        template_name=ok_template,
        config=config,
        timeout=config["timeouts"]["optional_ok"],
        description="Send photos 确认弹窗 OK",
        abort_checker=abort_checker,
    )
    if not ok_location:
        log("未检测到 OK 弹窗，默认继续后续流程")
        return True

    if abort_checker is not None:
        abort_checker()
    click_point(ok_location, config, reason="点击 Send photos 的 OK")
    controlled_sleep(config["timing"]["after_click_ok_wait"])
    if abort_checker is not None:
        abort_checker()
    still_there = locate_template(ok_template, config, wait_before=0.0)
    if not still_there:
        log("已确认 OK 弹窗消失")
        return True

    log("点击 OK 后弹窗仍在，补点 1 次 OK", level="WARNING")
    if abort_checker is not None:
        abort_checker()
    click_point(still_there, config, reason="补点 Send photos 的 OK")
    controlled_sleep(config["timing"]["after_click_ok_wait"])
    if abort_checker is not None:
        abort_checker()
    final_check = locate_template(ok_template, config, wait_before=0.0)
    if final_check:
        log("OK 弹窗仍未消失", level="ERROR")
        return False

    log("补点后已确认 OK 弹窗消失")
    return True


def ensure_chat_input_available(
    config: dict,
    abort_checker: Optional[Callable[[], None]] = None,
) -> bool:
    return wait_for_chat_window(
        config,
        timeout=config["timeouts"]["post_send_check"],
        abort_checker=abort_checker,
    )


def record_creator_result(index: int, status: str, details: str) -> None:
    log(f"达人 #{index}: {status} | {details}")


def validate_required_templates(config: dict) -> bool:
    all_ok = True
    for template_name in config["templates"].values():
        path = IMAGES_DIR / template_name
        if not path.exists():
            log(f"模板缺失: {path}", level="ERROR")
            all_ok = False
            continue
        if load_image_unicode(path) is None:
            log(f"模板存在但无法读取: {path}", level="ERROR")
            all_ok = False
        else:
            log(f"模板检查通过: {path}")
    return all_ok
