import sys
from display.display_service import DisplayService


def main():
    text = sys.argv[1] if len(sys.argv) > 1 else "Hello World"
    service = DisplayService()
    service.print_line(text)


if __name__ == "__main__":
    main()
