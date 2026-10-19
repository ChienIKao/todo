"""todo 指令與 MCP server 的進入點：python todo.py ls、python todo.py mcp"""
import sys

from agent_todo.cli import main

if __name__ == "__main__":
    sys.exit(main())
