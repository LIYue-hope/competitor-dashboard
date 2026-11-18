"""运行一个网站的采集脚本，失败时重试。"""

import argparse
import subprocess
import sys
import time


MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 30


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("script", help="采集脚本路径")
    args = parser.parse_args()

    command = [sys.executable, args.script]
    for retries_used in range(MAX_RETRIES + 1):
        return_code = subprocess.run(command, check=False).returncode
        if return_code == 0 or retries_used == MAX_RETRIES:
            return return_code

        print(
            f"{args.script} 采集失败（退出码 {return_code}），"
            f"{RETRY_DELAY_SECONDS} 秒后进行第 {retries_used + 1}/{MAX_RETRIES} 次重试",
            flush=True,
        )
        time.sleep(RETRY_DELAY_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
