from typing import Callable, Dict, Optional

import pyautogui

from auth_client import AuthorizationError, enforce_authorization
from utils import (
    StepFailedException,
    UserAbortException,
    check_abort,
    click_point,
    click_template_or_fallback,
    confirm_ok_popup_disappeared,
    controlled_sleep,
    ensure_chat_input_available,
    get_coordinate,
    load_config,
    log,
    paste_text,
    record_creator_result,
    recover_to_creator_list,
    retry_step,
    save_failure_screenshot,
    scroll_once,
    select_file_and_confirm_dialog_closed,
    validate_required_templates,
    wait_after_page_change,
    wait_for_chat_window,
    wait_for_file_dialog_ready,
)


def get_runtime_inputs() -> Dict[str, int | str]:
    print("TikTok_BD_Auto 主流程启动")
    print("请确保当前页面已经停留在 TikTok Shop Affiliate Centre 的 Find creators 页面。")
    print("当前版本是在稳定版基础上做的小幅提速，仍保留关键动作双重确认。")
    message_text = input("请输入本次私聊文案: ").strip()
    scroll_distance = int(input("请输入本次滚轮距离: ").strip())
    total_creators = int(input("请输入本次总运行人数: ").strip())
    return {
        "message_text": message_text,
        "scroll_distance": scroll_distance,
        "total_creators": total_creators,
    }


def open_creator_detail(config: dict) -> None:
    point = get_coordinate(config, "creator_click")
    click_point(point, config, reason="进入当前达人 Creator details")
    wait_after_page_change(config)


def open_chat_window(
    config: dict,
    abort_checker: Optional[Callable[[], None]] = None,
) -> bool:
    def attempt() -> bool:
        click_template_or_fallback(
            template_name=config["templates"]["private_chat_btn"],
            fallback_key="private_chat_fallback",
            config=config,
            description="私聊按钮",
            timeout=config["timeouts"]["template_wait"],
            abort_checker=abort_checker,
        )
        controlled_sleep(config["timing"]["after_click_private_chat_wait"])
        if abort_checker is not None:
            abort_checker()
        return wait_for_chat_window(
            config,
            timeout=config["timeouts"]["chat_window"],
            abort_checker=abort_checker,
        )

    return retry_step(
        action=attempt,
        attempts=config["retry"]["open_chat_attempts"],
        step_name="打开聊天窗口",
        retry_sleep=config["timing"]["retry_sleep"],
    )


def send_photo(
    config: dict,
    abort_checker: Optional[Callable[[], None]] = None,
) -> bool:
    def attempt() -> bool:
        click_template_or_fallback(
            template_name=config["templates"]["send_photo_btn"],
            fallback_key="send_photo_fallback",
            config=config,
            description="发送图片按钮",
            timeout=config["timeouts"]["template_wait"],
            abort_checker=abort_checker,
        )
        if abort_checker is not None:
            abort_checker()
        if not wait_for_file_dialog_ready(config, abort_checker=abort_checker):
            return False
        if not select_file_and_confirm_dialog_closed(config, abort_checker=abort_checker):
            return False
        if not confirm_ok_popup_disappeared(config, abort_checker=abort_checker):
            return False
        controlled_sleep(config["timing"]["after_upload_settle_sleep"])
        if abort_checker is not None:
            abort_checker()
        if ensure_chat_input_available(config, abort_checker=abort_checker):
            log("发图完成后已辅助确认到聊天输入区域")
        else:
            log("发图完成后未及时识别到聊天输入区域，但文件窗口和 OK 弹窗链路已完成，按发图成功继续后续流程", level="WARNING")
        return True

    return retry_step(
        action=attempt,
        attempts=config["retry"]["send_photo_attempts"],
        step_name="发送图片流程",
        retry_sleep=config["timing"]["retry_sleep"],
    )


