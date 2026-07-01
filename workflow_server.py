from __future__ import annotations

import argparse

from src.visual_workflow.api_server import create_server


def main() -> None:
    parser = argparse.ArgumentParser(description="投研拖拽工作流 Demo")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    server = create_server(host=args.host, port=args.port)
    print(f"投研工作流编辑器: http://{args.host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
