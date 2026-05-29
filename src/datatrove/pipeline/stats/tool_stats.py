import re

from datatrove.data import Document
from datatrove.io import DataFolderLike
from datatrove.pipeline.stats.base import BaseStats
from datatrove.pipeline.stats.config import DEFAULT_TOP_K_CONFIG, GROUP, TopKConfig


class ToolStats(BaseStats):
    """
    Stats over tool calls and tool responses in a chat-format document.

    Reads ``metadata[messages_field]`` (HF/OpenAI conversation schema). Tool
    calls are counted from each assistant message's ``tool_calls`` field when
    present; otherwise the message content is scanned for tags matching
    ``text_tool_call_pattern``. Tool responses are messages with ``role == "tool"``.

    Available metrics:
    n_messages, n_user_turns, n_assistant_turns, n_tool_responses, n_tool_turns,
    n_tool_calls, n_tools_available, n_simple_turns, n_multiple_turns,
    n_parallel_turns, n_parallel_multiple_turns, is_multi_turn,
    max_tools_per_turn

    Categorical metrics follow BFCL (Berkeley Function Calling Leaderboard)
    semantics. Per assistant turn, let ``n_calls`` = number of tool calls in
    that turn and ``zoo_size`` = ``len(metadata["tools"])`` (size of the
    available-tool zoo). The four single-turn categories are the strict cross
    of those two axes:

        | category                    | n_calls  | zoo_size |
        | --------------------------- | -------- | -------- |
        | n_simple_turns              | == 1     | == 1     |
        | n_multiple_turns            | == 1     |  > 1     |
        | n_parallel_turns            |  > 1     | == 1     |
        | n_parallel_multiple_turns   |  > 1     |  > 1     |

    ``is_multi_turn`` is the per-document axis: ``1`` iff
    ``n_user_turns > 1``.

    Boundaries are strict (``==``/``>``), matching BFCL exactly. When
    ``metadata["tools"]`` is missing, ``zoo_size == 0`` and the turn falls
    into **none** of the four single-turn categories.

    ``n_tool_responses`` counts every ``role == "tool"`` message individually
    (one per ``tool_call_id``), while ``n_tool_turns`` collapses consecutive
    runs of them — matching how chat templates render a single tool-response
    turn even when the underlying messages list contains several entries.
    """

    name = "🛠️ Tool stats"

    def __init__(
        self,
        output_folder: DataFolderLike,
        messages_field: str = "messages",
        text_tool_call_pattern: str = r"<tool_call\b[^>]*>.*?</tool_call>",
        groups_to_compute: list[GROUP] | None = None,
        histogram_round_digits: int = 0,
        top_k_config: TopKConfig = DEFAULT_TOP_K_CONFIG,
    ) -> None:
        super().__init__(
            output_folder,
            groups_to_compute=groups_to_compute or ["summary", "histogram"],
            histogram_round_digits=histogram_round_digits,
            top_k_config=top_k_config,
        )
        self.messages_field = messages_field
        self._tool_call_re = re.compile(text_tool_call_pattern, re.DOTALL)

    def _content_to_text(self, content) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        return ""

    def _count_tool_calls(self, msg: dict) -> int:
        calls = msg.get("tool_calls")
        if calls:
            return len(calls)
        return len(self._tool_call_re.findall(self._content_to_text(msg.get("content"))))

    def extract_stats(self, doc: Document) -> dict[str, int | float]:
        messages = doc.metadata.get(self.messages_field) or []
        if not isinstance(messages, list):
            messages = []

        tools = doc.metadata.get("tools") or []
        zoo_size = len(tools) if isinstance(tools, list) else 0

        n_user = n_assistant = n_tool = n_tool_turns = 0
        n_tool_calls = max_calls_per_turn = 0
        n_simple = n_multiple = n_parallel = n_parallel_multiple = 0
        prev_role = None

        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            if role == "user":
                n_user += 1
            elif role == "assistant":
                n_assistant += 1
                n_calls = self._count_tool_calls(msg)
                n_tool_calls += n_calls
                if n_calls > max_calls_per_turn:
                    max_calls_per_turn = n_calls
                if n_calls == 1 and zoo_size == 1:
                    n_simple += 1
                elif n_calls == 1 and zoo_size > 1:
                    n_multiple += 1
                elif n_calls > 1 and zoo_size == 1:
                    n_parallel += 1
                elif n_calls > 1 and zoo_size > 1:
                    n_parallel_multiple += 1
            elif role == "tool":
                n_tool += 1
                if prev_role != "tool":
                    n_tool_turns += 1
            prev_role = role

        return {
            "n_messages": len(messages),
            "n_user_turns": n_user,
            "n_assistant_turns": n_assistant,
            "n_tool_responses": n_tool,
            "n_tool_turns": n_tool_turns,
            "n_tool_calls": n_tool_calls,
            "n_tools_available": zoo_size,
            "n_simple_turns": n_simple,
            "n_multiple_turns": n_multiple,
            "n_parallel_turns": n_parallel,
            "n_parallel_multiple_turns": n_parallel_multiple,
            "is_multi_turn": int(n_user > 1),
            "max_tools_per_turn": max_calls_per_turn,
        }
