import re
import shutil
from pathlib import Path
from typing import Tuple

import pyautogui
from PIL import ImageEnhance, ImageFilter, ImageOps

from utils import LOGS_DIR, controlled_sleep, log, timestamp


try:
    import pytesseract
except ImportError:
    pytesseract = None


def _get_region(config: dict, region_key: str) -> Tuple[int, int, int, int]:
    region = config["ocr"][region_key]
    return (
        int(region["x"]),
        int(region["y"]),
        int(region["width"]),
        int(region["height"]),
    )


def _prepare_ocr_image(image, scale: int):
    resized = image.resize((image.width * scale, image.height * scale))
    gray = ImageOps.grayscale(resized)
    gray = ImageEnhance.Contrast(gray).enhance(2.0)
    gray = gray.filter(ImageFilter.SHARPEN)
    return gray


def _clean_creator_name(raw_text: str) -> str:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        return ""
    first_line = re.sub(r"\s+", " ", lines[0]).strip()
    return first_line.strip("|[]{}()")


def ensure_ocr_engine_ready(config: dict) -> bool:
    if pytesseract is None:
        log("未安装 pytesseract，无法 OCR 读取页面文字。请先执行: pip install pytesseract", level="ERROR")
        return False

    ocr_config = config.get("ocr", {})
    tesseract_cmd = (ocr_config.get("tesseract_cmd") or "").strip()
    if tesseract_cmd:
        tesseract_path = Path(tesseract_cmd)
        if not tesseract_path.exists():
            log(f"config.json 中配置的 tesseract_cmd 不存在: {tesseract_cmd}", level="ERROR")
            return False
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        log(f"OCR 引擎路径检查通过: {tesseract_cmd}")
        return True

    detected = shutil.which("tesseract")
    if detected:
        log(f"OCR 引擎已在 PATH 中可用: {detected}")
        return True

    log(
        "未找到 tesseract.exe。请先安装 Tesseract OCR，或在 config.json 的 "
        "ocr.tesseract_cmd 中填写完整路径，例如 C:\\Program Files\\Tesseract-OCR\\tesseract.exe",
        level="ERROR",
    )
    return False


def read_ocr_text_from_region(config: dict, region_key: str, debug_prefix: str, psm: int) -> str:
    if pytesseract is None:
        log("未安装 pytesseract，无法 OCR 读取页面文字。", level="ERROR")
        return ""

    ocr_config = config.get("ocr", {})
    tesseract_cmd = (ocr_config.get("tesseract_cmd") or "").strip()
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    region = _get_region(config, region_key)
    controlled_sleep(float(ocr_config.get("before_read_sleep", 0.8)))

    try:
        screenshot = pyautogui.screenshot(region=region)
    except Exception as exc:
        log(f"OCR 截取区域失败 {region_key}: {exc}", level="ERROR")
        return ""

    scale = int(ocr_config.get("scale", 3))
    image_for_ocr = _prepare_ocr_image(screenshot, scale=max(1, scale))

    if bool(ocr_config.get("debug_save", True)):
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        debug_path = LOGS_DIR / f"{debug_prefix}_{timestamp()}.png"
        try:
            image_for_ocr.save(debug_path)
            log(f"OCR 调试截图已保存: {debug_path}")
        except Exception as exc:
            log(f"OCR 调试截图保存失败: {exc}", level="WARNING")

    lang = ocr_config.get("lang", "eng")
    extra_config = f"--psm {psm}"

    try:
        return pytesseract.image_to_string(image_for_ocr, lang=lang, config=extra_config).strip()
    except Exception as exc:
        log("OCR 识别失败，请检查 Tesseract OCR 是否已安装并正确配置。", level="ERROR")
        log(f"OCR 原始异常: {exc}", level="ERROR")
        return ""


def _available_ocr_languages(config: dict) -> set:
    if pytesseract is None:
        return set()

    ocr_config = config.get("ocr", {})
    tesseract_cmd = (ocr_config.get("tesseract_cmd") or "").strip()
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    try:
        return set(pytesseract.get_languages(config=""))
    except Exception as exc:
        log(f"读取 Tesseract 语言包列表失败: {exc}", level="WARNING", also_print=False)
        return set()


def read_crash_text_from_screen(config: dict) -> str:
    """OCR 读取当前屏幕，用于崩溃页模板分数可疑时的兜底确认。"""
    if pytesseract is None:
        log("未安装 pytesseract，跳过崩溃页 OCR 兜底。", level="WARNING", also_print=False)
        return ""

    ocr_config = config.get("ocr", {})
    if not bool(ocr_config.get("crash_ocr_enabled", True)):
        return ""

    crash_lang = str(ocr_config.get("crash_lang", "chi_sim+eng")).strip() or "chi_sim+eng"
    required_langs = [lang for lang in re.split(r"[+\s]+", crash_lang) if lang]
    available_langs = _available_ocr_languages(config)
    missing_langs = [lang for lang in required_langs if lang not in available_langs]
    if missing_langs:
        log(
            f"崩溃页 OCR 兜底已跳过，缺少 Tesseract 语言包: {missing_langs}。"
            "如需识别“重新加载”等中文，请安装 chi_sim.traineddata。",
            level="WARNING",
            also_print=False,
        )
        return ""

    try:
        crash_region = ocr_config.get("crash_region")
        if crash_region and int(crash_region.get("width", 0)) > 0 and int(crash_region.get("height", 0)) > 0:
            region = (
                int(crash_region["x"]),
                int(crash_region["y"]),
                int(crash_region["width"]),
                int(crash_region["height"]),
            )
            screenshot = pyautogui.screenshot(region=region)
        else:
            screenshot = pyautogui.screenshot()
    except Exception as exc:
        log(f"崩溃页 OCR 截屏失败: {exc}", level="WARNING", also_print=False)
        return ""

    scale = int(ocr_config.get("crash_scale", 2))
    psm = int(ocr_config.get("crash_psm", 6))
    image_for_ocr = _prepare_ocr_image(screenshot, scale=max(1, scale))

    if bool(ocr_config.get("crash_debug_save", False)):
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        debug_path = LOGS_DIR / f"ocr_browser_crash_{timestamp()}.png"
        try:
            image_for_ocr.save(debug_path)
            log(f"崩溃页 OCR 调试截图已保存: {debug_path}", also_print=False)
        except Exception as exc:
            log(f"崩溃页 OCR 调试截图保存失败: {exc}", level="WARNING", also_print=False)

    try:
        return pytesseract.image_to_string(
            image_for_ocr,
            lang=crash_lang,
            config=f"--psm {psm}",
        ).strip()
    except Exception as exc:
        log(f"崩溃页 OCR 识别失败: {exc}", level="WARNING", also_print=False)
        return ""


def read_creator_name_from_page(config: dict) -> str:
    psm = int(config.get("ocr", {}).get("psm", 7))
    raw_text = read_ocr_text_from_region(config, "creator_name_region", "ocr_creator_name", psm)
    creator_name = _clean_creator_name(raw_text)
    if creator_name:
        log(f"OCR 识别到达人名称: {creator_name}")
    else:
        log(f"OCR 未识别到有效达人名称，原始结果: {raw_text!r}", level="WARNING")
    return creator_name


def read_contact_text_from_page(config: dict) -> str:
    psm = int(config.get("ocr", {}).get("contact_psm", 6))
    raw_text = read_ocr_text_from_region(config, "contact_region", "ocr_contact_region", psm)
    if raw_text:
        log(f"OCR 识别到简介/联系方式文本: {raw_text!r}")
    else:
        log("OCR 未识别到简介/联系方式文本", level="WARNING")
    return raw_text
