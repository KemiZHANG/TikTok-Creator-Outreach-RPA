from utils import UserAbortException, check_abort, controlled_sleep, load_config, log, scroll_once


def main() -> None:
    config = load_config()
    print("TikTok_BD_Auto 滚轮测试工具")
    print("请先把 TikTok Shop Affiliate Centre 页面切到前台。")
    print("程序会把鼠标移动到 config.json 里的 scroll_area，然后执行一次滚动。")

    raw_value = input("请输入本次测试的滚轮值（例如 -520 或 520）: ").strip()
    amount = int(raw_value)

    print("3 秒后开始，请勿移动页面焦点。")
    log(f"开始执行滚轮测试，滚轮值={amount}")
    try:
        controlled_sleep(3)
        check_abort()
        scroll_once(config, amount)
        print("滚轮测试完成。请观察是否刚好滚动一个达人卡片高度。")
        log("滚轮测试完成")
    except UserAbortException as exc:
        print(str(exc))
        log(str(exc), level="WARNING")


if __name__ == "__main__":
    main()
