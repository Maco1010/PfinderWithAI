"""PfinderWithAI 本地 Demo 的命令行入口。

完整命令会在应用层模块中实现。当前入口不依赖外部组件，确保尚未配置
任何 Adapter 时，项目包仍然可以安装并验证入口是否可用。
"""


def main() -> None:
    """确认项目包和控制台入口可以正常加载。"""

    print("PfinderWithAI project skeleton is ready.")


if __name__ == "__main__":
    main()