def send_text_message(
    config: dict,
    message_text: str,
    abort_checker: Optional[Callable[[], None]] = None,
) -> bool:
    def attempt() -> bool:
        if abort_checker is not None:
            abort_checker()
        if not ensure_chat_input_available(config, abort_checker=abort_checker):
            log("发送文本前未确认到聊天输入区域可用", level="WARNING")
            return False

        chat_input = get_coordinate(config, "chat_input")
        send_button = get_coordinate(config, "send_button")
        click_point(chat_input, config, reason="激活聊天输入框")
        if abort_checker is not None:
            abort_checker()
        if not ensure_chat_input_available(config, abort_checker=abort_checker):
            log("点击聊天输入框后，聊天区域状态异常", level="WARNING")
            return False

        paste_text(message_text, config)
        click_point(send_button, config, reason="发送文本消息")
        controlled_sleep(config["timing"]["after_send_text_wait"])

        if abort_checker is not None:
            abort_checker()
        if not ensure_chat_input_available(config, abort_checker=abort_checker):
            log("点击 Send 后聊天区域状态异常，优先按收尾逻辑返回列表", level="WARNING")
            return False
        return True

    return retry_step(
        action=attempt,
        attempts=config["retry"]["send_text_attempts"],
        step_name="发送文本流程",
        retry_sleep=config["timing"]["retry_sleep"],
    )


def process_one_creator(index: int, runtime_inputs: dict, config: dict) -> None:
    log(f"开始处理达人 #{index}")
    should_recover = True
    try:
        check_abort()
        open_creator_detail(config)

        if not open_chat_window(config):
            raise StepFailedException("连续 3 次点击私聊按钮后，仍未识别到 Send a message。")

        if not send_photo(config):
            raise StepFailedException("发送图片流程未能稳定完成。")

        if not send_text_message(config, str(runtime_inputs["message_text"])):
            raise StepFailedException("发送文本流程未能稳定完成。")

        record_creator_result(index, "SUCCESS", "图片和文本都已完成发送。")
    except UserAbortException:
        raise
    except Exception as exc:
        save_failure_screenshot(f"creator_{index}_failed")
        record_creator_result(index, "FAILED", str(exc))
    finally:
        if should_recover:
            try:
                recover_to_creator_list(config, reason="当前达人流程结束或异常", creator_index=index)
            except UserAbortException:
                raise
            except Exception as close_exc:
                save_failure_screenshot(f"creator_{index}_close_failed")
                log(f"关闭达人页面时出现异常: {close_exc}", level="ERROR")


def prepare_next_creator(runtime_inputs: dict, config: dict) -> None:
    controlled_sleep(config["timing"]["after_return_list_sleep"])
    scroll_once(config, int(runtime_inputs["scroll_distance"]))
    controlled_sleep(config["timing"]["after_scroll_settle_sleep"])


def run_startup_checks(config: dict) -> None:
    log("开始启动前资源检查")
    templates_ok = validate_required_templates(config)
    if templates_ok:
        log("启动前资源检查完成，未发现缺失项")
        return

    log("启动前资源检查发现问题。模板缺失或不可读时，相关步骤会记录错误并尽量退回后备坐标。", level="WARNING")


def main() -> None:
    try:
        enforce_authorization()
    except AuthorizationError as exc:
        print(f"授权失败，程序已停止: {exc}")
        return

    config = load_config()
    runtime_inputs = get_runtime_inputs()
    run_startup_checks(config)

    log("TikTok_BD_Auto 主流程开始")
    log(
        "本次运行参数: "
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
        for index in range(1, total_creators + 1):
            process_one_creator(index, runtime_inputs, config)
            if index < total_creators:
                prepare_next_creator(runtime_inputs, config)

        log("全部达人处理完成")
        print("运行结束。请查看 logs 文件夹中的日志和异常截图。")
    except UserAbortException as exc:
        log(str(exc), level="WARNING")
        save_failure_screenshot("manual_abort")
        print(str(exc))


if __name__ == "__main__":
    main()
