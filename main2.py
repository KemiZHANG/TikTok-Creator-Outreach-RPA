import re
import time
from typing import Dict

import pyautogui

from contact_export import append_contact_if_new, extract_contacts, init_contact_db
from creator_db import (
    add_processed_creator,
    clear_processed_creators,
    init_processed_creators_db,
    is_creator_processed,
)
from main import (
    open_chat_window,
    open_creator_detail,
    prepare_next_creator,
    run_startup_checks,
    send_photo,
    send_text_message,
)
from ocr_utils import (
    ensure_ocr_engine_ready,
    read_contact_text_from_page,
    read_crash_text_from_screen,
    read_creator_name_from_page,
)
from utils import (
    IMAGES_DIR,
    StepFailedException,
    UserAbortException,
    capture_screen_image,
    check_abort,
    click_point,
    click_template_or_fallback,
    controlled_sleep,
    get_coordinate,
    load_config,
    load_image_unicode,
    locate_template,
    log,
    paste_text,
    record_creator_result,
    recover_to_creator_list,
    save_failure_screenshot,
    scroll_once,
    wait_for_template,
)


class BrowserCrashDetected(Exception):
    """Raised when Chrome's crash page is detected."""


class BrowserRecoveryLoopExceeded(Exception):
    """Raised when crash recovery keeps triggering without making progress."""


_LAST_DIRECT_CRASH_OCR_AT = 0.0
_LAST_CRASH_CHECK_AT = 0.0
_LAST_CRASH_CHECK_RESULT = False


def _remember_crash_detection(result: bool) -> bool:
    global _LAST_CRASH_CHECK_AT, _LAST_CRASH_CHECK_RESULT
    _LAST_CRASH_CHECK_AT = time.monotonic()
    _LAST_CRASH_CHECK_RESULT = result
    return result


def ask_yes_no(prompt: str) -> bool:
    while True:
        answer = input(prompt).strip().lower()
        if answer in {"是", "y", "yes"}:
            return True
        if answer in {"否", "n", "no"}:
            return False
        print("请输入 是/否，或 y/n")


def get_runtime_inputs() -> Dict[str, int | str | bool]:
    print("TikTok_BD_Auto main2 去重版启动")
    print("请确保当前页面已经停留在 TikTok Shop Affiliate Centre 的 Find creators 页面。")
    print("main2 保留达人昵称去重、可选联系方式采集，并新增多次崩溃恢复。")

    clear_db = ask_yes_no("是否清理达人去重数据库（是/否）: ")
    collect_contacts = ask_yes_no("是否抓取邮箱与商务电话（是/否）: ")
    use_recovery_filter = ask_yes_no("崩溃恢复后是否应用 Product category 筛选（是/否）: ")
    recovery_category = ""
    if use_recovery_filter:
        recovery_category = input("请输入崩溃恢复后 Product category 类目名称: ").strip()

    message_text = input("请输入本次私聊文案: ").strip()
    scroll_distance = int(input("请输入本次滚轮距离: ").strip())
    total_creators = int(input("请输入本次总运行人数: ").strip())

    return {
        "clear_db": clear_db,
        "collect_contacts": collect_contacts,
        "use_recovery_filter": use_recovery_filter,
        "recovery_category": recovery_category,
        "message_text": message_text,
        "scroll_distance": scroll_distance,
        "total_creators": total_creators,
    }


