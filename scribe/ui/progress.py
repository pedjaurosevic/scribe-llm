"""
Rich Progress bars and spinners for Scribe TUI.
"""

from __future__ import annotations

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeRemainingColumn,
)


def create_default_progress() -> Progress:
    """
    Create the default Scribe progress bar configuration.

    Returns:
        Configured Progress instance
    """
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
        console=None,
    )


class StreamProgress:
    """
    Progress bar for streaming responses.

    Usage:
        with StreamProgress(console) as progress:
            for chunk in adapter.streaming_complete(messages, progress.callback):
                yield chunk
    """

    def __init__(self, console: Console, description: str = "Generating"):
        """
        Initialize streaming progress.

        Args:
            console: Rich Console instance
            description: Progress bar description
        """
        self.console = console
        self.description = description
        self.progress: Progress | None = None
        self.task_id: TaskID | None = None
        self.text = ""

    def __enter__(self):
        """Start the progress bar."""
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[cyan]{task.completed} chars"),
            console=self.console,
        )
        self.progress.__enter__()
        self.task_id = self.progress.add_task(self.description, total=None)
        return self

    def __exit__(self, *args):
        """Stop the progress bar."""
        if self.progress:
            self.progress.__exit__(*args)

    def callback(self, chunk: str):
        """
        Callback for streaming chunks.

        Args:
            chunk: Text chunk from stream
        """
        self.text += chunk
        if self.progress and self.task_id is not None:
            self.progress.update(
                self.task_id,
                description=f"{self.description} ({len(self.text)} chars)",
            )

    def update_description(self, description: str):
        """
        Update the progress description.

        Args:
            description: New description
        """
        if self.progress and self.task_id is not None:
            self.progress.update(self.task_id, description=description)


class TokenCounter:
    """
    Simple token counter for progress display.

    Estimates token count based on text length.
    """

    CHARS_PER_TOKEN = 4

    def __init__(self, progress: Progress, task_id: TaskID):
        """
        Initialize counter.

        Args:
            progress: Rich Progress instance
            task_id: Task ID to update
        """
        self.progress = progress
        self.task_id = task_id
        self.tokens = 0
        self.chars = 0

    def add(self, text: str):
        """
        Add text and update counter.

        Args:
            text: Text to count
        """
        self.chars += len(text)
        self.tokens = self.chars // self.CHARS_PER_TOKEN

        if self.progress:
            self.progress.update(
                self.task_id,
                completed=self.tokens,
                total=max(self.tokens, 1),
            )

    @property
    def estimated_tokens(self) -> int:
        """Get estimated token count."""
        return self.tokens
