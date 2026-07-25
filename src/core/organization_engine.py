"""Organization engine — moves renamed files into organized folder structures."""

import shutil
from pathlib import Path
from datetime import datetime
from loguru import logger

from ..models.file_item import FileItem, FileStatus
from ..core.rename_history import RenameHistory, RenameRecord


RULE_HANDLERS = {
    "by_date": lambda meta, pattern: _organize_by_date(meta, pattern),
    "by_type": lambda meta, pattern: _organize_by_type(meta, pattern),
    "by_category": lambda meta, pattern: _organize_by_category(meta, pattern),
    "by_project": lambda meta, pattern: _organize_by_project(meta, pattern),
}


def organize(
    item: FileItem,
    rule: str,
    target_root: str,
    history: RenameHistory = None,
    batch_id: str = "",
) -> str | None:
    """Move a renamed file to an organized folder.

    Args:
        item: The renamed FileItem (status should be APPLIED).
        rule: Organization rule (by_date, by_type, by_category, by_project).
        target_root: Root directory for organized files.
        history: Optional RenameHistory for undo support.
        batch_id: Batch ID for undo grouping.

    Returns:
        New path as string if moved, None if no move needed.
    """
    if item.status != FileStatus.APPLIED:
        logger.warning(f"文件未重命名，无法归类: {item.original_name}")
        return None

    handler = RULE_HANDLERS.get(rule)
    if not handler:
        logger.warning(f"未知归类规则: {rule}")
        return None

    target_dir = handler(item.metadata, target_root)
    if not target_dir:
        return None

    # Create target directory
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    # Move file
    old_path = item.original_path
    new_path = target_dir / item.final_name

    # Handle conflicts
    if new_path.exists():
        base, ext = new_path.stem, new_path.suffix
        counter = 1
        while new_path.exists():
            new_path = target_dir / f"{base}_{counter}{ext}"
            counter += 1

    try:
        shutil.move(str(old_path), str(new_path))
        logger.info(f"文件归类: {old_path.name} → {new_path}")

        # Record for undo
        if history and batch_id:
            history.record(RenameRecord(
                batch_id=batch_id,
                old_path=old_path,
                new_path=new_path,
                file_size=item.file_size,
            ))

        item.original_path = new_path
        return str(new_path)

    except Exception as e:
        logger.error(f"归类失败: {old_path} — {e}")
        return None


def organize_batch(
    items: list[FileItem],
    rule: str,
    target_root: str,
    history: RenameHistory = None,
    batch_id: str = "",
) -> tuple[int, int]:
    """Organize a batch of files.

    Returns:
        (success_count, failed_count)
    """
    success = 0
    failed = 0

    for item in items:
        result = organize(item, rule, target_root, history, batch_id)
        if result:
            success += 1
        else:
            failed += 1

    logger.info(f"批量归类完成: {success} 成功, {failed} 失败")
    return success, failed


def _organize_by_date(metadata: dict, root: str) -> Path:
    """Organize by date: root/YYYY/MM/"""
    date_str = metadata.get("date", "")
    if not date_str or date_str == "unknown":
        today = datetime.now()
        return Path(root) / str(today.year) / f"{today.month:02d}"

    try:
        dt = datetime.fromisoformat(date_str[:10])
        return Path(root) / str(dt.year) / f"{dt.month:02d}"
    except (ValueError, TypeError):
        today = datetime.now()
        return Path(root) / str(today.year) / f"{today.month:02d}"


def _organize_by_type(metadata: dict, root: str) -> Path:
    """Organize by document type: root/invoices/, root/contracts/, etc."""
    doc_type = metadata.get("type", "")
    if not doc_type:
        # Try AI fields
        doc_type = metadata.get("ai_type", "other")
    return Path(root) / doc_type


def _organize_by_category(metadata: dict, root: str) -> Path:
    """Organize by category tag."""
    tags = metadata.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]
    category = tags[0] if tags else "uncategorized"
    return Path(root) / category


def _organize_by_project(metadata: dict, root: str) -> Path:
    """Organize by project name."""
    project = metadata.get("project", metadata.get("title", "general"))
    # Clean project name for folder use
    project = project.strip().replace(" ", "-").replace("/", "-")[:50]
    return Path(root) / project