def _get_template_match_score(template_name: str, config: dict) -> float:
    """直接返回 OpenCV 匹配分数（不判断阈值），用于调试日志。"""
    from pathlib import Path
    import cv2

    del Path
    template_path = IMAGES_DIR / template_name
    matching = config["matching"]
    use_grayscale = matching["grayscale"]

    template = load_image_unicode(template_path)
    if template is None:
        return 0.0
    if use_grayscale:
        template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

    try:
        screen_image = capture_screen_image(grayscale=use_grayscale, region=None)
    except Exception:
        return 0.0

    if screen_image.shape[0] < template.shape[0] or screen_image.shape[1] < template.shape[1]:
        return 0.0

    try:
        result = cv2.matchTemplate(screen_image, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        return float(max_val)
    except Exception:
        return 0.0


def _get_template_name(config: dict, template_key: str) -> str:
    return str(config.get("templates", {}).get(template_key, "")).strip()


def _locate_optional_template(
    config: dict,
    template_key: str,
    *,
    confidence: float | None = None,
    wait_before: float = 0.0,
):
    template_name = _get_template_name(config, template_key)
    if not template_name:
        return None
    if not (IMAGES_DIR / template_name).exists():
        log(f"模板未配置或不存在，跳过识别: {template_key} -> {template_name}", level="WARNING", also_print=False)
        return None
    return locate_template(
        template_name=template_name,
        config=config,
        confidence=confidence,
        wait_before=wait_before,
    )


def _crash_ocr_confirms(config: dict) -> bool:
    text = read_crash_text_from_screen(config)
    if not text:
        return False

    normalized_text = re.sub(r"\s+", "", text).lower()
    keywords = config.get("ocr", {}).get("crash_keywords", ["重新加载", "崩溃", "错误代码", "reload"])
    for keyword in keywords:
        normalized_keyword = re.sub(r"\s+", "", str(keyword)).lower()
        if normalized_keyword and normalized_keyword in normalized_text:
            log(f"崩溃页 OCR 兜底确认成功，命中关键词: {keyword}")
            return True

    if bool(config.get("ocr", {}).get("crash_log_full_text", False)):
        log(f"崩溃页 OCR 已执行，但未命中关键词，原始文本: {text!r}", also_print=False)
    else:
        preview = re.sub(r"\s+", " ", text).strip()
        log(f"崩溃页 OCR 已执行，但未命中关键词，文本预览: {preview[:220]!r}", also_print=False)
    return False


def _direct_crash_ocr_confirms(config: dict) -> bool:
    """
    模板完全不命中时的低频 OCR 兜底。

    这一步专门处理“无法打开此网页”这类模板不像原崩溃图的页面。
    冷却期内只跳过昂贵 OCR，不复用上一次 True，避免恢复后误判。
    """
    global _LAST_DIRECT_CRASH_OCR_AT

    ocr_config = config.get("ocr", {})
    if not bool(ocr_config.get("crash_direct_ocr_enabled", True)):
        return False

    now = time.monotonic()
    cooldown = max(0.0, float(ocr_config.get("crash_direct_ocr_cooldown", 12.0)))
    if now - _LAST_DIRECT_CRASH_OCR_AT < cooldown:
        return False

    _LAST_DIRECT_CRASH_OCR_AT = now
    log("崩溃模板未命中，执行低频 OCR 兜底确认", also_print=False)
    return _crash_ocr_confirms(config)


def detect_browser_crash(config: dict) -> bool:
    """
    崩溃判断逻辑：
    - 找到 find_creators_marker → 正常（Find Creators 列表页）→ 不崩溃
    - 找到 browser_crash_marker1 → 崩溃页专属“重新加载”按钮 → 崩溃
    - 找到 browser_crash_marker → 崩溃（"喔唷，崩溃啦"错误页）→ 崩溃
    - 两者都找不到 → 不崩溃（交给后续步骤自行处理异常，不触发崩溃恢复）

    reload_btn 按钮在正常页面和崩溃页上同时存在，不能作为崩溃判断依据，
    仅在崩溃恢复时作为点击目标使用。
    """
    matching = config["matching"]
    now = time.monotonic()
    cache_seconds = max(0.0, float(matching.get("crash_negative_cache_seconds", 0.0)))
    if (
        cache_seconds > 0
        and not _LAST_CRASH_CHECK_RESULT
        and now - _LAST_CRASH_CHECK_AT < cache_seconds
    ):
        return False

    crash_confidence = float(matching.get("browser_crash_confidence", 0.55))
    crash_reload_confidence = float(matching.get("browser_crash_reload_confidence", 0.95))

    if bool(matching.get("crash_debug_scores", False)):
        fc_score = _get_template_match_score(_get_template_name(config, "find_creators_marker"), config)
        crash_score = _get_template_match_score(_get_template_name(config, "browser_crash_marker"), config)
        crash_full_score = _get_template_match_score(_get_template_name(config, "browser_crash_marker_full"), config)
        crash_reload_score = _get_template_match_score(_get_template_name(config, "browser_crash_marker1"), config)
        log(
            f"[CrashDetect] find_creators_marker 匹配分数={fc_score:.3f} "
            f"(阈值={matching['default_confidence']}), "
            f"browser_crash_marker 匹配分数={crash_score:.3f}, "
            f"browser_crash_marker_full 匹配分数={crash_full_score:.3f}, "
            f"browser_crash_marker1 匹配分数={crash_reload_score:.3f} "
            f"(按钮阈值={crash_reload_confidence}, 崩溃页阈值={crash_confidence})",
            also_print=False,
        )

    if bool(matching.get("crash_check_find_creators_first", False)):
        find_creators = _locate_optional_template(
            config=config,
            template_key="find_creators_marker",
            wait_before=0.0,
        )
        if find_creators is not None:
            return _remember_crash_detection(False)

    # 这个是崩溃页内的“重新加载”按钮，正常页面不会出现；命中即认为崩溃。
    crash_reload_marker = _locate_optional_template(
        config=config,
        template_key="browser_crash_marker1",
        confidence=crash_reload_confidence,
        wait_before=0.0,
    )
    if crash_reload_marker is not None:
        log("检测到浏览器崩溃页面，命中模板: browser_crash_marker1", level="WARNING")
        return _remember_crash_detection(True)

    crash_marker = _locate_optional_template(
        config=config,
        template_key="browser_crash_marker",
        confidence=crash_confidence,
        wait_before=0.0,
    )
    if crash_marker is not None:
        log("检测到浏览器崩溃页面，命中模板: browser_crash_marker", level="WARNING")
        return _remember_crash_detection(True)

    crash_full_marker = _locate_optional_template(
        config=config,
        template_key="browser_crash_marker_full",
        confidence=crash_confidence,
        wait_before=0.0,
    )
    if crash_full_marker is not None:
        log("检测到浏览器崩溃页面，命中模板: browser_crash_marker_full", level="WARNING")
        return _remember_crash_detection(True)

    if bool(matching.get("crash_candidate_ocr_enabled", False)):
        ocr_reload_candidate_confidence = float(matching.get("browser_crash_ocr_candidate_confidence", 0.72))
        ocr_marker_candidate_confidence = float(matching.get("browser_crash_marker_ocr_candidate_confidence", 0.42))
        crash_score = _get_template_match_score(_get_template_name(config, "browser_crash_marker"), config)
        crash_full_score = _get_template_match_score(_get_template_name(config, "browser_crash_marker_full"), config)
        crash_reload_score = _get_template_match_score(_get_template_name(config, "browser_crash_marker1"), config)
        likely_crash_candidate = (
            crash_reload_score >= ocr_reload_candidate_confidence
            or crash_score >= ocr_marker_candidate_confidence
            or crash_full_score >= ocr_marker_candidate_confidence
        )
        if likely_crash_candidate and _crash_ocr_confirms(config):
            log("检测到浏览器崩溃页面，命中方式: 模板候选 + OCR 文字兜底", level="WARNING")
            return _remember_crash_detection(True)

    if _direct_crash_ocr_confirms(config):
        log("检测到浏览器崩溃页面，命中方式: 直接 OCR 文字兜底", level="WARNING")
        return _remember_crash_detection(True)

    return _remember_crash_detection(False)


def raise_if_browser_crashed(config: dict) -> None:
    if detect_browser_crash(config):
        raise BrowserCrashDetected("检测到浏览器崩溃页面")


def apply_recovery_filter(config: dict, category_name: str) -> None:
    category_name = (category_name or "").strip()
    if not category_name:
        log("未设置恢复筛选类目，跳过 Product category 重建")
        return

    log(f"开始恢复 Product category 筛选: {category_name}")
    click_point(get_coordinate(config, "product_category_dropdown"), config, reason="打开 Product category 下拉框")
    controlled_sleep(config["timing"]["after_filter_dropdown_wait"])

    click_point(get_coordinate(config, "product_category_search"), config, reason="点击 Product category 搜索框")
    paste_text(category_name, config)
    controlled_sleep(config["timing"]["after_filter_search_wait"])

    click_point(get_coordinate(config, "product_category_first_result"), config, reason="点击 Product category 搜索结果第一项")
    controlled_sleep(config["timing"]["after_filter_select_wait"])

    click_point(get_coordinate(config, "filter_blank_area"), config, reason="点击空白处收起筛选栏")
    controlled_sleep(config["timing"]["after_filter_collapse_wait"])
    log(f"Product category 恢复筛选完成: {category_name}")


def restore_scroll_position(config: dict, scroll_distance: int, completed_count: int) -> None:
    if completed_count <= 0:
        log("累计完成轮数为 0，无需恢复滚动位置")
        return

    log(f"开始按累计完成轮数恢复滚动位置: {completed_count} 次")
    for step in range(1, completed_count + 1):
        check_abort()
        scroll_once(config, scroll_distance)
        controlled_sleep(config["timing"]["restore_scroll_interval"])
        if step % 10 == 0 or step == completed_count:
            log(f"恢复滚动进度: {step}/{completed_count}")


def confirm_creator_detail_open(config: dict) -> None:
    """确认已经进入 Creator details；私聊按钮是当前最可靠的详情页标志。"""
    private_chat_template = _get_template_name(config, "private_chat_btn")
    if not private_chat_template:
        return

    marker = wait_for_template(
        template_name=private_chat_template,
        config=config,
        timeout=float(config["timeouts"].get("creator_detail_confirm", config["timeouts"]["template_wait"])),
        description="达人详情页私聊按钮 private_chat_btn",
    )
    if not marker:
        raise StepFailedException("点击达人坐标后未识别到私聊按钮，判定未进入达人详情页。")


def detect_recovery_page_state(config: dict) -> str:
    """
    刷新后的页面状态判断：
    - detail: 刷新回到 Creator details，可继续当前达人
    - list: 刷新回到 Find creators，需要筛选并恢复滚动
    - "": 暂未确认
    """
    detail_marker = _locate_optional_template(
        config=config,
        template_key="private_chat_btn",
        wait_before=0.0,
    )
    if detail_marker is not None:
        log("刷新后确认回到 Creator details 页面，命中模板: private_chat_btn")
        return "detail"

    optional_detail_marker = _locate_optional_template(
        config=config,
        template_key="creator_detail_marker",
        wait_before=0.0,
    )
    if optional_detail_marker is not None:
        log("刷新后确认回到 Creator details 页面，命中模板: creator_detail_marker")
        return "detail"

    list_marker = _locate_optional_template(
        config=config,
        template_key="find_creators_marker",
        wait_before=0.0,
    )
    if list_marker is not None:
        log("刷新后确认回到 Find creators 列表页")
        return "list"

    return ""


def wait_for_recovery_page_state(config: dict, timeout: float, interval: float) -> str:
    end_time = time.time() + max(0.0, timeout)
    attempt = 1
    while time.time() < end_time:
        check_abort()
        state = detect_recovery_page_state(config)
        if state:
            return state
        log(f"刷新后页面状态未确认，继续等待 {attempt}", also_print=False)
        attempt += 1
        controlled_sleep(interval)
    return ""


def recover_from_browser_crash(config: dict, runtime_inputs: dict, completed_count: int) -> str:
    log(f"开始浏览器崩溃恢复，累计已完成轮数: {completed_count}", level="WARNING")
    save_failure_screenshot("browser_crash_detected")

    try:
        clicked_reload = False
        crash_reload_template = _get_template_name(config, "browser_crash_marker1")
        if crash_reload_template and (IMAGES_DIR / crash_reload_template).exists():
            crash_reload_location = wait_for_template(
                template_name=crash_reload_template,
                config=config,
                confidence=float(config["matching"].get("browser_crash_reload_confidence", 0.95)),
                timeout=config["timeouts"]["recovery_template_wait"],
                description="浏览器崩溃页重新加载按钮(browser_crash_marker1)",
            )
            if crash_reload_location:
                click_point(crash_reload_location, config, reason="浏览器崩溃页重新加载按钮(browser_crash_marker1模板)")
                clicked_reload = True

        if not clicked_reload:
            click_template_or_fallback(
                template_name=config["templates"]["reload_btn"],
                fallback_key="browser_reload_button",
                config=config,
                description="浏览器刷新按钮 reload_btn",
                timeout=config["timeouts"]["recovery_template_wait"],
            )
        controlled_sleep(config["timing"]["after_crash_reload_wait"])

        page_state = wait_for_recovery_page_state(
            config=config,
            timeout=float(config["timeouts"]["find_creators_after_reload"]),
            interval=float(config["matching"]["search_retry_interval"]),
        )
        if not page_state:
            log("刷新后未确认回到 Find creators 或 Creator details 页面，本次恢复失败", level="ERROR")
            save_failure_screenshot("browser_crash_recovery_failed")
            return ""

        if page_state == "detail":
            log("浏览器崩溃恢复完成：当前位于 Creator details，将继续当前达人流程")
            return "detail"

        if bool(runtime_inputs["use_recovery_filter"]):
            apply_recovery_filter(config, str(runtime_inputs["recovery_category"]))

        restore_scroll_position(config, int(runtime_inputs["scroll_distance"]), completed_count)
        controlled_sleep(config["timing"]["after_filter_collapse_wait"])
        log("浏览器崩溃恢复完成：当前位于 Find creators 列表页，将继续后续达人流程")
        return "list"
    except UserAbortException:
        raise
    except Exception as exc:
        log(f"浏览器崩溃恢复异常: {exc}", level="ERROR")
        save_failure_screenshot("browser_crash_recovery_exception")
        return ""


def prepare_next_creator_with_crash_check(runtime_inputs: dict, config: dict) -> None:
    """Move to the next creator while checking the crash page around the scroll step."""
    raise_if_browser_crashed(config)
    prepare_next_creator(runtime_inputs, config)
    raise_if_browser_crashed(config)


def read_creator_name_or_fail(config: dict) -> str:
    raise_if_browser_crashed(config)
    creator_name = read_creator_name_from_page(config)
    raise_if_browser_crashed(config)
    if not creator_name:
        raise StepFailedException("OCR 未读取到达人名称，为避免重复发送，跳过当前达人。")
    return creator_name


def collect_contact_to_excel(index: int, creator_name: str, config: dict, enabled: bool) -> None:
    if not enabled:
        log(f"本次运行未启用邮箱/商务电话采集，跳过达人 #{index}: {creator_name}")
        return

    raise_if_browser_crashed(config)
    contact_text = read_contact_text_from_page(config)
    raise_if_browser_crashed(config)
    emails, phones = extract_contacts(contact_text)

    if emails or phones:
        append_contact_if_new(creator_name, emails, phones)
        log(f"达人 #{index} 已提取联系方式: emails={emails}, phones={phones}")
        return

    log(f"达人 #{index} 未提取到邮箱或商务电话，不写入联系方式数据库和 Excel: {creator_name}")


def process_one_creator_with_db(
    index: int,
    runtime_inputs: dict,
    config: dict,
    *,
    already_on_detail: bool = False,
) -> None:
    log(f"开始处理达人 #{index}（main2 去重版）")
    creator_name = ""

    try:
        check_abort()
        raise_if_browser_crashed(config)
        if already_on_detail:
            log(f"从崩溃恢复后的 Creator details 页面继续达人 #{index}，跳过打开达人详情页步骤")
        else:
            open_creator_detail(config)
        raise_if_browser_crashed(config)
        confirm_creator_detail_open(config)

        creator_name = read_creator_name_or_fail(config)
        creator_already_processed = is_creator_processed(creator_name)

        if creator_already_processed:
            log(f"达人 #{index} 已在达人昵称数据库中，但仍会先按开关决定是否采集联系方式: {creator_name}", level="WARNING")
            record_creator_result(index, "SKIPPED", f"达人昵称数据库已有记录: {creator_name}")
        else:
            log(f"达人 #{index} 达人昵称数据库未命中，继续发送流程: {creator_name}")

        collect_contact_to_excel(index, creator_name, config, bool(runtime_inputs["collect_contacts"]))

        if creator_already_processed:
            return

        raise_if_browser_crashed(config)
        if not open_chat_window(config, abort_checker=lambda: raise_if_browser_crashed(config)):
            raise StepFailedException("连续 3 次点击私聊按钮后，仍未识别到 Send a message。")

        raise_if_browser_crashed(config)
        if not send_photo(config, abort_checker=lambda: raise_if_browser_crashed(config)):
            raise StepFailedException("发送图片流程未能稳定完成。")

        raise_if_browser_crashed(config)
        if not send_text_message(
            config,
            str(runtime_inputs["message_text"]),
            abort_checker=lambda: raise_if_browser_crashed(config),
        ):
            raise StepFailedException("发送文本流程未能稳定完成。")

        add_processed_creator(creator_name)
        record_creator_result(index, "SUCCESS", f"已完成发送并写入达人昵称数据库: {creator_name}")
    except UserAbortException:
        raise
    except BrowserCrashDetected:
        raise
    except Exception as exc:
        save_failure_screenshot(f"creator_{index}_main2_failed")
        record_creator_result(index, "FAILED", str(exc))
    finally:
        if detect_browser_crash(config):
            log("finally 块检测到崩溃页面，直接抛出异常交由主循环处理", level="WARNING")
            # 崩溃页面没有可点击的达人详情关闭按钮，直接交给主循环刷新恢复。
            raise BrowserCrashDetected("finally 块崩溃检测触发")
        try:
            recover_to_creator_list(config, reason="main2 当前达人流程结束或异常", creator_index=index)
        except UserAbortException:
            raise
        except Exception as close_exc:
            save_failure_screenshot(f"creator_{index}_main2_close_failed")
            log(f"关闭达人页面时出现异常: {close_exc}", level="ERROR")


def main() -> None:
    config = load_config()
    runtime_inputs = get_runtime_inputs()

    init_processed_creators_db()
    init_contact_db()

    if bool(runtime_inputs["clear_db"]):
        clear_processed_creators()

    run_startup_checks(config)
    if not ensure_ocr_engine_ready(config):
        print("OCR 引擎不可用，main2 已停止。请先安装 Tesseract OCR 或配置 tesseract_cmd。")
        return

    log("TikTok_BD_Auto main2 去重版主流程开始")
    log(
        "本次运行参数: "
        f"是否清理达人昵称数据库={runtime_inputs['clear_db']}, "
        f"是否采集联系方式={runtime_inputs['collect_contacts']}, "
        f"崩溃恢复筛选={runtime_inputs['use_recovery_filter']}, "
        f"恢复类目={runtime_inputs['recovery_category']}, "
        f"总人数={runtime_inputs['total_creators']}, "
        f"滚轮值={runtime_inputs['scroll_distance']}, "
        f"文案长度={len(str(runtime_inputs['message_text']))}"
    )
    print("5 秒后开始，请切回浏览器并保持 Find creators 页面在最前面。")

    try:
        controlled_sleep(5)
        check_abort()
        pyautogui.PAUSE = config["timing"]["pyautogui_pause"]

        total_creators = int(runtime_inputs["total_creators"])
        completed_count = 0
        repeated_recovery_count = 0
        current_index = 0
        resume_current_detail = False

        while completed_count < total_creators:
            if not resume_current_detail:
                current_index = completed_count + 1
            current_round_counted = False

            try:
                raise_if_browser_crashed(config)
                process_one_creator_with_db(
                    current_index,
                    runtime_inputs,
                    config,
                    already_on_detail=resume_current_detail,
                )
                resume_current_detail = False
                completed_count += 1
                current_round_counted = True
                repeated_recovery_count = 0

                if completed_count < total_creators:
                    prepare_next_creator_with_crash_check(runtime_inputs, config)
            except BrowserCrashDetected as exc:
                log(f"主循环检测到浏览器崩溃: {exc}", level="ERROR")
                repeated_recovery_count += 1
                recovered = recover_from_browser_crash(config, runtime_inputs, completed_count)
                if not recovered:
                    log("浏览器崩溃恢复失败，停止本次运行", level="ERROR")
                    break
                if recovered == "detail":
                    if current_round_counted:
                        log(
                            "崩溃恢复回到 Creator details，但当前达人已计入完成数；"
                            "为避免重复发送，先关闭详情页再回列表继续。",
                            level="WARNING",
                        )
                        recover_to_creator_list(
                            config,
                            reason="当前达人已完成后恢复到详情页，避免重复发送",
                            creator_index=current_index,
                        )
                        current_index = completed_count
                        resume_current_detail = False
                    else:
                        log(f"崩溃恢复回到 Creator details，下一轮继续当前达人 #{current_index}")
                        resume_current_detail = True
                else:
                    current_index = completed_count
                    resume_current_detail = False
                if repeated_recovery_count >= 3:
                    raise BrowserRecoveryLoopExceeded(
                        "连续 3 次触发崩溃恢复但仍未进入正常达人流程，请检查 browser_crash_marker*.png 是否误匹配正常页面。"
                    )

        log(f"main2 去重版运行结束，累计完成轮数: {completed_count}/{total_creators}")
        print("运行结束。请查看 logs 文件夹、OCR 调试截图、contact_leads.db 和 leads_contacts.xlsx。")
    except UserAbortException as exc:
        log(str(exc), level="WARNING")
        save_failure_screenshot("manual_abort_main2")
        print(str(exc))
    except BrowserRecoveryLoopExceeded as exc:
        log(str(exc), level="ERROR")
        save_failure_screenshot("browser_recovery_loop_exceeded")
        print(str(exc))


if __name__ == "__main__":
    main()
