"""Command-line entry point for the local PfinderWithAI Demo.

The real command implementation is added with the application module. Keeping
this entry point dependency-free makes the initial project package installable
before external adapters are configured.
"""


def main() -> None:
    """Confirm that the project package and console entry point are available."""

    print("PfinderWithAI project skeleton is ready.")


if __name__ == "__main__":
    main()

